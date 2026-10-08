from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from .auth import parse_cookie_header


ME_URL = "https://www.zhihu.com/api/v4/me"
_ALLOWED_HOSTS = {"www.zhihu.com", "zhuanlan.zhihu.com", "api.zhihu.com"}
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class ZhihuAPIError(RuntimeError):
    """A sanitized transport or API failure."""


class ZhihuClient:
    def __init__(
        self,
        cookie: str,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ):
        cookies = parse_cookie_header(cookie)
        headers = {
            "accept": "application/json",
            "cookie": "; ".join(f"{name}={value}" for name, value in cookies.items()),
            "user-agent": _USER_AGENT,
        }
        if "_xsrf" in cookies:
            headers["x-xsrftoken"] = cookies["_xsrf"]
        self._client = httpx.Client(
            headers=headers,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        content: Any = None,
        follow_redirects: bool = False,
    ) -> httpx.Response:
        current_method = method.upper()
        if follow_redirects and current_method not in {"GET", "HEAD"}:
            raise ZhihuAPIError("Redirect following is only allowed for GET and HEAD")
        current_url = str(url)
        current_params = params
        current_json = json
        current_content = content

        for redirect_count in range(21):
            self._validate_target(current_url)
            try:
                response = self._client.request(
                    current_method,
                    current_url,
                    params=current_params,
                    json=current_json,
                    content=current_content,
                    follow_redirects=False,
                )
            except httpx.RequestError:
                raise ZhihuAPIError(
                    f"Zhihu API transport failed for {current_method}"
                ) from None

            if not follow_redirects or not response.is_redirect:
                break
            if redirect_count == 20:
                response.close()
                raise ZhihuAPIError("Zhihu API exceeded the redirect limit")

            location = response.headers.get("location")
            if not location:
                response.close()
                raise ZhihuAPIError("Zhihu API returned a redirect without a location")
            try:
                next_url = str(response.url.join(location))
            except (ValueError, httpx.InvalidURL):
                response.close()
                raise ZhihuAPIError("Zhihu API returned an invalid redirect location") from None
            try:
                self._validate_target(next_url)
            except ZhihuAPIError:
                response.close()
                raise

            if response.status_code == 303 and current_method != "HEAD":
                current_method = "GET"
                current_json = None
                current_content = None
            elif response.status_code in (301, 302) and current_method == "POST":
                current_method = "GET"
                current_json = None
                current_content = None
            response.close()
            current_url = next_url
            current_params = None
        else:
            raise ZhihuAPIError("Zhihu API exceeded the redirect limit")

        if not 200 <= response.status_code < 300:
            raise ZhihuAPIError(
                f"Zhihu API returned HTTP {response.status_code} for {current_method}"
            )
        return response

    def me(self) -> dict:
        response = self.request("GET", ME_URL)
        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError):
            raise ZhihuAPIError("Zhihu profile response was not valid JSON") from None
        if not isinstance(payload, dict):
            raise ZhihuAPIError("Zhihu profile response was not a JSON object")
        return payload

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _validate_target(url: str) -> None:
        try:
            parsed = urlsplit(url)
            host = parsed.hostname
            port = parsed.port
        except ValueError:
            raise ZhihuAPIError(
                "Authenticated requests require an approved HTTPS Zhihu host"
            ) from None
        if (
            parsed.scheme != "https"
            or host not in _ALLOWED_HOSTS
            or port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ZhihuAPIError("Authenticated requests require an approved HTTPS Zhihu host")
