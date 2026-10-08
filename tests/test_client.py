import httpx
import pytest

from zhihupost.client import ZhihuAPIError, ZhihuClient


def test_client_sends_cookie_xsrf_user_agent_and_explicit_timeout():
    seen = {}

    def handler(request):
        seen["cookie"] = request.headers["cookie"]
        seen["xsrf"] = request.headers["x-xsrftoken"]
        seen["user_agent"] = request.headers["user-agent"]
        seen["timeout"] = request.extensions["timeout"]
        return httpx.Response(200, json={"id": "user-1"})

    client = ZhihuClient(
        "Cookie: z_c0=secret=value; _xsrf=csrf",
        timeout=7.5,
        transport=httpx.MockTransport(handler),
    )
    try:
        response = client.request("GET", "https://www.zhihu.com/api/v4/me")
    finally:
        client.close()

    assert response.json() == {"id": "user-1"}
    assert seen["cookie"] == "z_c0=secret=value; _xsrf=csrf"
    assert seen["xsrf"] == "csrf"
    assert "Mozilla/5.0" in seen["user_agent"]
    assert seen["timeout"] == {
        "connect": 7.5,
        "read": 7.5,
        "write": 7.5,
        "pool": 7.5,
    }


def test_client_me_returns_profile_dict():
    client = ZhihuClient(
        "z_c0=synthetic",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"id": "user-1"})
        ),
    )
    try:
        assert client.me() == {"id": "user-1"}
    finally:
        client.close()


def test_http_status_error_redacts_cookie_headers_and_auth_payload():
    cookie = "z_c0=secret=value; _xsrf=csrf"

    def handler(request):
        return httpx.Response(
            403,
            json={"message": "rejected", "debug": cookie},
            request=request,
        )

    client = ZhihuClient(cookie, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ZhihuAPIError) as error:
            client.me()
    finally:
        client.close()

    message = str(error.value)
    assert "403" in message
    assert cookie not in message
    assert "secret=value" not in message
    assert "rejected" not in message
    assert "cookie" not in message.lower()


def test_transport_failure_is_redacted():
    cookie = "z_c0=synthetic-secret"

    def handler(request):
        raise httpx.ConnectError(f"transport failed for {cookie}", request=request)

    client = ZhihuClient(cookie, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ZhihuAPIError) as error:
            client.me()
    finally:
        client.close()

    assert cookie not in str(error.value)
    assert "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("cookie", ["", "  ", "z_c0", "=secret", "z_c0=x; broken"])
def test_client_rejects_malformed_cookie_without_echoing_input(cookie):
    with pytest.raises(ValueError) as error:
        ZhihuClient(cookie, transport=httpx.MockTransport(lambda request: None))

    if cookie.strip():
        assert cookie.strip() not in str(error.value)


def test_request_forwards_method_params_json_and_redirect_option():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = request.read()
        return httpx.Response(200, json={"ok": True}, request=request)

    client = ZhihuClient("z_c0=synthetic", transport=httpx.MockTransport(handler))
    try:
        response = client.request(
            "POST",
            "https://www.zhihu.com/api/v4/items",
            params={"page": 2},
            json={"name": "value"},
            follow_redirects=False,
        )
    finally:
        client.close()

    assert response.json() == {"ok": True}
    assert seen["method"] == "POST"
    assert seen["url"] == "https://www.zhihu.com/api/v4/items?page=2"
    assert seen["body"] == b'{"name":"value"}'


def test_follow_redirects_never_sends_credentials_to_unapproved_host():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://example.org/collect"},
            request=request,
        )

    client = ZhihuClient(
        "z_c0=synthetic-secret", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ZhihuAPIError) as error:
            client.request(
                "GET", "https://www.zhihu.com/answer/42", follow_redirects=True
            )
    finally:
        client.close()

    assert seen == ["https://www.zhihu.com/answer/42"]
    assert "synthetic-secret" not in str(error.value)


def test_client_refuses_direct_request_to_unapproved_host():
    calls = []
    client = ZhihuClient(
        "z_c0=synthetic-secret",
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    )
    try:
        with pytest.raises(ZhihuAPIError):
            client.request("GET", "https://example.org/collect")
    finally:
        client.close()

    assert calls == []


def test_client_rejects_custom_port_before_dispatch():
    calls = []
    client = ZhihuClient(
        "z_c0=synthetic-secret",
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    )
    try:
        with pytest.raises(ZhihuAPIError) as error:
            client.request("GET", "https://www.zhihu.com:444/api/v4/me")
    finally:
        client.close()

    assert calls == []
    assert "444" not in str(error.value)
    assert "synthetic-secret" not in str(error.value)


def test_malformed_port_raises_sanitized_api_error_before_dispatch():
    calls = []
    client = ZhihuClient(
        "z_c0=synthetic-secret",
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    )
    try:
        with pytest.raises(ZhihuAPIError) as error:
            client.request("GET", "https://www.zhihu.com:not-a-port/api/v4/me")
    finally:
        client.close()

    assert calls == []
    assert "not-a-port" not in str(error.value)
    assert "synthetic-secret" not in str(error.value)


def test_client_accepts_explicit_https_default_port():
    calls = []
    client = ZhihuClient(
        "z_c0=synthetic",
        transport=httpx.MockTransport(lambda request: calls.append(str(request.url)) or httpx.Response(200)),
    )
    try:
        response = client.request("GET", "https://www.zhihu.com:443/api/v4/me")
    finally:
        client.close()

    assert response.status_code == 200
    assert calls == ["https://www.zhihu.com/api/v4/me"]


def test_redirect_to_custom_port_is_rejected_before_second_request():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://www.zhihu.com:444/api/v4/me"},
            request=request,
        )

    client = ZhihuClient("z_c0=synthetic", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ZhihuAPIError) as error:
            client.request(
                "GET", "https://www.zhihu.com/answer/42", follow_redirects=True
            )
    finally:
        client.close()

    assert calls == ["https://www.zhihu.com/answer/42"]
    assert "444" not in str(error.value)


def test_write_request_cannot_follow_redirects_or_be_replayed():
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(
            307,
            headers={"location": "https://www.zhihu.com/api/v4/items/1"},
            request=request,
        )

    client = ZhihuClient(
        "z_c0=synthetic", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ZhihuAPIError) as error:
            client.request(
                "POST",
                "https://www.zhihu.com/api/v4/items",
                json={"title": "synthetic"},
            )
    finally:
        client.close()

    assert calls == ["POST"]
    assert "307" in str(error.value)


def test_write_request_rejects_redirect_following_before_sending():
    calls = []
    client = ZhihuClient(
        "z_c0=synthetic",
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    )
    try:
        with pytest.raises(ZhihuAPIError, match="only allowed for GET and HEAD"):
            client.request(
                "PUT",
                "https://www.zhihu.com/api/v4/items/1",
                json={"title": "synthetic"},
                follow_redirects=True,
            )
    finally:
        client.close()

    assert calls == []
