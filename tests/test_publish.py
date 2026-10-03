import json
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


def test_upload_multipart_filename_and_authorization(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return json.dumps(RESPONSE).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.method == "POST"
            assert request.get_header("Authorization") == "Bearer test-token"
            assert b'filename="maintain.json"' in request.data
            assert b'name="change_note"' in request.data
            assert b"Content-Type: application/json" in request.data
            return Response()

    monkeypatch.setattr("automas_api.publish.build_opener", lambda *a: Opener())
    assert _upload(URL, "test-token", b"{}", "CI run") == RESPONSE
