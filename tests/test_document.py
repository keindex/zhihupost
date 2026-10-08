from pathlib import Path

import pytest

from zhihupost.document import (
    classify_target,
    derive_title,
    parse_document,
    set_front_matter_value,
)


def test_parse_bom_front_matter_and_normalize_comma_tags():
    document = parse_document(
        '\ufeff---\r\ntitle: "A: title"\r\ntags: one, two, ,\r\n---\r\n# Body\r\n'
    )

    assert document.metadata == {"title": "A: title", "tags": ["one", "two"]}
    assert document.body == "# Body\r\n"


def test_parse_yaml_list_tags_and_source_path(tmp_path):
    source = tmp_path / "article.md"
    document = parse_document("---\ntags:\n  - one\n  - two\n---\nBody", source)

    assert document.metadata["tags"] == ["one", "two"]
    assert document.source_path == source


def test_parse_missing_front_matter_keeps_original_text():
    source = "\ufeff# Heading\r\nBody\r\n"
    document = parse_document(source)

    assert document.metadata == {}
    assert document.body == source


@pytest.mark.parametrize(
    "source",
    [
        "---\ntitle: Missing close\nBody\n",
        "---\ntitle: [invalid\n---\nBody\n",
        "---\n- not\n- a mapping\n---\nBody\n",
        "---\ntags: 42\n---\nBody\n",
        "---\ntags: [one, 2]\n---\nBody\n",
    ],
)
def test_parse_rejects_malformed_front_matter_and_tags(source):
    with pytest.raises(ValueError):
        parse_document(source)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("\n  \r\n## First title  \nmore", "First title"),
        ("---\ntitle: Ignored\n---\n\n###### Heading\n", "Heading"),
        ("  Plain first line  \n# Later", "Plain first line"),
        ("\n\t\n", None),
        ("---\nnot closed\n# Not body", None),
    ],
)
def test_derive_title(body, expected):
    assert derive_title(body) == expected


@pytest.mark.parametrize(
    ("url", "kind", "article_id", "question_id", "answer_id"),
    [
        (None, "new_article", None, None, None),
        ("https://www.zhihu.com/question/123", "question", None, "123", None),
        (
            "https://www.zhihu.com/question/123/answer/456",
            "answer",
            None,
            "123",
            "456",
        ),
        ("https://www.zhihu.com/answer/456", "answer", None, None, "456"),
        (
            "https://zhuanlan.zhihu.com/p/789",
            "article",
            "789",
            None,
            None,
        ),
    ],
)
def test_classify_supported_targets(url, kind, article_id, question_id, answer_id):
    target = classify_target(url)

    assert target.kind == kind
    assert target.url == url
    assert target.article_id == article_id
    assert target.question_id == question_id
    assert target.answer_id == answer_id


@pytest.mark.parametrize(
    "url",
    [
        "http://www.zhihu.com/question/123",
        "https://example.org/question/123",
        "https://www.zhihu.com.evil.test/question/123",
        "https://zhuanlan.zhihu.com/question/123",
        "https://www.zhihu.com/question/123/",
        "https://www.zhihu.com/question/123/answer/456/extra",
        "https://www.zhihu.com/question/nope",
        "https://www.zhihu.com/answer/12x",
        "https://zhuanlan.zhihu.com/p/123/extra",
        "ftp://www.zhihu.com/answer/123",
    ],
)
def test_classify_rejects_unsupported_urls(url):
    with pytest.raises(ValueError):
        classify_target(url)


def test_writeback_updates_only_selected_field_and_preserves_crlf_body():
    source = "---\r\ntitle: Old\r\ntags:\r\n  - one\r\n---\r\nBody\r\n"
    updated = set_front_matter_value(source, "url", "https://zhuanlan.zhihu.com/p/12")

    assert updated == (
        "---\r\ntitle: Old\r\ntags:\r\n  - one\r\n"
        'url: "https://zhuanlan.zhihu.com/p/12"\r\n---\r\nBody\r\n'
    )
    changed = set_front_matter_value(updated, "title", 'A: "quoted" title')
    assert parse_document(changed).metadata["title"] == 'A: "quoted" title'
    assert changed.endswith("---\r\nBody\r\n")


def test_writeback_replaces_existing_field_and_keeps_lf_body():
    source = "---\ntitle: Old\nurl: old\n---\nBody\n"
    updated = set_front_matter_value(source, "url", "https://www.zhihu.com/answer/42")

    assert updated == '---\ntitle: Old\nurl: "https://www.zhihu.com/answer/42"\n---\nBody\n'


def test_writeback_creates_front_matter_before_bom_prefixed_body():
    source = "\ufeff# Heading\r\nBody\r\n"
    updated = set_front_matter_value(source, "title", "A: title")

    assert updated.startswith("\ufeff---\r\ntitle: ")
    assert updated.endswith("\r\n---\r\n# Heading\r\nBody\r\n")
    assert parse_document(updated).metadata["title"] == "A: title"


def test_writeback_rejects_unclosed_front_matter():
    with pytest.raises(ValueError):
        set_front_matter_value("---\ntitle: Old\nBody\n", "url", "new")
