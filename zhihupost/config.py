import os
import tempfile
from pathlib import Path

from platformdirs import user_config_path


class CookieError(ValueError):
    """Raised when no usable cookie is configured or it cannot be stored."""


class CookieStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else Path(
            user_config_path("zhihupost", appauthor=False)
        ) / "cookie"

    def load(self) -> str | None:
        try:
            return self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def save(self, cookie: str) -> None:
        from .auth import parse_cookie_header

        try:
            parse_cookie_header(cookie)
        except (TypeError, ValueError):
            raise CookieError("Cookie is empty or malformed") from None

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(cookie)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name == "posix":
                os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        finally:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)
