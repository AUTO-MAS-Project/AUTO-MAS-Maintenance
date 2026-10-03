import json
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError

import pytest

from automas_api.publish import PublishError, _upload, publish

POLICY = {
    "schema_version": 1,
    "generated_at": "2026-10-03T10:00:00+08:00",
    "games": {"arknights": {"maintenance": None}, "endfield": {"maintenance": None}},
}
URL = "https://data.auto-mas.top/api/v1/files/project/category/maintain/download"
RESPONSE = {
    "code": 0,
    "data": {
        "id": 17,
        "project_key": "project",
        "category_key": "category",
        "file_key": "maintain",
        "published_version_no": 2,
        "version": {"version_no": 2, "review_status": "approved"},
    },
}


def invoke(**kwargs):
    return publish(
        json.dumps(POLICY).encode(),
        file_id=17,
        public_url=URL,
        token="test-token",
        sleep=lambda _: None,
        **kwargs,
    )


def missing(*args, **kwargs):
    raise HTTPError(URL, 404, "Not found", {}, None)


def test_publish_verifies_public_content():
    downloads = iter([None, POLICY])

    def upload(url, token, content, note):
        assert url.endswith("/api/v1/user/files/17/versions")
        assert token == "test-token"
        assert json.loads(content) == POLICY
        return RESPONSE

    result = invoke(get=lambda *a, **k: next(downloads), upload=upload)
    assert result["state"] == "published"
    assert result["version_no"] == 2


def test_unchanged_does_not_upload():
    def upload(*args):
        pytest.fail("Unchanged public policy must not upload")

    assert invoke(get=lambda *a, **k: POLICY, upload=upload)["state"] == "unchanged"


def test_pending_is_not_success():
    response = {
        "code": 0,
        "data": {
            **RESPONSE["data"],
            "published_version_no": 1,
            "version": {"version_no": 2, "review_status": "pending"},
        },
    }
    with pytest.raises(PublishError, match="not published"):
        invoke(get=missing, upload=lambda *a: response)


def test_stale_public_download_is_not_success():
    with pytest.raises(PublishError, match="does not match maintain.json"):
        invoke(get=missing, upload=lambda *a: RESPONSE)


@pytest.mark.parametrize("published", [True, False])
def test_conflict_requires_matching_public_content(published):
    downloads = iter([None, POLICY])

    def upload(*args):
        raise HTTPError(URL, 409, "Conflict", {}, None)

    if published:
        assert invoke(get=lambda *a, **k: next(downloads), upload=upload)["state"] == "published"
    else:
        with pytest.raises(PublishError, match="does not match"):
            invoke(get=missing, upload=upload)


@pytest.fixture
def upload_server(tmp_path, monkeypatch):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    config = tmp_path / "openssl.cnf"
    config.write_text(
        "[req]\ndistinguished_name=dn\nx509_extensions=ext\n"
        "[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost\n"
    )
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-config",
            str(config),
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        capture_output=True,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.server.requests.append(
                {
                    "path": self.path,
                    "headers": self.headers,
                    "body": self.rfile.read(int(self.headers.get("Content-Length", "0"))),
                }
            )
            index = min(len(self.server.requests) - 1, len(self.server.responses) - 1)
            response = self.server.responses[index]
            body = json.dumps(response.get("body", {})).encode()
            self.send_response(response["status"])
            for name, value in response.get("headers", {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.requests = []
    server.responses = [{"status": 201, "body": RESPONSE}]
    server.url = f"https://localhost:{server.server_port}/versions"
    monkeypatch.setenv("CURL_CA_BUNDLE", str(cert))
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_curl_upload_multipart_filename_and_authorization(upload_server):
    assert _upload(upload_server.url, "test-token", b"{}", "CI run") == RESPONSE
    request = upload_server.requests[0]
    assert request["headers"]["Authorization"] == "Bearer test-token"
    assert b'filename="maintain.json"' in request["body"]
    assert b'name="change_note"' in request["body"]
    assert b"Content-Type: application/json" in request["body"]


@pytest.mark.parametrize("status", [307, 308])
def test_curl_follows_redirect_and_retains_post_content(upload_server, status):
    upload_server.responses = [
        {"status": status, "headers": {"Location": "/final"}},
        {"status": 201, "body": RESPONSE},
    ]
    assert _upload(upload_server.url, "test-token", b"{}", "CI run") == RESPONSE
    original, redirected = upload_server.requests
    assert redirected["path"] == "/final"
    assert redirected["body"] == original["body"]
    assert redirected["headers"]["Authorization"] == "Bearer test-token"


def test_curl_retains_cookie_on_redirect(upload_server):
    upload_server.responses = [
        {
            "status": 307,
            "headers": {"Location": "/final", "Set-Cookie": "upload_gate=passed; Path=/; Secure"},
        },
        {"status": 201, "body": RESPONSE},
    ]
    assert _upload(upload_server.url, "test-token", b"{}", "CI run") == RESPONSE
    assert upload_server.requests[1]["headers"]["Cookie"] == "upload_gate=passed"


def test_curl_redirect_loop_is_failure(upload_server):
    upload_server.responses = [{"status": 307, "headers": {"Location": "/versions"}}]
    with pytest.raises(PublishError, match="HTTP 307"):
        _upload(upload_server.url, "test-token", b"{}", "CI run")
    assert len(upload_server.requests) == 6


def test_curl_307_without_location_is_not_success(upload_server):
    upload_server.responses = [{"status": 307}]
    with pytest.raises(PublishError, match="HTTP 307"):
        _upload(upload_server.url, "test-token", b"{}", "CI run")


def test_curl_duplicate_content_preserves_409_handling(upload_server):
    upload_server.responses = [{"status": 409}]
    with pytest.raises(HTTPError) as error:
        _upload(upload_server.url, "test-token", b"{}", "CI run")
    assert error.value.code == 409


def test_curl_rejects_https_downgrade_without_exposing_token(upload_server, caplog):
    caplog.set_level("INFO", logger="automas_api.publish")
    upload_server.responses = [
        {"status": 307, "headers": {"Location": "http://localhost/upload?token=test-token"}}
    ]
    with pytest.raises(PublishError) as error:
        _upload(upload_server.url, "test-token", b"{}", "CI run")
    assert "test-token" not in str(error.value) + caplog.text
    assert len(upload_server.requests) == 1
