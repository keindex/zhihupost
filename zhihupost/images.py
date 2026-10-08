import hashlib
import re
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

import httpx
import oss2

from .client import ZhihuClient


IMAGE_UPLOAD_URL = "https://api.zhihu.com/images"
IMAGE_HOST = "https://pic4.zhimg.com/80"
OSS_ENDPOINT = "https://zhihu-pics-upload.zhimg.com"
OSS_BUCKET = "zhihu-pics"
OSS_REGION = "oss-cn-hangzhou"


def resolve_source(source: str, base_dir: Path) -> tuple[bytes, str]:
    """Read a local or remote image and return its bytes and filename suffix."""
    return _resolve_source(source, base_dir, remote_transport=None)


def _resolve_source(
    source: str,
    base_dir: Path,
    remote_transport: httpx.BaseTransport | None,
) -> tuple[bytes, str]:
    source = str(source)
    parsed = urlsplit(source)
    windows_drive_path = bool(re.match(r"^[A-Za-z]:[\\/]", source))

    if parsed.scheme.lower() in {"http", "https"}:
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError("Image URL must have a host and cannot contain credentials")
        suffix = Path(unquote(parsed.path)).suffix
        _reject_svg(suffix)
        with httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            transport=remote_transport,
        ) as remote_client:
            response = remote_client.get(source)
            response.raise_for_status()
            return response.content, suffix

    if parsed.scheme and not windows_drive_path:
        raise ValueError("Unsupported image URL scheme")

    local_name = unquote(source)
    local_path = Path(local_name)
    suffix = local_path.suffix
    _reject_svg(suffix)
    if not local_path.is_absolute():
        if base_dir is None:
            raise ValueError("A base directory is required for relative image paths")
        local_path = Path(base_dir) / local_path
    return local_path.read_bytes(), suffix


def _reject_svg(suffix: str) -> None:
    if suffix.lower() == ".svg":
        raise ValueError("SVG images are not supported")


class ImageUploader:
    def __init__(
        self,
        client: ZhihuClient,
        oss_put: Callable[[dict, str, bytes], None] | None = None,
        remote_transport: httpx.BaseTransport | None = None,
    ):
        self.client = client
        self.oss_put = oss_put
        self.remote_transport = remote_transport

    def upload(self, source: str, base_dir: Path) -> str:
        image_bytes, suffix = _resolve_source(
            source,
            base_dir,
            remote_transport=self.remote_transport,
        )
        image_hash = hashlib.md5(image_bytes, usedforsecurity=False).hexdigest()
        response = self.client.request(
            "POST",
            IMAGE_UPLOAD_URL,
            json={"image_hash": image_hash, "source": "answer"},
        )
        if not 200 <= response.status_code < 300:
            response.raise_for_status()
        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Zhihu image preflight returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("Zhihu image preflight returned an invalid response")

        upload_token = payload.get("upload_token")
        if upload_token is None:
            return f"{IMAGE_HOST}/v2-{image_hash}{suffix}"
        if not isinstance(upload_token, dict):
            raise ValueError("Zhihu image preflight returned an invalid upload token")

        upload_file = payload.get("upload_file")
        object_key = upload_file.get("object_key") if isinstance(upload_file, dict) else None
        if not isinstance(object_key, str) or not object_key:
            raise ValueError("Zhihu image preflight omitted the object key")
        for field in ("access_id", "access_key", "access_token"):
            if not isinstance(upload_token.get(field), str) or not upload_token[field]:
                raise ValueError("Zhihu image preflight returned incomplete upload credentials")

        if self.oss_put is None:
            self._put_object(upload_token, object_key, image_bytes)
        else:
            self.oss_put(upload_token, object_key, image_bytes)
        return f"{IMAGE_HOST}/v2-{image_hash}{suffix}"

    @staticmethod
    def _put_object(upload_token: dict, object_key: str, image_bytes: bytes) -> None:
        auth = oss2.StsAuth(
            upload_token["access_id"],
            upload_token["access_key"],
            upload_token["access_token"],
        )
        bucket = oss2.Bucket(
            auth,
            OSS_ENDPOINT,
            OSS_BUCKET,
            is_cname=True,
            region=OSS_REGION,
        )
        bucket.put_object(object_key, image_bytes)
