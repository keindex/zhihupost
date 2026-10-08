import argparse

from zhihupost.cli import build_parser


def test_parser_registers_supported_commands():
    parser = build_parser()
    action = next(
        item for item in parser._actions if isinstance(item, argparse._SubParsersAction)
    )
    assert set(action.choices) == {
        "login",
        "whoami",
        "logout",
        "render",
        "publish",
        "publish-dir",
        "upload-image",
    }


def test_publish_flags_parse():
    parsed = build_parser().parse_args(["publish", "draft.md", "--draft", "--dry-run"])
    assert (parsed.file, parsed.draft, parsed.dry_run) == ("draft.md", True, True)
