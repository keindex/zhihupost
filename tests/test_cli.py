import argparse
from pathlib import Path

import pytest

from zhihupost.cli import build_parser
from zhihupost.publisher import PublishResult


def test_parser_registers_supported_commands():
    parser = build_parser()
    action = next(
        item for item in parser._actions if isinstance(item, argparse._SubParsersAction)
    )
    assert set(action.choices) == {
        "login",
        "whoami",
        "logout",
        "render",
        "publish",
        "publish-dir",
        "upload-image",
    }


def test_publish_flags_parse():
    parsed = build_parser().parse_args(["publish", "draft.md", "--draft", "--dry-run"])
    assert (parsed.file, parsed.draft, parsed.dry_run) == ("draft.md", True, True)


def test_publish_dir_defaults_to_one_minute_delay():
    parsed = build_parser().parse_args(["publish-dir", "articles"])
    assert parsed.delay == 60.0


class FakeStore:
    instances = []

    def __init__(self, path=None):
        self.cookie = None
        self.path = Path(path) if path else None
        self.removed = False
        self.saved = []
        type(self).instances.append(self)

    def load(self):
        return self.cookie

    def save(self, cookie):
        self.saved.append(cookie)
        self.cookie = cookie

    def remove(self):
        self.removed = True
        self.cookie = None


class FakeClient:
    instances = []

    def __init__(self, cookie, *args, **kwargs):
        self.cookie = cookie
        self.closed = False
        self.requests = []
        type(self).instances.append(self)

    def me(self):
        return {"name": "Ada", "url_token": "ada"}

    def close(self):
        self.closed = True


class FakeUploader:
    instances = []

    def __init__(self, client, *args, **kwargs):
        self.client = client
        type(self).instances.append(self)

    def upload(self, source, base_dir):
        return "https://pic4.zhimg.com/80/v2-fake.png"


class FakePublisher:
    instances = []

    def __init__(self, client, uploader):
        self.client = client
        self.uploader = uploader
        self.calls = []
        type(self).instances.append(self)

    def publish_file(self, path, *, draft=False, dry_run=False):
        self.calls.append((Path(path), draft, dry_run))
        return PublishResult("skipped" if dry_run else "published", None, "Title")


def _reset_fakes():
    for fake in (FakeStore, FakeClient, FakeUploader, FakePublisher):
        fake.instances.clear()


def test_render_is_local_and_does_not_construct_authenticated_objects(monkeypatch, tmp_path, capsys):
    _reset_fakes()
    source = tmp_path / "note.md"
    source.write_text("---\ntitle: Local\n---\n# Hello\n", encoding="utf-8")
    monkeypatch.setattr("zhihupost.cli.CookieStore", FakeStore)
    monkeypatch.setattr("zhihupost.cli.resolve_cookie", lambda *_: pytest.fail("render must not resolve a cookie"))
    monkeypatch.setattr("zhihupost.cli.ZhihuClient", FakeClient)
    monkeypatch.setattr("zhihupost.cli.ImageUploader", FakeUploader)

    from zhihupost.cli import main

    assert main(["render", str(source)]) == 0
    assert "<h1>Hello</h1>" in capsys.readouterr().out
    assert FakeClient.instances == []
    assert FakeUploader.instances == []


def test_publish_dry_run_requires_no_cookie_or_network_objects(monkeypatch, tmp_path, capsys):
    _reset_fakes()
    source = tmp_path / "dry.md"
    source.write_text("---\ntitle: Dry\n---\n![x](remote.png)\n", encoding="utf-8")
    monkeypatch.delenv("ZHIHU_COOKIE", raising=False)
    monkeypatch.setattr("zhihupost.cli.CookieStore", FakeStore)
    monkeypatch.setattr("zhihupost.cli.resolve_cookie", lambda *_: pytest.fail("dry-run must not resolve a cookie"))
    monkeypatch.setattr("zhihupost.cli.ZhihuClient", FakeClient)
    monkeypatch.setattr("zhihupost.cli.ImageUploader", FakeUploader)
    monkeypatch.setattr("zhihupost.cli.Publisher", FakePublisher)

    from zhihupost.cli import main

    assert main(["publish", str(source), "--dry-run"]) == 0
    assert "skipped" in capsys.readouterr().out
    assert FakeClient.instances == []
    assert FakeUploader.instances == []
    assert FakePublisher.instances[0].calls == [(source, False, True)]


def test_login_stdin_validates_before_persisting(monkeypatch, capsys):
    _reset_fakes()
    store = FakeStore()
    monkeypatch.setattr("zhihupost.cli.CookieStore", lambda: store)
    monkeypatch.setattr("zhihupost.cli.ZhihuClient", FakeClient)
    monkeypatch.setattr("zhihupost.cli.validate_cookie", lambda client: client.me())
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("z_c0=synthetic\n"))

    from zhihupost.cli import main

    assert main(["login", "--stdin"]) == 0
    assert store.saved == ["z_c0=synthetic"]
    assert FakeClient.instances[0].cookie == "z_c0=synthetic"
    assert FakeClient.instances[0].closed is True
    assert "Ada" in capsys.readouterr().out


def test_login_does_not_save_when_validation_fails(monkeypatch):
    _reset_fakes()
    store = FakeStore()
    monkeypatch.setattr("zhihupost.cli.CookieStore", lambda: store)
    monkeypatch.setattr("zhihupost.cli.ZhihuClient", FakeClient)
    monkeypatch.setattr("zhihupost.cli.validate_cookie", lambda client: (_ for _ in ()).throw(ValueError("denied")))
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("z_c0=synthetic\n"))

    from zhihupost.cli import main

    assert main(["login", "--stdin"]) == 1
    assert store.saved == []
    assert FakeClient.instances[0].closed is True


def test_whoami_prefers_environment_cookie_and_closes_client(monkeypatch, capsys):
    _reset_fakes()
    store = FakeStore()
    store.cookie = "z_c0=stored"
    monkeypatch.setattr("zhihupost.cli.CookieStore", lambda: store)
    monkeypatch.setattr("zhihupost.cli.ZhihuClient", FakeClient)
    monkeypatch.setenv("ZHIHU_COOKIE", "z_c0=environment")

    from zhihupost.cli import main

    assert main(["whoami"]) == 0
    assert FakeClient.instances[0].cookie == "z_c0=environment"
    assert FakeClient.instances[0].closed is True
    output = capsys.readouterr().out
    assert "Ada" in output
    assert "environment" not in output
    assert "stored" not in output


def test_logout_removes_saved_cookie_without_printing_it(monkeypatch, capsys):
    store = FakeStore()
    store.cookie = "z_c0=secret"
    monkeypatch.setattr("zhihupost.cli.CookieStore", lambda: store)

    from zhihupost.cli import main

    assert main(["logout"]) == 0
    assert store.removed is True
    assert "secret" not in capsys.readouterr().out


def test_upload_image_prints_only_returned_url_and_closes_client(monkeypatch, tmp_path, capsys):
    _reset_fakes()
    source = tmp_path / "image.png"
    source.write_bytes(b"image")
    store = FakeStore()
    store.cookie = "z_c0=stored"
    monkeypatch.setattr("zhihupost.cli.CookieStore", lambda: store)
    monkeypatch.setattr("zhihupost.cli.ZhihuClient", FakeClient)
    monkeypatch.setattr("zhihupost.cli.ImageUploader", FakeUploader)

    assert __import__("zhihupost.cli", fromlist=["main"]).main(["upload-image", str(source)]) == 0
    assert capsys.readouterr().out.strip() == "https://pic4.zhimg.com/80/v2-fake.png"
    assert FakeClient.instances[0].closed is True


def test_publish_dir_returns_nonzero_and_prints_summary(monkeypatch, tmp_path, capsys):
    _reset_fakes()
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    store = FakeStore()
    store.cookie = "z_c0=stored"
    monkeypatch.setattr("zhihupost.cli.CookieStore", lambda: store)
    monkeypatch.setattr("zhihupost.cli.ZhihuClient", FakeClient)
    monkeypatch.setattr("zhihupost.cli.ImageUploader", FakeUploader)

    class BatchPublisher(FakePublisher):
        def publish_file(self, path, *, draft=False, dry_run=False):
            raise RuntimeError("failure z_c0=stored")

    monkeypatch.setattr("zhihupost.cli.Publisher", BatchPublisher)
    assert __import__("zhihupost.cli", fromlist=["main"]).main(["publish-dir", str(tmp_path), "--delay", "0"]) == 1
    output = capsys.readouterr()
    assert "failed: 1" in output.out
    assert "z_c0=stored" not in output.out
