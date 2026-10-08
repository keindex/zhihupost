from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from zhihupost.markdown import render_markdown


ROOT = Path(__file__).resolve().parents[1]


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def parse_html(html):
    parsed = Elements()
    parsed.feed(html)
    return parsed


def test_existing_fixture_preserves_code_images_and_math():
    source = (ROOT / "test/fixtures/publishTest/test.md").read_text(encoding="utf-8")
    html = render_markdown(source)
    parsed = parse_html(html)

    headings = [attrs for tag, attrs in parsed.elements if tag == "h2"]
    code_blocks = [attrs for tag, attrs in parsed.elements if tag == "pre"]
    images = [attrs for tag, attrs in parsed.elements if tag == "img"]

    assert len(headings) == 1
    assert code_blocks == [{"lang": "java"}]
    assert len(images) == 3
    assert images[0]["src"] == "https://pic4.zhimg.com/80/v2-00de3f8c56765b4b68ed43fe8513a8c4.png"
    equations = [image for image in images if image.get("eeimg") == "1"]
    assert len(equations) == 2
    assert all("alt" in image for image in equations)
    assert quote(r"\sqrt5\sqrt7", safe="") in equations[0]["src"]
    equation_queries = [parse_qs(urlsplit(image["src"]).query)["tex"][0] for image in equations]
    assert r"\sqrt5\sqrt7" in equation_queries[0]
    assert "Latex" in equation_queries[1]
    assert "eeimg=\"1\"" in html


def test_task_lists_footnotes_tables_and_unicode_emoji():
    html = render_markdown(
        "- [ ] pending\n- [x] done\n\nA **bold** note[^source] 😀 :smile:\n\n"
        "[^source]: https://example.com citation\n\n| Name | Value |\n| --- | --- |\n| a | b |\n"
    )
    parsed = parse_html(html)
    tags = [tag for tag, _ in parsed.elements]

    assert "input" not in tags
    assert "⚪ pending" in html and "☑️ done" in html
    assert "table" in tags and "th" in tags and "td" in tags
    table = next(item for tag, item in parsed.elements if tag == "table")
    assert table == {
        "data-draft-node": "block",
        "data-draft-type": "table",
        "data-size": "normal",
    }
    reference = next(item for tag, item in parsed.elements if tag == "sup")
    assert reference == {
        "data-text": "citation",
        "data-url": "https://example.com",
        "data-draft-node": "inline",
        "data-draft-type": "reference",
        "data-numero": "source",
    }
    assert "<strong>bold</strong>" in html
    assert "😀" in "".join(parsed.text) and "😄" in html


def test_link_card_semantics_and_image_resolver():
    seen = []

    def resolve(source):
        seen.append(source)
        return f"https://images.example/{source.rsplit('/', 1)[-1]}"

    html = render_markdown(
        "![body](/body.png)\n\n"
        "[![zhihu-link-card:caption](/card.png)](https://example.com/article)",
        image_resolver=resolve,
    )
    parsed = parse_html(html)
    anchors = [attrs for tag, attrs in parsed.elements if tag == "a"]
    images = [attrs for tag, attrs in parsed.elements if tag == "img"]

    assert seen == ["/body.png", "/card.png"]
    assert images == [{"src": "https://images.example/body.png", "alt": "body"}]
    card = next(attrs for attrs in anchors if attrs.get("data-draft-type") == "link-card")
    assert card["data-draft-node"] == "block"
    assert card["data-image"] == "https://images.example/card.png"
    assert "https://images.example/card.png" not in html.split("<a", 1)[1].split(">", 1)[1]
    assert "caption" in html


def test_image_references_are_unchanged_without_resolver():
    html = render_markdown(
        "![body](/body.png)\n\n[![zhihu-link-card:caption](/card.png)](https://example.com)"
    )

    assert 'src="/body.png"' in html
    assert 'data-image="/card.png"' in html


def test_raw_html_is_preserved():
    assert render_markdown("<div data-source=\"markdown\">raw</div>") == (
        '<div data-source="markdown">raw</div>'
    )
