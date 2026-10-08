import hashlib
from pathlib import Path

import httpx
import pytest

from zhihupost.client import ZhihuClient
from zhihupost.images import ImageUploader, resolve_source


IMAGE_URL = "https://pic4.zhimg.com/80/v2-"


def make_uploader(*, remote_transport=None, payload=None, oss_put=None):
    if payload is None:
        payload = {
            "upload_token": {
                "access_id": "temporary-id",
                "access_key": "temporary-key",
                "access_token": "temporary-token",
            },
            "upload_file": {"object_key": "image/object"},
        }

    def preflight(request):
        assert request.method == "POST"
        assert str(request.url) == "https://api.zhihu.com/images"
        return httpx.Response(200, json=payload, request=request)

    client = ZhihuClient(
        "z_c0=synthetic",
        transport=httpx.MockTransport(preflight),
    )
    uploader = ImageUploader(
        client,
        oss_put=oss_put if oss_put is not None else lambda token, key, data: None,
        remote_transport=remote_transport,
    )
    return uploader


def close(uploader):
    uploader.client.close()


def test_local_relative_and_percent_encoded_paths_preserve_suffix_and_hash(tmp_path):
    image_bytes = b"local-image"
    image_path = tmp_path / "picture one.JpG"
    image_path.write_bytes(image_bytes)
    calls = []
    uploader = make_uploader(
        oss_put=lambda token, key, data: calls.append((token, key, data))
    )
    try:
        data, suffix = resolve_source("picture%20one.JpG", tmp_path)
        assert (data, suffix) == (image_bytes, ".JpG")
        result = uploader.upload("picture%20one.JpG", tmp_path)
    finally:
        close(uploader)

    digest = hashlib.md5(image_bytes).hexdigest()
    assert result == f"{IMAGE_URL}{digest}.JpG"
    assert len(calls) == 1
    assert calls[0][1:] == ("image/object", image_bytes)


def test_remote_image_download_has_no_zhihu_cookie_and_posts_hash(tmp_path):
    image_bytes = b"remote-image"
    remote_requests = []
    api_requests = []
    oss_calls = []

    def remote(request):
        remote_requests.append(request)
        return httpx.Response(200, content=image_bytes, request=request)

    payload = {
        "upload_token": {
            "access_id": "temporary-id",
            "access_key": "temporary-key",
            "access_token": "temporary-token",
        },
        "upload_file": {"object_key": "object-key"},
    }

    def preflight(request):
        api_requests.append(request)
        return httpx.Response(200, json=payload, request=request)

    client = ZhihuClient("z_c0=synthetic", transport=httpx.MockTransport(preflight))
    uploader = ImageUploader(
        client,
        oss_put=lambda token, key, data: oss_calls.append((token, key, data)),
        remote_transport=httpx.MockTransport(remote),
    )
    try:
        result = uploader.upload("https://cdn.example/image%20name.png", tmp_path)
    finally:
        client.close()

    assert len(remote_requests) == 1
    assert remote_requests[0].headers.get("cookie") is None
    assert remote_requests[0].url == "https://cdn.example/image%20name.png"
    assert api_requests[0].method == "POST"
    assert str(api_requests[0].url) == "https://api.zhihu.com/images"
    assert api_requests[0].read() == (
        '{"image_hash":"'
        + hashlib.md5(image_bytes).hexdigest()
        + '","source":"answer"}'
    ).encode()
    assert result == f"{IMAGE_URL}{hashlib.md5(image_bytes).hexdigest()}.png"
    assert oss_calls[0][1:] == ("object-key", image_bytes)


def test_remote_non_success_status_fails_before_preflight(tmp_path):
    preflight_calls = []

    def remote(request):
        return httpx.Response(404, request=request)

    def preflight(request):
        preflight_calls.append(request)
        return httpx.Response(200, json={"upload_file": {"object_key": "x"}}, request=request)

    client = ZhihuClient("z_c0=synthetic", transport=httpx.MockTransport(preflight))
    uploader = ImageUploader(client, remote_transport=httpx.MockTransport(remote))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            uploader.upload("https://cdn.example/missing.png", tmp_path)
    finally:
        client.close()

    assert preflight_calls == []


def test_preflight_non_success_status_does_not_use_fallback(tmp_path):
    (tmp_path / "image.png").write_bytes(b"image")
    oss_calls = []

    class RejectedClient:
        def request(self, method, url, **kwargs):
            request = httpx.Request(method, url)
            return httpx.Response(401, json={}, request=request)

    uploader = ImageUploader(
        RejectedClient(),
        oss_put=lambda *args: oss_calls.append(args),
    )
    with pytest.raises(httpx.HTTPStatusError):
        uploader.upload("image.png", tmp_path)

    assert oss_calls == []


@pytest.mark.parametrize("source", ["diagram.svg", "https://cdn.example/diagram.SvG"])
def test_svg_is_rejected_before_any_http_call(tmp_path, source):
    image_path = tmp_path / "diagram.svg"
    image_path.write_bytes(b"<svg/>")
    api_calls = []
    remote_calls = []

    def preflight(request):
        api_calls.append(request)
        return httpx.Response(200, json={}, request=request)

    def remote(request):
        remote_calls.append(request)
        return httpx.Response(200, content=b"svg", request=request)

    client = ZhihuClient("z_c0=synthetic", transport=httpx.MockTransport(preflight))
    uploader = ImageUploader(client, remote_transport=httpx.MockTransport(remote))
    try:
        with pytest.raises(ValueError, match="SVG"):
            uploader.upload(source, tmp_path)
    finally:
        client.close()

    assert api_calls == []
    assert remote_calls == []


@pytest.mark.parametrize("source", ["ftp://cdn.example/image.png", "data:image/png;base64,AA=="])
def test_unsupported_scheme_is_rejected_before_any_http_call(tmp_path, source):
    api_calls = []
    remote_calls = []

    def preflight(request):
        api_calls.append(request)
        return httpx.Response(200, json={}, request=request)

    def remote(request):
        remote_calls.append(request)
        return httpx.Response(200, content=b"image", request=request)

    client = ZhihuClient("z_c0=synthetic", transport=httpx.MockTransport(preflight))
    uploader = ImageUploader(client, remote_transport=httpx.MockTransport(remote))
    try:
        with pytest.raises(ValueError, match="scheme"):
            uploader.upload(source, tmp_path)
    finally:
        client.close()

    assert api_calls == []
    assert remote_calls == []


def test_missing_upload_token_uses_hash_fallback_without_oss(tmp_path):
    image_bytes = b"fallback"
    (tmp_path / "fallback.webp").write_bytes(image_bytes)
    oss_calls = []
    uploader = make_uploader(
        payload={"upload_file": {"object_key": "ignored"}},
        oss_put=lambda *args: oss_calls.append(args),
    )
    try:
        result = uploader.upload("fallback.webp", tmp_path)
    finally:
        close(uploader)

    assert result == f"{IMAGE_URL}{hashlib.md5(image_bytes).hexdigest()}.webp"
    assert oss_calls == []


def test_malformed_present_upload_token_fails_instead_of_using_fallback(tmp_path):
    (tmp_path / "broken.png").write_bytes(b"broken")
    uploader = make_uploader(
        payload={"upload_token": {}, "upload_file": {"object_key": "key"}}
    )
    try:
        with pytest.raises(ValueError, match="upload credentials"):
            uploader.upload("broken.png", tmp_path)
    finally:
        close(uploader)


def test_temporary_credentials_and_object_key_reach_oss_and_failure_surfaces(tmp_path):
    image_bytes = b"oss-upload"
    (tmp_path / "upload.png").write_bytes(image_bytes)
    token = {
        "access_id": "temporary-id",
        "access_key": "temporary-key",
        "access_token": "temporary-token",
    }
    observed = []

    def fail_put(received_token, key, data):
        observed.append((received_token, key, data))
        raise RuntimeError("mock OSS failure")

    uploader = make_uploader(
        payload={"upload_token": token, "upload_file": {"object_key": "returned-key"}},
        oss_put=fail_put,
    )
    try:
        with pytest.raises(RuntimeError, match="mock OSS failure"):
            uploader.upload("upload.png", tmp_path)
    finally:
        close(uploader)

    assert observed == [(token, "returned-key", image_bytes)]


def test_default_oss_adapter_uses_fixed_public_target_and_waits_for_put(
    tmp_path, monkeypatch
):
    image_bytes = b"sdk-upload"
    (tmp_path / "sdk.gif").write_bytes(image_bytes)
    observed = {}

    class FakeBucket:
        def __init__(self):
            self.put_completed = False

        def put_object(self, key, data):
            observed["put"] = (key, data)
            self.put_completed = True
            return object()

    fake_bucket = FakeBucket()

    def fake_sts_auth(*args):
        observed["sts"] = args
        return "fake-auth"

    def fake_bucket_constructor(*args, **kwargs):
        observed["bucket_args"] = args
        observed["bucket_kwargs"] = kwargs
        return fake_bucket

    monkeypatch.setattr("zhihupost.images.oss2.StsAuth", fake_sts_auth)
    monkeypatch.setattr("zhihupost.images.oss2.Bucket", fake_bucket_constructor)
    uploader = make_uploader()
    try:
        uploader.oss_put = None
        uploader.upload("sdk.gif", tmp_path)
    finally:
        close(uploader)

    assert observed["sts"] == ("temporary-id", "temporary-key", "temporary-token")
    assert observed["bucket_args"] == (
        "fake-auth",
        "https://zhihu-pics-upload.zhimg.com",
        "zhihu-pics",
    )
    assert observed["bucket_kwargs"] == {
        "is_cname": True,
        "region": "oss-cn-hangzhou",
    }
    assert observed["put"] == ("image/object", image_bytes)
    assert fake_bucket.put_completed


def test_missing_local_image_fails_without_preflight(tmp_path):
    calls = []
    uploader = make_uploader()
    original_request = uploader.client.request

    def record_request(*args, **kwargs):
        calls.append((args, kwargs))
        return original_request(*args, **kwargs)

    uploader.client.request = record_request
    try:
        with pytest.raises(FileNotFoundError):
            uploader.upload("missing.png", tmp_path)
    finally:
        close(uploader)

    assert calls == []
