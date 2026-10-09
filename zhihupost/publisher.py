"""Publish rendered Markdown to Zhihu through an injected API client."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import quote, urlsplit

from .document import Document, PublishTarget, classify_target, derive_title, parse_document, set_front_matter_value
from .markdown import render_markdown


@dataclass(frozen=True)
class PublishResult:
    status: Literal["published", "draft", "skipped"]
    url: str | None
    title: str | None


class PublishError(RuntimeError):
    """Sanitized error raised for a failed publish operation."""


class PartialPublishError(PublishError):
    """Raised when content was written but a later step failed."""


class Publisher:
    def __init__(self, client, uploader, renderer: Callable = render_markdown):
        self.client = client
        self.uploader = uploader
        self.renderer = renderer

    def publish_file(
        self,
        path: Path,
        *,
        draft: bool = False,
        dry_run: bool = False,
    ) -> PublishResult:
        source_path = Path(path)
        with source_path.open("r", encoding="utf-8", newline="") as source_file:
            text = source_file.read()
        return self.publish_document(
            parse_document(text, source_path), draft=draft, dry_run=dry_run
        )

    def publish_document(
        self,
        document: Document,
        *,
        draft: bool = False,
        dry_run: bool = False,
    ) -> PublishResult:
        raw_url = document.metadata.get("url")
        if raw_url is not None and raw_url != "" and not isinstance(raw_url, str):
            raise ValueError("Front matter 'url' must be a supported Zhihu URL string")
        target = classify_target(raw_url if isinstance(raw_url, str) and raw_url else None)
        title = _document_title(document)

        if dry_run:
            self.renderer(document.body)
            return PublishResult("skipped", None, title)
        if self.client is None:
            raise ValueError("An authenticated client is required to publish")
        if self.uploader is None:
            raise ValueError("An image uploader is required to publish")

        if target.kind in {"new_article", "article"}:
            if not title:
                raise ValueError("Article title is empty; add a title or a body heading")
            return self._publish_article(document, target, title, draft)
        return self._publish_answer(document, target, title, draft)

    def _publish_article(
        self, document: Document, target: PublishTarget, title: str, draft: bool
    ) -> PublishResult:
        base_dir = _base_dir(document)
        try:
            content = self.renderer(
                document.body,
                image_resolver=lambda source: self.uploader.upload(source, base_dir),
            )
            title_image_source = document.metadata.get("title-image")
            title_image = None
            if title_image_source is not None and str(title_image_source).strip():
                if not isinstance(title_image_source, str):
                    raise ValueError("Front matter 'title-image' must be a string")
                title_image = self.uploader.upload(title_image_source, base_dir)
        except Exception as exc:
            if isinstance(exc, (ValueError, FileNotFoundError)):
                raise
            raise PublishError("Unable to render or upload article images") from None

        if target.kind == "new_article":
            response = self._call(
                "POST",
                "https://zhuanlan.zhihu.com/api/articles/drafts",
                json={"title": "h", "delta_time": 0},
                stage="article draft creation",
            )
            payload = self._json(response, "article draft creation")
            article_id = payload.get("id") if isinstance(payload, dict) else None
            if article_id is None or not str(article_id):
                raise PublishError("Article draft creation response omitted its ID")
            article_id = str(article_id)

            self._call(
                "PATCH",
                f"https://zhuanlan.zhihu.com/api/articles/{article_id}/draft",
                json={
                    "content": content,
                    "title": title,
                    "titleImage": title_image,
                    "isTitleImageFullScreen": False,
                },
                stage="article content update",
            )
            try:
                self._sync_topics(article_id, _tags(document.metadata.get("tags")))
                if not draft:
                    column = self._resolve_column(document.metadata.get("column"))
                    self._call(
                        "PUT",
                        f"https://zhuanlan.zhihu.com/api/articles/{article_id}/publish",
                        json={"column": column, "commentPermission": "anyone"},
                        stage="article publish",
                    )
                url = f"https://zhuanlan.zhihu.com/p/{article_id}"
                self._write_url(document, url)
            except Exception as exc:
                if isinstance(exc, PartialPublishError):
                    raise
                raise PartialPublishError(
                    f"Article {article_id} was created but a later operation failed: {exc}"
                ) from None
            return PublishResult("draft" if draft else "published", url, title)

        article_id = target.article_id
        assert article_id is not None
        self._call(
            "PATCH",
            f"https://zhuanlan.zhihu.com/api/articles/{article_id}/draft",
            json={
                "content": content,
                "title": title,
                "titleImage": title_image,
                "isTitleImageFullScreen": False,
            },
            stage="article content update",
        )
        try:
            self._sync_topics(article_id, _tags(document.metadata.get("tags")))
            if not draft:
                column = self._resolve_column(document.metadata.get("column"))
                self._call(
                    "PUT",
                    f"https://zhuanlan.zhihu.com/api/articles/{article_id}/publish",
                    json={"column": column, "commentPermission": "anyone"},
                    stage="article publish",
                )
        except Exception as exc:
            raise PartialPublishError(
                f"Article {article_id} was updated but a later operation failed: {exc}"
            ) from None

        url = target.url
        return PublishResult("draft" if draft else "published", url, title)

    def _publish_answer(
        self, document: Document, target: PublishTarget, title: str | None, draft: bool
    ) -> PublishResult:
        try:
            content = self.renderer(
                document.body,
                image_resolver=lambda source: self.uploader.upload(source, _base_dir(document)),
            )
        except Exception as exc:
            if isinstance(exc, (ValueError, FileNotFoundError)):
                raise
            raise PublishError("Unable to render or upload answer images") from None

        question_id = target.question_id
        if target.kind == "answer" and question_id is None:
            lookup_url = f"https://www.zhihu.com/answer/{target.answer_id}"
            response = self._call(
                "GET", lookup_url, follow_redirects=True, stage="answer page lookup"
            )
            match = _question_id(str(response.url))
            if match is None:
                raise PublishError("Answer page did not redirect to a question URL")
            question_id = match
        if question_id is None:
            raise PublishError("The target question ID could not be determined")

        if target.kind == "question":
            endpoint = f"https://www.zhihu.com/api/v4/questions/{question_id}/"
            endpoint += "draft" if draft else "answers"
            payload = {
                "content": content,
                "reshipment_settings": "allowed",
                "comment_permission": "all",
                "reward_setting": {"can_reward": False},
            }
            response = self._call("POST", endpoint, json=payload, stage="answer creation")
            response_data = self._json(response, "answer creation")
            answer_id = _response_id(response_data)
            if answer_id is not None:
                url = f"https://www.zhihu.com/answer/{answer_id}"
                try:
                    self._write_url(document, url)
                except Exception:
                    raise PartialPublishError(
                        "Answer was created but its URL could not be written to the source file"
                    ) from None
            elif draft:
                url = f"https://www.zhihu.com/question/{question_id}#draft"
            else:
                url = None
            return PublishResult("draft" if draft else "published", url, title)

        assert target.answer_id is not None
        endpoint = (
            f"https://www.zhihu.com/api/v4/questions/{question_id}/draft"
            if draft
            else f"https://www.zhihu.com/api/v4/answers/{target.answer_id}"
        )
        self._call(
            "PUT",
            endpoint,
            json={
                "content": content,
                "reward_setting": {"can_reward": False, "tagline": ""},
            },
            stage="answer update",
        )
        return PublishResult("draft" if draft else "published", target.url, title)

    def _resolve_column(self, column_title: object):
        if column_title is None or (isinstance(column_title, str) and not column_title.strip()):
            return None
        if not isinstance(column_title, str):
            raise ValueError("Front matter 'column' must be a string")
        title = column_title.strip()
        profile = self._json(
            self._call("GET", "https://www.zhihu.com/api/v4/me", stage="profile lookup"),
            "profile lookup",
        )
        url_token = profile.get("url_token") if isinstance(profile, dict) else None
        if not isinstance(url_token, str) or not url_token:
            raise PublishError("Profile response omitted its url_token")
        columns_url = (
            "https://www.zhihu.com/api/v4/members/"
            f"{quote(url_token, safe='')}/column-contributions?include="
            "data%5B*%5D.column.intro%2Cfollowers%2Carticles_count&offset=0&limit=20"
        )
        columns = self._json(self._call("GET", columns_url, stage="column lookup"), "column lookup")
        data = columns.get("data") if isinstance(columns, dict) else None
        if isinstance(data, list):
            for item in data:
                column = item.get("column") if isinstance(item, dict) else None
                if isinstance(column, dict) and column.get("title") == title:
                    return column
        response = self._call(
            "POST",
            "https://www.zhihu.com/api/v4/columns/request",
            json={"title": title, "intro": "", "intro_type": "rich"},
            stage="column creation",
        )
        created = self._json(response, "column creation")
        if not isinstance(created, dict) or not created.get("id"):
            raise PublishError("Column creation response omitted its ID")
        return created

    def _sync_topics(self, article_id: str, tags: list[str]) -> None:
        base_url = f"https://zhuanlan.zhihu.com/api/articles/{article_id}"
        response = self._call("GET", f"{base_url}/draft", stage="article topic lookup")
        payload = self._json(response, "article topic lookup")
        topics = payload.get("topics") if isinstance(payload, dict) else None
        if not isinstance(topics, list):
            raise PublishError("Article topic lookup response omitted its topics list")

        desired = {tag.casefold() for tag in tags}
        current_names: set[str] = set()
        for topic in topics:
            if not isinstance(topic, dict) or not isinstance(topic.get("name"), str):
                raise PublishError("Article topic lookup returned an invalid topic")
            name = topic["name"]
            current_names.add(name.casefold())
            if name.casefold() not in desired:
                topic_id = topic.get("id")
                if topic_id is None:
                    raise PublishError("Article topic to remove omitted its ID")
                self._call(
                    "DELETE",
                    f"{base_url}/topics/{quote(str(topic_id), safe='')}",
                    stage="topic removal",
                )

        for tag in tags:
            if tag.casefold() in current_names:
                continue
            encoded_tag = quote(tag, safe=";/?:@&=+$,#-_.!~*'()")
            search_url = (
                "https://zhuanlan.zhihu.com/api/autocomplete/topics?token="
                f"{encoded_tag}&max_matches=2&use_similar=0&topic_filter=1"
            )
            matches = self._json(
                self._call("GET", search_url, stage="topic lookup"), "topic lookup"
            )
            if not isinstance(matches, list) or not matches:
                raise PublishError(f"Could not find the requested topic '{tag}'")
            topic = matches[0]
            if not isinstance(topic, dict) or not isinstance(topic.get("name"), str):
                raise PublishError(f"Topic lookup returned an invalid result for '{tag}'")
            if topic["name"].casefold() != tag.casefold():
                raise PublishError(f"Could not find an exact topic match for '{tag}'")
            self._call(
                "POST", f"{base_url}/topics", json=topic, stage="topic addition"
            )

    def _write_url(self, document: Document, url: str) -> None:
        if document.source_path is None:
            return
        source_path = Path(document.source_path)
        with source_path.open("r", encoding="utf-8", newline="") as source_file:
            source = source_file.read()
        updated = set_front_matter_value(source, "url", url)
        with source_path.open("w", encoding="utf-8", newline="") as source_file:
            source_file.write(updated)

    def _call(self, method: str, url: str, *, stage: str, **kwargs):
        try:
            response = self.client.request(method, url, **kwargs)
        except Exception:
            raise PublishError(f"Request failed during {stage}") from None
        status = getattr(response, "status_code", None)
        if not isinstance(status, int) or not 200 <= status < 300:
            suffix = f" (HTTP {status})" if isinstance(status, int) else ""
            raise PublishError(f"Request failed during {stage}{suffix}")
        return response

    @staticmethod
    def _json(response, stage: str):
        try:
            return response.json()
        except (ValueError, UnicodeDecodeError, TypeError):
            raise PublishError(f"Invalid JSON response during {stage}") from None


def _document_title(document: Document) -> str | None:
    value = document.metadata.get("title")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return derive_title(document.body)


def _base_dir(document: Document) -> Path:
    return document.source_path.parent if document.source_path is not None else Path.cwd()


def _tags(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [tag.strip() for tag in value.split(",") if tag.strip()]
    if isinstance(value, list) and all(isinstance(tag, str) for tag in value):
        return [tag.strip() for tag in value if tag.strip()]
    raise ValueError("Front matter 'tags' must be a string or list of strings")


def _response_id(payload: object) -> str | None:
    if isinstance(payload, dict):
        value = payload.get("id")
        if value is None and isinstance(payload.get("data"), dict):
            value = payload["data"].get("id")
        if value is not None and str(value):
            return str(value)
    return None


def _question_id(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.hostname != "www.zhihu.com":
        return None
    pieces = parsed.path.split("/")
    if len(pieces) >= 3 and pieces[1] == "question" and pieces[2].isdigit():
        return pieces[2]
    return None
