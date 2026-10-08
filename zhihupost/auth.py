import os
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING

from .config import CookieError, CookieStore

if TYPE_CHECKING:
    from .client import ZhihuClient


_COOKIE_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def parse_cookie_header(raw: str) -> dict[str, str]:
    if not isinstance(raw, str):
        raise ValueError("Cookie header is empty or malformed")

    value = raw.strip()
    if value[:7].lower() == "cookie:":
        value = value[7:].strip()
    if not value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError("Cookie header is empty or malformed")

    parts = value.split(";")
    if parts[-1].strip() == "":
        parts.pop()
    cookies: dict[str, str] = {}
    for part in parts:
        pair = part.strip()
        if not pair or "=" not in pair:
            raise ValueError("Cookie header is empty or malformed")
        name, cookie_value = pair.split("=", 1)
        name = name.strip()
        cookie_value = cookie_value.strip()
        if not name or not _COOKIE_NAME.fullmatch(name) or not cookie_value:
            raise ValueError("Cookie header is empty or malformed")
        if name in cookies:
            raise ValueError("Cookie header is empty or malformed")
        cookies[name] = cookie_value
    if not cookies:
        raise ValueError("Cookie header is empty or malformed")
    return cookies


def resolve_cookie(
    store: CookieStore, environ: Mapping[str, str] | None = None
) -> str:
    environment = os.environ if environ is None else environ
    if "ZHIHU_COOKIE" in environment:
        cookie = environment["ZHIHU_COOKIE"]
        try:
            parse_cookie_header(cookie)
        except (TypeError, ValueError):
            raise CookieError("ZHIHU_COOKIE is empty or malformed") from None
        return cookie

    cookie = store.load()
    if cookie is None:
        raise CookieError("No Zhihu cookie is configured; use login or set ZHIHU_COOKIE")
    try:
        parse_cookie_header(cookie)
    except (TypeError, ValueError):
        raise CookieError("The saved Zhihu cookie is empty or malformed") from None
    return cookie


def validate_cookie(client: "ZhihuClient") -> dict:
    return client.me()
