from pathlib import Path

import httpx
import pytest

from zhihupost.document import parse_document
from zhihupost.publisher import PartialPublishError, PublishError, Publisher, PublishResult


class RecordingClient:
    def __init__(self, payloads=()):
        self.payloads = list(payloads)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.payloads:
            raise AssertionError(f"Unexpected request: {method} {url}")
        item = self.payloads.pop(0)
        if isinstance(item, httpx.Response):
            return item
        status, payload = item if isinstance(item, tuple) else (200, item)
        request = httpx.Request(method, url)
        if isinstance(payload, str):
            return httpx.Response(status, text=payload, request=request)
        return httpx.Response(status, json=payload, request=request)


class FakeUploader:
    def __init__(self):
        self.calls = []

    def upload(self, source, base_dir):
        self.calls.append((source, Path(base_dir)))
        return f"https://pic.example/{Path(source).name}"


def document(tmp_path, *, metadata="title: Title\n", body="Body\n", url=None):
    if url is not None:
        metadata += f'url: "{url}"\n'
    source = tmp_path / "article.md"
    source.write_text(f"---\n{metadata}---\n{body}", encoding="utf-8", newline="")
    return parse_document(read_raw(source), source)


def read_raw(path):
    with path.open("r", encoding="utf-8", newline="") as source_file:
        return source_file.read()


def calls_without_kwargs(client):
    return [(method, url) for method, url, _ in client.calls]


def test_new_article_waits_for_serial_topic_sync_before_publish_and_writes_url(tmp_path):
    source = tmp_path / "article.md"
    source.write_text("---\ntitle: Title\ntags: tag\n---\nBody\n", encoding="utf-8")
    parsed = parse_document(source.read_text(encoding="utf-8"), source)
    client = RecordingClient([
        {"id": "42"},
        {},
        {"topics": []},
        [{"id": "tag-1", "name": "tag", "url": "/tag"}],
        {},
        {},
    ])

    result = Publisher(client, FakeUploader()).publish_document(parsed)

    assert calls_without_kwargs(client) == [
        ("POST", "https://zhuanlan.zhihu.com/api/articles/drafts"),
        ("PATCH", "https://zhuanlan.zhihu.com/api/articles/42/draft"),
        ("GET", "https://zhuanlan.zhihu.com/api/articles/42/draft"),
        ("GET", "https://zhuanlan.zhihu.com/api/autocomplete/topics?token=tag&max_matches=2&use_similar=0&topic_filter=1"),
        ("POST", "https://zhuanlan.zhihu.com/api/articles/42/topics"),
        ("PUT", "https://zhuanlan.zhihu.com/api/articles/42/publish"),
    ]
    assert client.calls[0][2]["json"] == {"title": "h", "delta_time": 0}
    assert client.calls[1][2]["json"] == {
        "content": "<p>Body</p>\n",
        "title": "Title",
        "titleImage": None,
        "isTitleImageFullScreen": False,
    }
    assert client.calls[4][2]["json"] == {"id": "tag-1", "name": "tag", "url": "/tag"}
    assert client.calls[5][2]["json"] == {"column": None, "commentPermission": "anyone"}
    assert result == PublishResult("published", "https://zhuanlan.zhihu.com/p/42", "Title")
    assert 'url: "https://zhuanlan.zhihu.com/p/42"' in source.read_text(encoding="utf-8")


def test_new_article_draft_syncs_tags_then_writes_metadata_without_publish(tmp_path):
    source = tmp_path / "draft.md"
    source.write_text("---\ntitle: Draft\n---\nText\n", encoding="utf-8")
    parsed = parse_document(source.read_text(encoding="utf-8"), source)
    client = RecordingClient([{"id": "8"}, {}, {"topics": []}])

    result = Publisher(client, FakeUploader()).publish_document(parsed, draft=True)

    assert calls_without_kwargs(client) == [
        ("POST", "https://zhuanlan.zhihu.com/api/articles/drafts"),
        ("PATCH", "https://zhuanlan.zhihu.com/api/articles/8/draft"),
        ("GET", "https://zhuanlan.zhihu.com/api/articles/8/draft"),
    ]
    assert result == PublishResult("draft", "https://zhuanlan.zhihu.com/p/8", "Draft")
    assert 'url: "https://zhuanlan.zhihu.com/p/8"' in source.read_text(encoding="utf-8")


def test_existing_article_patches_and_syncs_tags_before_publish_without_url_writeback(tmp_path):
    original = "https://zhuanlan.zhihu.com/p/9"
    source = tmp_path / "existing.md"
    source.write_text(
        f'---\ntitle: Edited\nurl: "{original}"\ncolumn: Column\ntags:\n  - Keep\n---\nBody\n',
        encoding="utf-8",
    )
    parsed = parse_document(source.read_text(encoding="utf-8"), source)
    client = RecordingClient([
        {},
        {"topics": [{"id": "drop", "name": "Drop"}, {"id": "keep", "name": "KEEP"}]},
        {},
        {"url_token": "author"},
        {"data": [{"column": {"id": "c1", "title": "Column"}}]},
        {},
    ])

    result = Publisher(client, FakeUploader()).publish_document(parsed)

    assert calls_without_kwargs(client) == [
        ("PATCH", "https://zhuanlan.zhihu.com/api/articles/9/draft"),
        ("GET", "https://zhuanlan.zhihu.com/api/articles/9/draft"),
        ("DELETE", "https://zhuanlan.zhihu.com/api/articles/9/topics/drop"),
        ("GET", "https://www.zhihu.com/api/v4/me"),
        ("GET", "https://www.zhihu.com/api/v4/members/author/column-contributions?include=data%5B*%5D.column.intro%2Cfollowers%2Carticles_count&offset=0&limit=20"),
        ("PUT", "https://zhuanlan.zhihu.com/api/articles/9/publish"),
    ]
    assert client.calls[0][2]["json"]["title"] == "Edited"
    assert "json" not in client.calls[4][2]
    assert client.calls[-1][2]["json"] == {
        "column": {"id": "c1", "title": "Column"},
        "commentPermission": "anyone",
    }
    assert result == PublishResult("published", original, "Edited")
    assert source.read_text(encoding="utf-8").count(original) == 1


def test_missing_column_is_created_with_exact_payload(tmp_path):
    client = RecordingClient([
        {"id": "12"}, {}, {"topics": []},
        {"url_token": "author"}, {"data": []}, {"id": "created", "title": "New"},
        {},
    ])
    result = Publisher(client, FakeUploader()).publish_document(
        document(tmp_path, metadata="title: Title\ncolumn: New\n")
    )

    assert (client.calls[5][0], client.calls[5][1], client.calls[5][2]["json"]) == (
        "POST",
        "https://www.zhihu.com/api/v4/columns/request",
        {"title": "New", "intro": "", "intro_type": "rich"},
    )
    assert result.url.endswith("/12")


def test_draft_and_dry_run_do_not_resolve_or_create_column(tmp_path):
    client = RecordingClient([{"id": "3"}, {}, {"topics": []}])
    Publisher(client, FakeUploader()).publish_document(
        document(tmp_path, metadata="title: Title\ncolumn: New\n"), draft=True
    )
    assert calls_without_kwargs(client) == [
        ("POST", "https://zhuanlan.zhihu.com/api/articles/drafts"),
        ("PATCH", "https://zhuanlan.zhihu.com/api/articles/3/draft"),
        ("GET", "https://zhuanlan.zhihu.com/api/articles/3/draft"),
    ]

    dry = Publisher(None, None).publish_document(
        document(tmp_path, metadata="title: Title\ncolumn: New\n"), dry_run=True
    )
    assert dry.status == "skipped"


def test_title_image_and_body_images_resolve_relative_to_source_before_create(tmp_path):
    source = tmp_path / "nested" / "article.md"
    source.parent.mkdir()
    source.write_text(
        "---\ntitle: Images\ntitle-image: cover.jpg\n---\n![body](images/body.png)\n",
        encoding="utf-8",
    )
    parsed = parse_document(source.read_text(encoding="utf-8"), source)
    client = RecordingClient([{"id": "1"}, {}, {"topics": []}, {}])
    uploader = FakeUploader()

    Publisher(client, uploader).publish_document(parsed)

    assert uploader.calls == [
        ("images/body.png", source.parent),
        ("cover.jpg", source.parent),
    ]
    assert "https://pic.example/body.png" in client.calls[1][2]["json"]["content"]
    assert client.calls[1][2]["json"]["titleImage"] == "https://pic.example/cover.jpg"


def test_dry_run_renders_locally_and_preserves_images_without_dependencies(tmp_path):
    parsed = document(tmp_path, body="![remote](https://cdn.test/a.png)\n")
    seen = []

    def renderer(body, image_resolver=None):
        seen.append(image_resolver)
        return f"rendered:{body}"

    result = Publisher(None, None, renderer=renderer).publish_document(parsed, dry_run=True)

    assert result == PublishResult("skipped", None, "Title")
    assert seen == [None]


def test_publish_file_dry_run_parses_front_matter_and_keeps_source_unchanged(tmp_path):
    source = tmp_path / "dry.md"
    original = "\ufeff---\r\ntitle: Dry\r\n---\r\n![x](local.png)\r\n"
    source.write_text(original, encoding="utf-8", newline="")
    result = Publisher(None, None).publish_file(source, dry_run=True)
    assert result == PublishResult("skipped", None, "Dry")
    assert read_raw(source) == original


def test_title_falls_back_to_first_nonblank_body_heading(tmp_path):
    client = RecordingClient([{"id": "2"}, {}, {"topics": []}, {}])
    result = Publisher(client, FakeUploader()).publish_document(
        document(tmp_path, metadata="title: \n", body="\n\n## Derived title\nBody\n")
    )
    assert result.title == "Derived title"
    assert client.calls[1][2]["json"]["title"] == "Derived title"


def test_new_question_answer_uses_default_payload_and_writes_answer_url(tmp_path):
    source = tmp_path / "answer.md"
    source.write_text(
        '---\ntitle: Answer\nurl: "https://www.zhihu.com/question/123"\n---\nText\n',
        encoding="utf-8",
    )
    parsed = parse_document(source.read_text(encoding="utf-8"), source)
    client = RecordingClient([{"id": "456"}])

    result = Publisher(client, FakeUploader()).publish_document(parsed)

    assert calls_without_kwargs(client) == [
        ("POST", "https://www.zhihu.com/api/v4/questions/123/answers")
    ]
    assert client.calls[0][2]["json"] == {
        "content": "<p>Text</p>\n",
        "reshipment_settings": "allowed",
        "comment_permission": "all",
        "reward_setting": {"can_reward": False},
    }
    assert result == PublishResult("published", "https://www.zhihu.com/answer/456", "Answer")
    assert source.read_text(encoding="utf-8").endswith("url: \"https://www.zhihu.com/answer/456\"\n---\nText\n")


def test_new_answer_draft_without_answer_id_does_not_write_answer_url(tmp_path):
    source = tmp_path / "answer-draft.md"
    original = '---\ntitle: Answer\nurl: "https://www.zhihu.com/question/321"\n---\nText\n'
    source.write_text(original, encoding="utf-8")
    parsed = parse_document(original, source)
    client = RecordingClient([{}])

    result = Publisher(client, FakeUploader()).publish_document(parsed, draft=True)

    assert calls_without_kwargs(client) == [
        ("POST", "https://www.zhihu.com/api/v4/questions/321/draft")
    ]
    assert result == PublishResult("draft", "https://www.zhihu.com/question/321#draft", "Answer")
    assert source.read_text(encoding="utf-8") == original


def test_new_answer_draft_with_id_writes_answer_url(tmp_path):
    source = tmp_path / "answer-draft.md"
    source.write_text("---\ntitle: Answer\nurl: https://www.zhihu.com/question/1\n---\nBody\n", encoding="utf-8")
    parsed = parse_document(source.read_text(encoding="utf-8"), source)

    result = Publisher(RecordingClient([{"id": "2"}]), FakeUploader()).publish_document(parsed, draft=True)

    assert result.url == "https://www.zhihu.com/answer/2"
    assert 'url: "https://www.zhihu.com/answer/2"' in source.read_text(encoding="utf-8")


def test_existing_answer_update_and_draft_routes_leave_url_unchanged(tmp_path):
    answer_url = "https://www.zhihu.com/question/10/answer/20"
    parsed = document(tmp_path, url=answer_url)
    client = RecordingClient([{}])

    result = Publisher(client, FakeUploader()).publish_document(parsed)

    assert calls_without_kwargs(client) == [
        ("PUT", "https://www.zhihu.com/api/v4/answers/20")
    ]
    assert client.calls[0][2]["json"] == {
        "content": "<p>Body</p>\n",
        "reward_setting": {"can_reward": False, "tagline": ""},
    }
    assert result.url == answer_url

    draft_client = RecordingClient([{}])
    Publisher(draft_client, FakeUploader()).publish_document(parsed, draft=True)
    assert calls_without_kwargs(draft_client) == [
        ("PUT", "https://www.zhihu.com/api/v4/questions/10/draft")
    ]


def test_answer_only_url_is_resolved_with_redirects_and_question_id(tmp_path):
    parsed = document(tmp_path, url="https://www.zhihu.com/answer/20")
    client = RecordingClient([
        httpx.Response(
            200,
            request=httpx.Request(
                "GET", "https://www.zhihu.com/question/10/answer/20"
            ),
        ),
        {},
    ])

    Publisher(client, FakeUploader()).publish_document(parsed)

    assert client.calls[0] == (
        "GET",
        "https://www.zhihu.com/answer/20",
        {"follow_redirects": True},
    )
    assert client.calls[1][0:2] == ("PUT", "https://www.zhihu.com/api/v4/answers/20")


def test_existing_article_draft_patches_and_syncs_tags_without_publish(tmp_path):
    url = "https://zhuanlan.zhihu.com/p/5"
    parsed = document(tmp_path, url=url)
    client = RecordingClient([{}, {"topics": []}])

    result = Publisher(client, FakeUploader()).publish_document(parsed, draft=True)

    assert calls_without_kwargs(client) == [
        ("PATCH", "https://zhuanlan.zhihu.com/api/articles/5/draft"),
        ("GET", "https://zhuanlan.zhihu.com/api/articles/5/draft"),
    ]
    assert result == PublishResult("draft", url, "Title")


def test_tag_sync_deletes_and_adds_serially_and_requires_exact_case_insensitive_match(tmp_path):
    client = RecordingClient([
        {"id": "6"}, {},
        {"topics": [{"id": "old", "name": "Old"}]},
        {},
        [{"id": "wrong", "name": "other"}],
    ])
    with pytest.raises(PartialPublishError, match="topic"):
        Publisher(client, FakeUploader()).publish_document(
            document(tmp_path, metadata="title: Title\ntags: wanted\n")
        )

    assert calls_without_kwargs(client)[-2:] == [
        ("DELETE", "https://zhuanlan.zhihu.com/api/articles/6/topics/old"),
        ("GET", "https://zhuanlan.zhihu.com/api/autocomplete/topics?token=wanted&max_matches=2&use_similar=0&topic_filter=1"),
    ]
    assert not any(url.endswith("/publish") for _, url in calls_without_kwargs(client))


@pytest.mark.parametrize(
    "payloads",
    [
        [(500, {"message": "denied"})],
        [{"id": "7"}, (500, {"message": "patch failed"})],
        [{"id": "7"}, {}, {"topics": []}, (500, {"message": "publish failed"})],
    ],
)
def test_failed_or_partial_article_flow_never_writes_url(tmp_path, payloads):
    source = tmp_path / "failure.md"
    original = "---\ntitle: Failure\n---\nBody\n"
    source.write_text(original, encoding="utf-8")
    parsed = parse_document(original, source)
    with pytest.raises((RuntimeError, PublishError, PartialPublishError)):
        Publisher(RecordingClient(payloads), FakeUploader()).publish_document(parsed)
    assert source.read_text(encoding="utf-8") == original


def test_article_writeback_preserves_bom_crlf_and_body_after_success(tmp_path):
    source = tmp_path / "crlf.md"
    original = "\ufeff---\r\ntitle: CRLF\r\ntags:\r\n  - one\r\n---\r\n# Body\r\n"
    source.write_text(original, encoding="utf-8", newline="")
    parsed = parse_document(original, source)
    client = RecordingClient([
        {"id": "77"}, {}, {"topics": []}, [{"id": "t1", "name": "one"}], {}, {},
    ])

    Publisher(client, FakeUploader()).publish_document(parsed)

    updated = read_raw(source)
    assert updated.startswith("\ufeff---\r\n")
    assert updated.endswith("---\r\n# Body\r\n")
    assert "url: \"https://zhuanlan.zhihu.com/p/77\"\r\n" in updated


def test_publish_file_preserves_bom_line_endings_and_existing_metadata(tmp_path):
    source = tmp_path / "file.md"
    original = "\ufeff---\r\ntitle: File\r\ncustom: value\r\n---\r\nBody\r\n"
    source.write_text(original, encoding="utf-8", newline="")
    client = RecordingClient([{"id": "88"}, {}, {"topics": []}, {}])

    Publisher(client, FakeUploader()).publish_file(source)

    updated = read_raw(source)
    assert "custom: value\r\n" in updated
    assert updated.endswith("---\r\nBody\r\n")


def test_write_request_failure_is_not_retried_and_errors_do_not_expose_details(tmp_path):
    client = RecordingClient([(403, {"message": "secret cookie must not appear"})])

    with pytest.raises(RuntimeError) as error:
        Publisher(client, FakeUploader()).publish_document(document(tmp_path))

    assert len(client.calls) == 1
    assert "secret cookie" not in str(error.value)


def test_publish_document_rejects_real_publish_without_dependencies_but_dry_run_works(tmp_path):
    publisher = Publisher(None, None)
    with pytest.raises(ValueError, match="client"):
        publisher.publish_document(document(tmp_path))
    assert publisher.publish_document(document(tmp_path), dry_run=True).status == "skipped"


def test_non_string_url_is_rejected_instead_of_routed_as_new_article(tmp_path):
    parsed = parse_document("---\ntitle: Title\nurl: 123\n---\nBody\n")

    with pytest.raises(ValueError, match="url"):
        Publisher(None, None).publish_document(parsed, dry_run=True)

