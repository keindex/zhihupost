from pathlib import Path

from zhihupost.batch import BatchSummary, publish_directory
from zhihupost.publisher import PublishResult


class StubPublisher:
    def __init__(self):
        self.paths = []

    def publish_file(self, path, *, draft=False):
        self.paths.append((Path(path), draft))
        if Path(path).name == "b.MD":
            raise RuntimeError("mocked failure")
        if Path(path).name == "skip.md":
            return PublishResult("skipped", None, "Skip")
        return PublishResult("published", "https://zhuanlan.zhihu.com/p/1", "A")


def test_batch_sorts_waits_between_files_and_continues(tmp_path):
    (tmp_path / "b.MD").write_text("b", encoding="utf-8")
    (tmp_path / "skip.md").write_text("skip", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "a.md").write_text("a", encoding="utf-8")
    sleeps = []
    publisher = StubPublisher()

    summary = publish_directory(tmp_path, publisher, draft=True, delay=3, sleep=sleeps.append)

    assert [path.relative_to(tmp_path).as_posix() for path, _ in publisher.paths] == [
        "b.MD",
        "nested/a.md",
        "skip.md",
    ]
    assert all(draft for _, draft in publisher.paths)
    assert sleeps == [3, 3]
    assert summary == BatchSummary(
        succeeded=1,
        skipped=1,
        failed=1,
        failures=[(tmp_path / "b.MD", "mocked failure")],
    )


def test_batch_uses_default_delay_and_does_not_sleep_for_empty_or_single_file(tmp_path):
    sleeps = []
    publisher = StubPublisher()
    assert publish_directory(tmp_path, publisher, sleep=sleeps.append).succeeded == 0
    assert sleeps == []

    (tmp_path / "only.Md").write_text("only", encoding="utf-8")
    assert publish_directory(tmp_path, publisher, sleep=sleeps.append).failed == 0
    assert sleeps == []


def test_batch_rejects_negative_delay(tmp_path):
    publisher = StubPublisher()
    try:
        publish_directory(tmp_path, publisher, delay=-1)
    except ValueError as error:
        assert "delay" in str(error)
    else:
        raise AssertionError("negative delay must fail")
