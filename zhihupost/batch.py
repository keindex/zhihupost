"""Recursive, sequential publishing of Markdown files."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .publisher import Publisher


@dataclass(frozen=True)
class BatchSummary:
    succeeded: int
    skipped: int
    failed: int
    failures: list[tuple[Path, str]]


def publish_directory(
    root: Path,
    publisher: Publisher,
    *,
    draft: bool = False,
    delay: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> BatchSummary:
    """Publish every Markdown file below *root* in deterministic order."""

    if delay < 0:
        raise ValueError("delay must be non-negative")
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"Batch root is not a directory: {root}")

    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() == ".md"
    ]
    files.sort(key=lambda path: path.relative_to(root).as_posix().casefold())

    succeeded = skipped = failed = 0
    failures: list[tuple[Path, str]] = []
    for index, path in enumerate(files):
        try:
            result = publisher.publish_file(path, draft=draft)
            if getattr(result, "status", None) == "skipped":
                skipped += 1
            else:
                succeeded += 1
        except Exception as exc:
            failed += 1
            failures.append((path, str(exc).strip() or exc.__class__.__name__))
        if index < len(files) - 1:
            sleep(delay)

    return BatchSummary(succeeded, skipped, failed, failures)
