# Python CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an installable Python CLI for Zhihu Markdown rendering, authentication, image upload, article/answer publishing, drafts, and recursive batch processing while retaining the VS Code extension.

**Architecture:** Keep the Python implementation in a new `zhihupost` package. Separate front matter and Markdown rendering, credential storage, HTTP/API access, image conversion, publishing decisions, batch sequencing, and argparse commands; inject HTTP, OSS, and sleep dependencies so tests never perform live writes.

**Tech Stack:** Python 3.10+, `markdown-it-py`, `mdit-py-plugins`, `PyYAML`, `httpx`, `oss2`, `platformdirs`, and `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-08-python-cli-design.md`

## Global Constraints

- Use Python's standard `argparse` interface.
- Runtime dependencies are `markdown-it-py` plus `mdit-py-plugins`, `PyYAML`, `httpx`, `oss2`, and `platformdirs`.
- `ZHIHU_COOKIE` overrides the cookie saved by `login` for authenticated commands.
- `login` validates credentials only with read-only `GET /api/v4/me`, stores them in the user config directory, and `logout` deletes that saved credential.
- On POSIX the credential file mode is `0600`; on Windows it remains in the current user's config directory.
- Never print, commit, or place a real cookie in test fixtures.
- HTTP uses explicit timeouts and status handling; never automatically retry write requests.
- `render` and `--dry-run` make no Zhihu or OSS requests; preserve image references in dry-run HTML.
- Resolve relative images against the source Markdown directory, reject SVG, use API-returned temporary OSS credentials, and never copy the extension's hard-coded OSS values.
- A batch continues after an individual file fails and reports succeeded, skipped, and failed counts.
- Automated tests mock all Zhihu HTTP and OSS calls; never submit a live write while verifying.
- Leave the TypeScript extension and its `package.json` unchanged.

---

### Task 1: Add Python Package and CLI Skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `zhihupost/__init__.py`
- Create: `zhihupost/cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- `zhihupost.cli.build_parser() -> argparse.ArgumentParser`
- `zhihupost.cli.main(argv: list[str] | None = None) -> int`
- Console script: `zhihupost = "zhihupost.cli:main"`

- [ ] **Step 1: Add failing command-registration tests**

```python
import argparse

from zhihupost.cli import build_parser


def test_parser_registers_supported_commands():
    parser = build_parser()
    action = next(item for item in parser._actions if isinstance(item, argparse._SubParsersAction))
    assert set(action.choices) == {
        "login", "whoami", "logout", "render", "publish", "publish-dir", "upload-image"
    }


def test_publish_flags_parse():
    parsed = build_parser().parse_args(["publish", "draft.md", "--draft", "--dry-run"])
    assert (parsed.file, parsed.draft, parsed.dry_run) == ("draft.md", True, True)
```

- [ ] **Step 2: Run the test and confirm import/registration failure**

Run: `python -m pytest tests/test_cli.py -q`
Expected: FAIL because the package and CLI do not exist.

- [ ] **Step 3: Add package metadata and minimal parser**

Declare Python `>=3.10`, the six runtime dependencies in the spec, `pytest` and `build` as test extras, setuptools package discovery, and the console entry point. Register the seven commands; `render FILE`, `publish FILE [--draft] [--dry-run]`, `publish-dir DIR [--draft] [--delay SECONDS]`, and `upload-image FILE` take paths. Implement `main()` to parse and return a nonzero “not implemented” status for commands not yet wired.

- [ ] **Step 4: Run the test and verify package metadata**

Run: `python -m pytest tests/test_cli.py -q`
Expected: PASS. Run `python -m pip install -e . --no-deps` and `zhihupost --help`; expected: editable install succeeds and help lists all seven commands.

### Task 2: Parse Front Matter and Classify Publish Targets

**Files:**
- Create: `zhihupost/document.py`
- Create: `tests/test_document.py`

**Interfaces:**
- `Document(metadata: dict[str, object], body: str, source_path: Path | None)` dataclass.
- `PublishTarget(kind: Literal["new_article", "question", "answer", "article"], url: str | None, article_id: str | None = None, question_id: str | None = None, answer_id: str | None = None)` dataclass.
- `parse_document(text: str, source_path: Path | None = None) -> Document`
- `derive_title(body: str) -> str | None`
- `classify_target(url: str | None) -> PublishTarget`
- `set_front_matter_value(text: str, key: str, value: str) -> str`

- [ ] **Step 1: Write parsing, routing, and write-back tests**

Cover BOM and CRLF input, quoted YAML title, missing front matter, absent title with `# Heading`, comma-separated and YAML-list tags, valid `/question/{id}`, `/question/{id}/answer/{id}`, `/answer/{id}`, and `/p/{id}` URLs, and rejection of non-Zhihu hosts or unsupported paths. Verify write-back changes only the selected YAML field and preserves body content and line endings.

```python
import pytest

from zhihupost.document import classify_target, derive_title, parse_document, set_front_matter_value


def test_parse_bom_front_matter_and_normalize_tags():
    document = parse_document('\ufeff---\r\ntitle: "A: title"\r\ntags: one, two\r\n---\r\n# Body\r\n')
    assert document.metadata["title"] == "A: title"
    assert document.metadata["tags"] == ["one", "two"]
    assert document.body == "# Body\r\n"


def test_route_question_and_reject_unrelated_host():
    assert classify_target("https://www.zhihu.com/question/123").question_id == "123"
    with pytest.raises(ValueError):
        classify_target("https://example.org/question/123")


def test_writeback_preserves_crlf_body():
    source = "---\r\ntitle: Old\r\n---\r\nBody\r\n"
    updated = set_front_matter_value(source, "url", "https://zhuanlan.zhihu.com/p/12")
    assert updated.endswith("---\r\nBody\r\n")
    assert "url: https://zhuanlan.zhihu.com/p/12\r\n" in updated
    assert derive_title("---\nignored\n---\n\n## First title\n") == "First title"
```

- [ ] **Step 2: Run `python -m pytest tests/test_document.py -q` and confirm failure**

Expected: FAIL because `zhihupost.document` does not exist.

- [ ] **Step 3: Implement the document model and helpers**

Strip a leading BOM for parsing but retain original text when writing. Require a closed `---` YAML block and a mapping. Parse URL hosts and paths explicitly. Accept tags as either the legacy comma-delimited scalar or a YAML list, normalize both to `list[str]` in the publishing model, and quote inserted string values using `yaml.safe_dump(..., allow_unicode=True).strip()`.

- [ ] **Step 4: Run `python -m pytest tests/test_document.py -q`**

Expected: PASS, including invalid-host and malformed-front-matter errors.

### Task 3: Render Zhihu-Compatible Markdown Locally

**Files:**
- Create: `zhihupost/markdown.py`
- Create: `tests/test_markdown.py`
- Reference: `test/fixtures/publishTest/test.md`
- Reference: `test/fixtures/publishTest/test_assert.html`

**Interfaces:**
- `render_markdown(body: str, image_resolver: Callable[[str], str] | None = None) -> str`
- Image resolver is omitted by `render` and dry-run; when supplied it is called for Markdown image sources and link-card `data-image` sources before HTML output.

- [ ] **Step 1: Add tests for the existing fixture and README syntax**

Assert semantic HTML for heading levels, fenced code with language, block and inline math using Zhihu's `//www.zhihu.com/equation?tex=` image form, task lists, footnote references, and `[![zhihu-link-card:label](image)](url)` with the expected `data-image` attribute. Include a resolver spy that proves both image `src` and card `data-image` are rewritten.

```python
from pathlib import Path

from zhihupost.markdown import render_markdown


def test_existing_fixture_and_zhihu_constructs():
    source = Path("test/fixtures/publishTest/test.md").read_text(encoding="utf-8")
    html = render_markdown(source)
    assert '<pre lang="java">' in html
    assert "www.zhihu.com/equation?tex=" in html
    assert 'data-image="/card.png"' in render_markdown(
        "[![zhihu-link-card:label](/card.png)](https://example.com)"
    )


def test_image_resolver_rewrites_image_and_card_images():
    seen = []
    html = render_markdown(
        "![alt](/body.png)\n\n[![zhihu-link-card:card](/card.png)](https://example.com)",
        image_resolver=lambda src: seen.append(src) or f"https://pic4.zhimg.com/{src.rsplit('/', 1)[-1]}",
    )
    assert seen == ["/body.png", "/card.png"]
    assert html.count("https://pic4.zhimg.com/") == 2
```

- [ ] **Step 2: Run `python -m pytest tests/test_markdown.py -q` and confirm failure**

Expected: FAIL because `zhihupost.markdown` does not exist.

- [ ] **Step 3: Implement the MarkdownIt pipeline and Zhihu rules**

Use `markdown-it-py` with raw HTML enabled and the `mdit-py-plugins` task-list, footnote, and dollar-math plugins. Add a narrowly scoped core/render rule that turns Zhihu link-card syntax into an anchor with `data-image` and caption text, and renders math as Zhihu equation image URLs. Apply the optional resolver to image tokens and link-card image attributes before rendering. Keep render local and deterministic.

- [ ] **Step 4: Compare against the existing snapshot and run syntax tests**

Run: `python -m pytest tests/test_markdown.py -q`
Expected: PASS for each supported construct; compare the existing fixture structurally rather than requiring irrelevant attribute ordering/whitespace equality.

### Task 4: Add Credential Storage and Authenticated HTTP Client

**Files:**
- Create: `zhihupost/config.py`
- Create: `zhihupost/client.py`
- Create: `zhihupost/auth.py`
- Create: `tests/test_config_auth.py`
- Create: `tests/test_client.py`

**Interfaces:**
- `CookieStore(path: Path | None = None)` with `load() -> str | None`, `save(cookie: str) -> None`, and `remove() -> None`.
- `resolve_cookie(store: CookieStore, environ: Mapping[str, str] | None = None) -> str`, environment taking precedence over the stored cookie.
- `ZhihuClient(cookie: str, timeout: float = 20.0, transport: httpx.BaseTransport | None = None)` with `request(method, url, *, params=None, json=None, content=None, follow_redirects=False) -> httpx.Response`, `me() -> dict`, and `close() -> None`.
- `validate_cookie(client: ZhihuClient) -> dict` uses only `GET https://www.zhihu.com/api/v4/me`.
- `parse_cookie_header(raw: str) -> dict[str, str]` strips an optional `Cookie:` prefix and splits each pair only at the first `=`.

- [ ] **Step 1: Write isolated cookie and HTTP tests**

Test environment override, saved-cookie fallback, absent-cookie errors, POSIX mode `0600`, logout deletion, cookie values containing `=`, optional `Cookie:` prefix, `_xsrf` header derivation, request timeout forwarding, non-2xx API errors, and that exception text does not contain the cookie. Use `httpx.MockTransport`; no test may use the network.

```python
import httpx

from zhihupost.auth import parse_cookie_header
from zhihupost.client import ZhihuAPIError, ZhihuClient


def test_cookie_parser_keeps_equals_in_value():
    assert parse_cookie_header("Cookie: z_c0=a=b; _xsrf=token") == {
        "z_c0": "a=b", "_xsrf": "token"
    }


def test_client_sends_xsrf_and_raises_without_leaking_cookie():
    seen = {}

    def handler(request):
        seen.update(cookie=request.headers["cookie"], xsrf=request.headers["x-xsrftoken"])
        return httpx.Response(403, json={"message": "denied"})

    client = ZhihuClient("z_c0=secret=value; _xsrf=csrf", transport=httpx.MockTransport(handler))
    try:
        client.request("GET", "https://www.zhihu.com/api/v4/me")
    except ZhihuAPIError as error:
        assert "secret=value" not in str(error)
    else:
        raise AssertionError("403 response must raise ZhihuAPIError")
    assert seen == {"cookie": "z_c0=secret=value; _xsrf=csrf", "xsrf": "csrf"}
```

- [ ] **Step 2: Run `python -m pytest tests/test_config_auth.py tests/test_client.py -q` and confirm failure**

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement storage, cookie parsing, and the client**

Use `platformdirs.user_config_path("zhihupost", appauthor=False)` for the default location. Create parent directories; write through a restrictive temporary file and `os.replace`; chmod to `0600` on POSIX. Build one `httpx.Client` with the cookie header and `_xsrf` header, a desktop user agent, and the configured timeout. Redact cookies from custom error messages and avoid logging response request headers.

- [ ] **Step 4: Run the two focused test modules**

Run: `python -m pytest tests/test_config_auth.py tests/test_client.py -q`
Expected: PASS, with only mocked GET `/api/v4/me` during auth validation.

### Task 5: Implement Image Resolution and Zhihu Upload

**Files:**
- Create: `zhihupost/images.py`
- Create: `tests/test_images.py`

**Interfaces:**
- `ImageUploader(client: ZhihuClient, oss_put: Callable[[dict, str, bytes], None] | None = None, remote_transport: httpx.BaseTransport | None = None)`.
- `resolve_source(source: str, base_dir: Path) -> tuple[bytes, str]` resolves URL-encoded local paths and HTTP(S) sources, returning bytes and suffix; reject `.svg` and unsupported schemes.
- `upload(source: str, base_dir: Path) -> str` returns `https://pic4.zhimg.com/80/v2-{md5}{suffix}` after successful upload, or the content-hash URL when the preflight response has no `upload_token`.
- Never send the authenticated `ZhihuClient` cookie to external image URLs; use a separate unauthenticated HTTP request for remote image bytes.

- [ ] **Step 1: Write image tests with mocked download, Zhihu preflight, and OSS**

Cover local relative paths including percent-encoded names, remote fetch without a Cookie header, SVG and unsupported-scheme rejection, preflight POST body `{image_hash, source: "answer"}`, missing upload token fallback, temporary token fields passed to OSS, awaiting/surfacing OSS failure, extension preservation, and content-hash URL generation. Monkeypatch the OSS SDK constructor in a focused test to assert the fixed public target `zhihu-pics-upload.zhimg.com` / `zhihu-pics` in the `oss-cn-hangzhou` region with CNAME enabled; those values are not credentials.

```python
import httpx
import pytest

from zhihupost.images import ImageUploader


def test_remote_image_download_has_no_zhihu_cookie(tmp_path):
    observed = []

    def remote(request):
        observed.append(request.headers.get("cookie"))
        return httpx.Response(200, content=b"image-bytes")

    # Inject a separate remote transport and fake preflight/OSS adapters.
    uploader = make_uploader(remote_transport=httpx.MockTransport(remote))
    uploader.upload("https://cdn.example/image.png", tmp_path)
    assert observed == [None]


def test_svg_is_rejected_before_any_request(tmp_path):
    uploader = make_uploader()
    with pytest.raises(ValueError, match="SVG"):
        uploader.upload("diagram.svg", tmp_path)
```

Define `make_uploader()` in this test module. It creates `ZhihuClient("z_c0=fake", transport=httpx.MockTransport(preflight))`, passes the `remote_transport` to `ImageUploader`, and supplies an `oss_put=lambda token, key, data: None` callback. The preflight handler returns a fake success JSON payload. The helper uses a synthetic cookie and never reads credentials from the environment.

- [ ] **Step 2: Run `python -m pytest tests/test_images.py -q` and confirm failure**

Expected: FAIL because `zhihupost.images` does not exist.

- [ ] **Step 3: Implement image loading and preflight/OSS flow**

POST to `https://api.zhihu.com/images` with the MD5 and `source=answer`. The response supplies temporary `access_id`, `access_key`, `access_token`, and `object_key`; it does not supply the OSS target. When `upload_token` exists, construct `oss2.StsAuth` only from those API-returned temporary credentials and upload `object_key` to the fixed public target (`zhihu-pics-upload.zhimg.com`, bucket `zhihu-pics`, region `oss-cn-hangzhou`, CNAME enabled) with `put_object`. Never copy the access key, secret, or STS token from `src/const/HTTP.ts`. Wait for the call to finish before returning. If the preflight omits an upload token, return the documented content-hash image URL. Fail before article submission on download, preflight, or OSS errors.

- [ ] **Step 4: Run `python -m pytest tests/test_images.py -q`**

Expected: PASS; tests assert there are no live calls and no legacy credentials.

### Task 6: Publish Articles and Answers in Explicit API Order

**Files:**
- Create: `zhihupost/publisher.py`
- Create: `tests/test_publisher.py`

**Interfaces:**
- `PublishResult(status: Literal["published", "draft", "skipped"], url: str | None, title: str | None)` dataclass.
- `Publisher(client: ZhihuClient | None, uploader: ImageUploader | None, renderer=render_markdown)`; `client` and `uploader` may be `None` only for dry-run. The renderer accepts `(body, image_resolver=None)` and the publisher supplies a resolver bound to the source file's parent directory.
- `publish_document(document: Document, *, draft: bool = False, dry_run: bool = False) -> PublishResult`.
- `publish_file(path: Path, *, draft: bool = False, dry_run: bool = False) -> PublishResult`.

- [ ] **Step 1: Add route and request-order tests**

Mock API operations and assert new article order: `POST /api/articles/drafts`, `PATCH /api/articles/{id}/draft`, synchronize topics serially, then `PUT /api/articles/{id}/publish` unless draft. Assert question URL creates an answer; answer URL updates an answer; article URL patches and republishes existing article; `/answer/{id}` performs the read-only answer lookup to discover its question. Assert columns are listed or created only for article routes during a real run, tags accept both normalized input forms, and dry-run invokes neither client nor uploader.

```python
from zhihupost.document import parse_document
from zhihupost.publisher import Publisher


def test_new_article_waits_for_tags_before_publish(tmp_path):
    client = RecordingClient([
        {"id": "42"}, {}, {"topics": []},
        [{"id": "tag-1", "name": "tag"}], {}, {},
    ])
    document = parse_document(
        "---\ntitle: Title\ntags: tag\n---\nBody\n", tmp_path / "article.md"
    )
    publisher = Publisher(client, FakeUploader())
    result = publisher.publish_document(document)
    assert client.calls == [
        ("POST", "https://zhuanlan.zhihu.com/api/articles/drafts"),
        ("PATCH", "https://zhuanlan.zhihu.com/api/articles/42/draft"),
        ("GET", "https://zhuanlan.zhihu.com/api/articles/42/draft"),
        ("GET", "https://zhuanlan.zhihu.com/api/autocomplete/topics?token=tag&max_matches=2&use_similar=0&topic_filter=1"),
        ("POST", "https://zhuanlan.zhihu.com/api/articles/42/topics"),
        ("PUT", "https://zhuanlan.zhihu.com/api/articles/42/publish"),
    ]
    assert result.url == "https://zhuanlan.zhihu.com/p/42"


def test_dry_run_does_not_call_client_or_uploader(tmp_path):
    client = RecordingClient([])
    uploader = FakeUploader()
    document = parse_document("---\ntitle: Title\n---\n![x](remote.png)\n", tmp_path / "a.md")
    Publisher(client, uploader).publish_document(document, dry_run=True)
    assert client.calls == []
    assert uploader.calls == []
```

Define `RecordingClient` and `FakeUploader` in `tests/test_publisher.py`. `RecordingClient.request(method, url, **kwargs)` stores `(method, url)` and wraps the next queued JSON payload in `httpx.Response(200, json=payload, request=httpx.Request(method, url))`; for `/answer/{id}` it returns a response with the final redirected URL. This matches the production `ZhihuClient.request() -> httpx.Response` interface. `FakeUploader.upload(source, base_dir)` records `(source, base_dir)` and returns a fixed Zhihu URL. The response queue in the test covers draft creation, patch, current topics, exact autocomplete result, topic creation, and publish. Add companion route tests with response queues for new question answers, existing answer updates, existing article updates, and `/answer/{id}` redirect lookup. Add a title-image test that asserts it passes through `FakeUploader` before the article draft request.

- [ ] **Step 2: Add metadata behavior tests**

Verify title fallback skips front matter and blank lines, successful article create/draft writes `/p/{id}` to the source file, successful new answer writes `/answer/{id}` when the API response supplies its ID, and existing answer/article URLs remain unchanged. If a draft-answer response has no answer ID, return success with the question draft URL and do not invent an answer URL. Verify failed API calls do not write metadata and body/BOM/line endings remain intact. Cover exact write payloads and partial-success failures for tags and publishing.

- [ ] **Step 3: Run `python -m pytest tests/test_publisher.py -q` and confirm failure**

Expected: FAIL because `zhihupost.publisher` does not exist.

- [ ] **Step 4: Implement content preparation and route handlers**

Render after resolving body images and upload a nonempty `title-image` through the same `ImageUploader`; derive title from body only when metadata is empty. Read successful JSON responses with `.json()` and inspect `status_code`. Create articles with `POST https://zhuanlan.zhihu.com/api/articles/drafts` and `{title: "h", delta_time: 0}`, then patch `/api/articles/{id}/draft` with `{content, title, titleImage, isTitleImageFullScreen: false}` before syncing topics. Publish with `PUT /api/articles/{id}/publish` and `{column: <column object or null>, commentPermission: "anyone"}`. Resolve columns from `GET https://www.zhihu.com/api/v4/members/{url_token}/column-contributions?include=data%5B*%5D.column.intro%2Cfollowers%2Carticles_count&offset=0&limit=20`, reading `data[].column`; create a missing named column with `POST https://www.zhihu.com/api/v4/columns/request` and `{title, intro: "", intro_type: "rich"}` only during real article publish. For articles, await tag removal/addition before publish. Read current topics from the article draft's `topics`; delete unwanted topics with `DELETE /api/articles/{id}/topics/{topic_id}`. For missing tags, GET `/api/autocomplete/topics?token={encodeURI(tag)}&max_matches=2&use_similar=0&topic_filter=1`, require the first result's name to match case-insensitively, and POST the entire matching topic object to `/api/articles/{id}/topics`. New answers use `POST https://www.zhihu.com/api/v4/questions/{question_id}/answers` or `/draft` with `{content, reshipment_settings: "allowed", comment_permission: "all", reward_setting: {can_reward: false}}`; existing answers use `PUT https://www.zhihu.com/api/v4/answers/{answer_id}` or the question draft endpoint with content and reward settings. Resolve `/answer/{id}` with a read-only GET, redirects enabled, and final response URL; fail if it does not identify the question. Do not retry any write. Surface a partial-success error if content was written but subsequent tag/publish/write-back work fails.

- [ ] **Step 5: Run `python -m pytest tests/test_publisher.py -q`**

Expected: PASS, including the order assertion and partial failure/no-write-back behavior.

### Task 7: Add Recursive Batch Processing and Complete CLI Commands

**Files:**
- Create: `zhihupost/batch.py`
- Modify: `zhihupost/cli.py`
- Create: `tests/test_batch.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- `BatchSummary(succeeded: int, skipped: int, failed: int, failures: list[tuple[Path, str]])` dataclass.
- `publish_directory(root: Path, publisher: Publisher, *, draft: bool = False, delay: float = 60.0, sleep: Callable[[float], None] = time.sleep) -> BatchSummary`.
- Commands: `login [--stdin]`, `whoami`, `logout`, `render FILE`, `publish FILE [--draft] [--dry-run]`, `publish-dir DIR [--draft] [--delay SECONDS]`, and `upload-image FILE`.

- [ ] **Step 1: Write batch traversal and result tests**

Create a temporary tree with uppercase/lowercase `.md` extensions and nested directories. Inject a publisher and sleeper; assert case-insensitive sorted traversal, sequential calls, delay only between files, default delay `60.0`, continuation after exceptions, and separate succeeded/skipped/failed counts.

```python
from zhihupost.batch import publish_directory
from zhihupost.publisher import PublishResult


class StubPublisher:
    def __init__(self):
        self.paths = []

    def publish_file(self, path, *, draft=False):
        self.paths.append(path)
        if path.name == "b.MD":
            raise RuntimeError("mocked failure")
        return PublishResult("published", "https://zhuanlan.zhihu.com/p/1", "A")


def test_batch_sorts_waits_between_files_and_continues(tmp_path):
    (tmp_path / "b.MD").write_text("b", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "a.md").write_text("a", encoding="utf-8")
    sleeps = []
    publisher = StubPublisher()
    summary = publish_directory(tmp_path, publisher, delay=3, sleep=sleeps.append)
    assert [path.name for path in publisher.paths] == ["b.MD", "a.md"]
    assert sleeps == [3]
    assert (summary.succeeded, summary.skipped, summary.failed) == (1, 0, 1)
```

- [ ] **Step 2: Run `python -m pytest tests/test_batch.py -q` and confirm failure**

Expected: FAIL because `zhihupost.batch` does not exist.

- [ ] **Step 3: Implement batch processing**

Collect recursive Markdown paths, sort by normalized relative path, call `publish_file` one at a time, sleep only between adjacent files, and capture per-file errors into `BatchSummary` without aborting the run.

- [ ] **Step 4: Write CLI dispatch and exit-code tests**

Patch constructors to inject fake store/client/uploader/publisher. Verify `render` writes HTML to stdout with no network object created; `publish --dry-run` works without a configured cookie, writes a dry-run result, and creates neither the authenticated client nor uploader; `login --stdin` reads stdin and saves only after mocked `me()` validation; `whoami` honors `ZHIHU_COOKIE`; `logout` removes the saved cookie; `upload-image` prints only the resulting image URL; batch returns nonzero if any file failed and prints the summary without cookie values.

- [ ] **Step 5: Wire command handlers and run focused tests**

Keep credentials out of argparse values/history: `login` reads stdin only with `--stdin`, otherwise use `getpass.getpass`. Resolve cookies through environment then store for authenticated commands. Return `0` on complete success, `1` on API/validation/batch failure, and let argparse use `2` for invalid invocation. Run `python -m pytest tests/test_cli.py tests/test_batch.py -q`; expected: PASS.

### Task 8: Document Installation and Run Full Verification

**Files:**
- Modify: `README.md`
- Review: `pyproject.toml`, `zhihupost/`, `tests/`

- [ ] **Step 1: Document Python CLI usage**

Add a Python CLI section in Chinese, matching the existing README, with editable install, `zhihupost login`, environment-cookie usage, `whoami/logout`, local render, dry-run, publish/draft, recursive batch and delay examples, upload-image, front matter fields, YAML-list or comma-separated tags, and supported Markdown constructs. State that `render` and dry-run do no network access. Do not reproduce the supplied cookie.

- [ ] **Step 2: Run all Python tests and packaging checks**

Run: `python -m pytest -q`
Expected: PASS with all HTTP and OSS operations mocked. Run `python -m pip check`; expected: no dependency conflicts. Run `python -m build`; expected: source and wheel build successfully.

- [ ] **Step 3: Exercise CLI help and local-only rendering**

Run: `zhihupost --help`, `zhihupost render test/fixtures/publishTest/test.md`, and `zhihupost publish test/fixtures/publishTest/test.md --dry-run` with no cookie configured.
Expected: help lists all commands; render emits HTML; dry-run emits a prepared article result without network access or modifying the fixture.

- [ ] **Step 4: Check diff and test isolation**

Run: `git diff --check; git status --short`
Expected: no whitespace errors, no cookie files or live generated artifacts, and TypeScript files unchanged.

## Self-Review Coverage

- Authentication, environment override, whoami, logout, POSIX permissions, and secret redaction: Tasks 4 and 7.
- Front matter fields, routes, title fallback, and URL write-back: Tasks 2 and 6.
- README Markdown features, Zhihu equations, cards, references, tasks, and image rewriting: Task 3.
- Article/answer create/update and drafts, tags, columns, URL write-back, explicit API order, and dry-run purity: Task 6.
- Recursive sequential batch processing, adjustable delay, partial failures, and final summary: Task 7.
- Local/remote images, relative resolution, URL-decoding, SVG rejection, temporary credentials, and OSS completion: Task 5.
- Installable CLI, docs, tests, packaging, and local-only verification: Tasks 1, 7, and 8.
