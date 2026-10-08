import os
import stat

import httpx
import pytest

from zhihupost.auth import parse_cookie_header, resolve_cookie, validate_cookie
from zhihupost.client import ZhihuClient
from zhihupost.config import CookieError, CookieStore


def test_cookie_parser_strips_optional_prefix_and_splits_once():
    assert parse_cookie_header("Cookie: z_c0=a=b; _xsrf=token") == {
        "z_c0": "a=b",
        "_xsrf": "token",
    }
    assert parse_cookie_header(" _xsrf = csrf ; z_c0 =abc== ") == {
        "_xsrf": "csrf",
        "z_c0": "abc==",
    }


@pytest.mark.parametrize("raw", ["", "  ", "z_c0", "=secret", "z_c0=x; broken"])
def test_cookie_parser_rejects_malformed_input_without_echoing_it(raw):
    with pytest.raises(ValueError) as error:
        parse_cookie_header(raw)

    if raw.strip():
        assert raw.strip() not in str(error.value)


def test_cookie_store_saves_atomically_with_restrictive_permissions(tmp_path, monkeypatch):
    target = tmp_path / "config" / "cookie"
    store = CookieStore(target)
    original_replace = os.replace
    observed = {}

    def inspect_replace(source, destination):
        source = os.fspath(source)
        destination = os.fspath(destination)
        observed["source"] = source
        observed["destination"] = destination
        observed["mode"] = stat.S_IMODE(os.stat(source).st_mode)
        original_replace(source, destination)

    monkeypatch.setattr("zhihupost.config.os.replace", inspect_replace)
    store.save("z_c0=synthetic=value; _xsrf=csrf")

    assert store.load() == "z_c0=synthetic=value; _xsrf=csrf"
    assert observed["destination"] == str(target)
    assert os.path.dirname(observed["source"]) == str(target.parent)
    assert observed["source"] != str(target)
    assert not os.path.exists(observed["source"])
    if os.name == "posix":
        assert observed["mode"] == 0o600
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_cookie_store_replace_failure_preserves_old_file_and_cleans_temporary_file(
    tmp_path, monkeypatch
):
    target = tmp_path / "cookie"
    target.write_text("z_c0=old", encoding="utf-8")
    store = CookieStore(target)

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr("zhihupost.config.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        store.save("z_c0=new")

    assert target.read_text(encoding="utf-8") == "z_c0=old"
    assert list(tmp_path.iterdir()) == [target]


def test_cookie_store_default_path_uses_platform_config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("zhihupost.config.user_config_path", lambda *args, **kwargs: tmp_path)
    store = CookieStore()

    assert store.path == tmp_path / "cookie"


def test_cookie_store_remove_deletes_only_configured_file(tmp_path):
    target = tmp_path / "cookie"
    neighboring = tmp_path / "other"
    target.write_text("z_c0=synthetic", encoding="utf-8")
    neighboring.write_text("keep", encoding="utf-8")

    CookieStore(target).remove()

    assert not target.exists()
    assert neighboring.read_text(encoding="utf-8") == "keep"


def test_cookie_store_rejects_empty_or_malformed_cookie(tmp_path):
    store = CookieStore(tmp_path / "cookie")

    for value in ("", "  ", "malformed"):
        with pytest.raises(CookieError):
            store.save(value)
    assert not store.path.exists()


def test_resolve_cookie_prefers_environment_and_falls_back_to_store(tmp_path):
    store = CookieStore(tmp_path / "cookie")
    store.save("z_c0=stored")

    assert resolve_cookie(store, {"ZHIHU_COOKIE": "z_c0=environment"}) == "z_c0=environment"
    assert resolve_cookie(store, {}) == "z_c0=stored"


def test_resolve_cookie_rejects_missing_or_empty_override_without_leaking(tmp_path):
    store = CookieStore(tmp_path / "cookie")

    with pytest.raises(CookieError, match="No Zhihu cookie"):
        resolve_cookie(store, {})
    with pytest.raises(CookieError) as error:
        resolve_cookie(store, {"ZHIHU_COOKIE": "   "})
    assert "   " not in str(error.value)


def test_validate_cookie_uses_only_read_only_me_endpoint():
    calls = []

    def handler(request):
        calls.append((request.method, str(request.url)))
        return httpx.Response(200, json={"id": "user-1", "name": "Synthetic User"})

    client = ZhihuClient("z_c0=synthetic", transport=httpx.MockTransport(handler))
    try:
        assert validate_cookie(client) == {"id": "user-1", "name": "Synthetic User"}
    finally:
        client.close()

    assert calls == [("GET", "https://www.zhihu.com/api/v4/me")]
