"""Markdown front matter and Zhihu target helpers."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml


@dataclass
class Document:
    metadata: dict[str, object]
    body: str
    source_path: Path | None


PublishTargetKind = Literal["new_article", "question", "answer", "article"]


@dataclass
class PublishTarget:
    kind: PublishTargetKind
    url: str | None
    article_id: str | None = None
    question_id: str | None = None
    answer_id: str | None = None


@dataclass(frozen=True)
class _FrontMatter:
    opening_end: int
    closing_start: int
    closing_end: int
    newline: str


def _newline_for(text: str) -> str:
    match = re.search(r"\r\n|\n|\r", text)
    return match.group(0) if match else "\n"


def _front_matter(text: str) -> _FrontMatter | None:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n").strip() != "---":
        return None

    opening_end = len(lines[0])
    offset = opening_end
    for line in lines[1:]:
        line_start = offset
        offset += len(line)
        if line.rstrip("\r\n").strip() == "---":
            return _FrontMatter(
                opening_end=opening_end,
                closing_start=line_start,
                closing_end=offset,
                newline=_newline_for(lines[0]),
            )
    raise ValueError("Unclosed YAML front matter: expected a closing '---' line.")


def _normalize_tags(metadata: dict[str, object]) -> None:
    if "tags" not in metadata:
        return

    value = metadata["tags"]
    if isinstance(value, str):
        metadata["tags"] = [tag.strip() for tag in value.split(",") if tag.strip()]
        return
    if isinstance(value, list) and all(isinstance(tag, str) for tag in value):
        metadata["tags"] = [tag.strip() for tag in value if tag.strip()]
        return
    raise ValueError("Front matter 'tags' must be a comma-separated string or a list of strings.")


def parse_document(text: str, source_path: Path | None = None) -> Document:
    """Parse a leading YAML block while retaining the Markdown body verbatim."""
    parse_text = text[1:] if text.startswith("\ufeff") else text
    front_matter = _front_matter(parse_text)
    if front_matter is None:
        return Document(metadata={}, body=text, source_path=source_path)

    yaml_text = parse_text[front_matter.opening_end : front_matter.closing_start]
    try:
        metadata = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}" if mark is not None else ""
        raise ValueError(f"Invalid YAML front matter{location}.") from None

    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict) or any(not isinstance(key, str) for key in metadata):
        raise ValueError("YAML front matter must be a mapping with string keys.")
    _normalize_tags(metadata)

    return Document(
        metadata=metadata,
        body=parse_text[front_matter.closing_end :],
        source_path=source_path,
    )


def derive_title(body: str) -> str | None:
    """Return the first nonempty Markdown body line as a plain title."""
    content = body[1:] if body.startswith("\ufeff") else body
    try:
        front_matter = _front_matter(content)
    except ValueError:
        return None
    if front_matter is not None:
        content = content[front_matter.closing_end :]

    for line in content.splitlines():
        title = line.strip()
        if not title:
            continue
        title = re.sub(r"^#{1,6}\s*", "", title).strip()
        if title:
            return title
    return None


def classify_target(url: str | None) -> PublishTarget:
    """Validate and classify the supported Zhihu content URLs."""
    if url is None:
        return PublishTarget(kind="new_article", url=None)
    if not isinstance(url, str) or not url:
        raise ValueError("Target URL must be a supported HTTPS Zhihu URL.")

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("Target URL must be a supported HTTPS Zhihu URL.") from None
    if (
        parsed.scheme.lower() != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        raise ValueError("Target URL must be a supported HTTPS Zhihu URL.")

    host = hostname.lower()
    path = parsed.path
    if host == "www.zhihu.com":
        match = re.fullmatch(r"/question/(\d+)", path, re.IGNORECASE)
        if match:
            return PublishTarget(kind="question", url=url, question_id=match.group(1))
        match = re.fullmatch(r"/question/(\d+)/answer/(\d+)", path, re.IGNORECASE)
        if match:
            return PublishTarget(
                kind="answer",
                url=url,
                question_id=match.group(1),
                answer_id=match.group(2),
            )
        match = re.fullmatch(r"/answer/(\d+)", path, re.IGNORECASE)
        if match:
            return PublishTarget(kind="answer", url=url, answer_id=match.group(1))
    elif host == "zhuanlan.zhihu.com":
        match = re.fullmatch(r"/p/(\d+)", path, re.IGNORECASE)
        if match:
            return PublishTarget(kind="article", url=url, article_id=match.group(1))

    raise ValueError("Target URL host or path is not a supported Zhihu content URL.")


def _serialized_string(value: str) -> str:
    serialized = yaml.safe_dump(
        value,
        allow_unicode=True,
        default_style='"',
        width=1_000_000,
    ).strip().splitlines()
    if serialized and serialized[-1] == "...":
        serialized.pop()
    return "\n".join(serialized)


def _field_pattern(key: str) -> re.Pattern[str]:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
        raise ValueError("Front matter key must be a simple YAML field name.")
    return re.compile(rf"^{re.escape(key)}\s*:")


def set_front_matter_value(text: str, key: str, value: str) -> str:
    """Set one string field without rewriting the body or unrelated metadata."""
    if not isinstance(value, str):
        raise TypeError("Front matter values written by this helper must be strings.")
    pattern = _field_pattern(key)
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    source = text[len(bom) :]
    front_matter = _front_matter(source)
    newline = front_matter.newline if front_matter else _newline_for(source)
    serialized = _serialized_string(value)

    if front_matter is None:
        return (
            f"{bom}---{newline}{key}: {serialized}{newline}---{newline}"
            f"{source}"
        )

    yaml_region = source[front_matter.opening_end : front_matter.closing_start]
    lines = yaml_region.splitlines(keepends=True)
    line_offsets: list[tuple[int, int, str, str]] = []
    offset = 0
    for line in lines:
        line_end = offset + len(line)
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        line_offsets.append((offset, line_end, content, ending))
        offset = line_end

    for index, (line_start, line_end, content, ending) in enumerate(line_offsets):
        if pattern.match(content):
            replacement_end = line_end
            for next_start, next_end, next_content, _ in line_offsets[index + 1 :]:
                if next_content.strip() and not next_content[0].isspace():
                    break
                replacement_end = next_end
            updated_region = (
                yaml_region[:line_start]
                + f"{key}: {serialized}{ending or newline}"
                + yaml_region[replacement_end:]
            )
            return (
                f"{bom}{source[: front_matter.opening_end]}{updated_region}"
                f"{source[front_matter.closing_start:]}"
            )

    insertion = f"{key}: {serialized}{newline}"
    return (
        f"{bom}{source[: front_matter.closing_start]}{insertion}"
        f"{source[front_matter.closing_start:]}"
    )
