"""Local Markdown rendering for Zhihu-compatible article HTML."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from html import escape
from urllib.parse import quote

import emoji
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin


_LINK_CARD_PREFIX = "zhihu-link-card:"
_EQUATION_URL = "//www.zhihu.com/equation?tex="


def _equation_image(tex: str) -> str:
    source = quote(tex.strip(), safe="")
    alt = escape(tex.strip(), quote=True)
    return f'<img eeimg="1" src="{_EQUATION_URL}{source}" alt="{alt}"/>'


def _render_inline_math(self, tokens, index, options, env) -> str:
    return _equation_image(tokens[index].content)


def _render_block_math(self, tokens, index, options, env) -> str:
    return f"<p>{_equation_image(tokens[index].content)}</p>\n"


def _render_fence(self, tokens, index, options, env) -> str:
    token = tokens[index]
    language = token.info.strip().split(maxsplit=1)
    lang_attr = f' lang="{escape(language[0], quote=True)}"' if language else ""
    return f"<pre{lang_attr}>{escape(token.content)}</pre>\n"


def _render_reference(self, tokens, index, options, env) -> str:
    token = tokens[index]
    return f"<sup{self.renderAttrs(token)}>{escape(token.content)}</sup>"


def _table_open(self, tokens, index, options, env) -> str:
    return '<table data-draft-node="block" data-draft-type="table" data-size="normal">'


def _thead_open(self, tokens, index, options, env) -> str:
    return "<tbody>"


def _empty_rule(self, tokens, index, options, env) -> str:
    return ""


def _tbody_close(self, tokens, index, options, env) -> str:
    return "</tbody>"


def _rewrite_tasklists(tokens: Sequence[Token]) -> None:
    for token in tokens:
        if token.type == "list_item_open" and token.attrs:
            if token.attrs.get("class") == "task-list-item enabled":
                token.attrs.pop("class", None)
        elif token.type in {"bullet_list_open", "ordered_list_open"} and token.attrs:
            if token.attrs.get("class") == "contains-task-list":
                token.attrs.pop("class", None)

        if token.type != "inline" or not token.children:
            continue
        first = token.children[0]
        if first.type != "html_inline" or "task-list-item-checkbox" not in first.content:
            continue
        marker = (
            ":ballot_box_with_check: "
            if 'checked="checked"' in first.content
            else ":white_circle: "
        )
        first.type = "text"
        first.tag = ""
        first.attrs = None
        first.content = marker
        if len(token.children) > 1:
            content = token.children[1]
            if content.type == "text" and content.content.startswith(" "):
                content.content = content.content[1:]


def _replace_emoji_shortcodes(tokens: Sequence[Token]) -> None:
    for block_token in tokens:
        for child in block_token.children or []:
            if child.type == "text":
                child.content = emoji.emojize(child.content, language="alias")


def _rewrite_footnotes(tokens: list[Token]) -> None:
    references: dict[str, str] = {}
    start = next(
        (index for index, token in enumerate(tokens) if token.type == "footnote_block_open"),
        len(tokens),
    )
    label: str | None = None
    for token in tokens[start:]:
        if token.type == "footnote_open":
            label = token.meta.get("label")
        elif token.type == "inline" and label is not None:
            references[str(label)] = token.content
        elif token.type == "footnote_close":
            label = None

    if start < len(tokens):
        del tokens[start:]

    for block_token in tokens:
        for child in block_token.children or []:
            if child.type != "footnote_ref":
                continue
            label = str(child.meta.get("label", ""))
            reference = references.get(label, "")
            url, _, text = reference.partition(" ")
            child.type = "zhihu_reference"
            child.tag = "sup"
            child.attrs = {
                "data-text": text,
                "data-url": url or reference,
                "data-draft-node": "inline",
                "data-draft-type": "reference",
                "data-numero": label,
            }
            child.content = f"[{label}]"


def _postprocess_tokens(
    tokens: list[Token], image_resolver: Callable[[str], str] | None
) -> None:
    _rewrite_footnotes(tokens)
    _rewrite_tasklists(tokens)
    _replace_emoji_shortcodes(tokens)

    for block_token in tokens:
        children = block_token.children
        if not children:
            continue

        for child in children:
            if child.type == "image" and image_resolver is not None:
                source = child.attrGet("src")
                if source is not None:
                    child.attrSet("src", image_resolver(source))

        for index in range(len(children) - 2):
            opening, image, closing = children[index : index + 3]
            if not (
                opening.type == "link_open"
                and image.type == "image"
                and closing.type == "link_close"
                and image.content.startswith(_LINK_CARD_PREFIX)
            ):
                continue

            opening.attrSet("data-draft-node", "block")
            opening.attrSet("data-draft-type", "link-card")
            opening.attrSet("data-image", image.attrGet("src") or "")
            opening.attrSet("data-image-width", "640")
            opening.attrSet("data-image-height", "480")
            image.type = "text"
            image.tag = ""
            image.content = image.content[len(_LINK_CARD_PREFIX) :]
            image.attrs = None
            image.children = None


def render_markdown(body: str, image_resolver: Callable[[str], str] | None = None) -> str:
    """Render supported Markdown without making network requests."""
    md = MarkdownIt("default", {"html": True})
    md.use(tasklists_plugin, enabled=True)
    md.use(footnote_plugin)
    md.use(dollarmath_plugin)
    md.add_render_rule("fence", _render_fence)
    md.add_render_rule("math_inline", _render_inline_math)
    md.add_render_rule("math_inline_double", _render_inline_math)
    md.add_render_rule("math_block", _render_block_math)
    md.add_render_rule("math_block_label", _render_block_math)
    md.add_render_rule("zhihu_reference", _render_reference)
    md.add_render_rule("table_open", _table_open)
    md.add_render_rule("thead_open", _thead_open)
    md.add_render_rule("thead_close", _empty_rule)
    md.add_render_rule("tbody_open", _empty_rule)
    md.add_render_rule("tbody_close", _tbody_close)

    def postprocess(state) -> None:
        _postprocess_tokens(state.tokens, image_resolver)

    md.core.ruler.after("github-tasklists", "zhihu_content", postprocess)
    return md.render(body)
