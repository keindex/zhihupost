"""Command-line interface for Zhihu publishing tools."""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zhihupost")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("login", help="Log in to Zhihu")
    commands.add_parser("whoami", help="Show the current account")
    commands.add_parser("logout", help="Log out of Zhihu")

    render = commands.add_parser("render", help="Render a Markdown file")
    render.add_argument("file")

    publish = commands.add_parser("publish", help="Publish a Markdown file")
    publish.add_argument("file")
    publish.add_argument("--draft", action="store_true")
    publish.add_argument("--dry-run", action="store_true")

    publish_dir = commands.add_parser("publish-dir", help="Publish Markdown files in a directory")
    publish_dir.add_argument("dir")
    publish_dir.add_argument("--draft", action="store_true")
    publish_dir.add_argument("--delay", type=float, default=60.0, metavar="SECONDS")

    upload_image = commands.add_parser("upload-image", help="Upload an image file")
    upload_image.add_argument("file")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"zhihupost {args.command}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
