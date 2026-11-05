from __future__ import annotations

import gzip
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from conftest import FIXTURE_DATE, METADATA_DATE, FixtureClient, fixture_bytes, fixture_trains

from train_elt import extract
from train_elt.settings import manifest_path


def test_extract_trains_lands_payload_and_manifest(paths):
    result = extract.extract_trains(FixtureClient(), paths, FIXTURE_DATE)

    original = fixture_bytes(f"trains_{FIXTURE_DATE}.json")
    assert result.records == 7 and not result.skipped
    assert result.path == paths.trains_file(FIXTURE_DATE)
    assert gzip.decompress(result.path.read_bytes()) == original

    manifest = json.loads(manifest_path(result.path).read_text())
    assert manifest["sha256"] == hashlib.sha256(original).hexdigest()
    assert manifest["records"] == 7
    assert manifest["source_url"].endswith(f"/trains/{FIXTURE_DATE}")


def test_extract_skips_landed_day_unless_forced(paths):
    client = FixtureClient()
    extract.extract_trains(client, paths, FIXTURE_DATE)
    assert extract.extract_trains(client, paths, FIXTURE_DATE).skipped
    assert client.calls == [f"/trains/{FIXTURE_DATE}"]

    assert not extract.extract_trains(client, paths, FIXTURE_DATE, force=True).skipped
    assert len(client.calls) == 2


def test_extract_rejects_train_from_another_day(paths):
    trains = fixture_trains()
    trains[0]["departureDate"] = "2026-11-03"
    with pytest.raises(extract.ExtractError, match="expected 2026-11-04"):
        extract.extract_trains(FixtureClient(trains), paths, FIXTURE_DATE)
    assert not paths.trains_file(FIXTURE_DATE).exists()


def test_extract_rejects_non_array_response(paths):
    client = FixtureClient()
    client.responses[f"/trains/{FIXTURE_DATE}"] = b'{"error": "maintenance"}'
    with pytest.raises(extract.ExtractError, match="expected a JSON array"):
        extract.extract_trains(client, paths, FIXTURE_DATE)


def test_extract_metadata_lands_both_snapshots(paths):
    results = extract.extract_metadata(FixtureClient(), paths, fetched_date=METADATA_DATE)
    assert results["stations"].records == 29
    assert results["cause_categories"].records == 15
    assert paths.metadata_file("stations", METADATA_DATE).exists()


# --- the real HTTP client, against a local server -------------------------------------


class _Handler(BaseHTTPRequestHandler):
    statuses: list[int] = []
    seen_headers: list[dict] = []

    def do_GET(self):  # noqa: N802 (http.server API)
        type(self).seen_headers.append(dict(self.headers))
        status = type(self).statuses.pop(0)
        if status != 200:
            self.send_response(status)
            self.end_headers()
            return
        body = gzip.compress(b'[{"ok": true}]')
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    _Handler.statuses = []
    _Handler.seen_headers = []
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_client_retries_transient_errors_and_decodes_gzip(server):
    _Handler.statuses = [503, 429, 200]
    delays = []
    client = extract.DigitrafficClient(base_url=server, sleep=delays.append, backoff_seconds=1)

    assert client.get("/anything") == b'[{"ok": true}]'
    assert delays == [1, 2]  # exponential backoff
    assert _Handler.seen_headers[0]["Digitraffic-User"].startswith("train-punctuality-elt")


def test_client_does_not_retry_client_errors(server):
    _Handler.statuses = [404]
    delays = []
    client = extract.DigitrafficClient(base_url=server, sleep=delays.append)

    with pytest.raises(extract.ExtractError, match="HTTP 404"):
        client.get("/missing")
    assert delays == []


def test_client_gives_up_after_max_retries(server):
    _Handler.statuses = [503, 503, 503]
    client = extract.DigitrafficClient(base_url=server, sleep=lambda _: None, max_retries=2)
    with pytest.raises(extract.ExtractError, match="HTTP 503"):
        client.get("/flaky")
