# Python CLI Design

## Goal

Add a Python command-line implementation of zhihupost's active Zhihu authoring workflow. The Python CLI becomes a usable alternative for terminal users while the existing VS Code extension remains in the repository as a compatibility reference.

## Scope

The CLI will support:

- Cookie-based authentication, account status, and logout.
- Rendering Markdown with YAML front matter into Zhihu-compatible HTML.
- Creating or updating articles and answers, either published or saved as drafts.
- Recursively publishing or drafting Markdown files in a directory, with an adjustable inter-file delay.
- Local and remote image upload, including images embedded in Markdown and title images.
- Article tags and selecting or creating a column from front matter.
- Writing the created article or answer URL back to the Markdown file after a successful create/draft operation, where it can identify the content for later updates.

Front matter fields remain `title`, `url`, `column`, `title-image`, and `tags`. With no `url`, a new article is created. A question URL creates an answer, an answer URL updates that answer, and an article URL updates that article. A missing title may be derived from the first nonempty body line or heading.

VS Code-only webviews, editor completion, clipboard UI, interactive search, and the dormant event scheduler are out of scope. The Python project will not remove or modify the TypeScript extension as part of this work.

## Architecture

The repository root will gain a `pyproject.toml` and an importable `zhihupost` package with separate modules for CLI parsing, Markdown/front matter, Zhihu HTTP access, authentication/configuration, image upload, and publish orchestration. The CLI will use Python's standard `argparse` interface and the following runtime dependencies: `markdown-it-py` plus `mdit-py-plugins` for rendering, `PyYAML` for front matter, `httpx` for HTTP, `oss2` for Zhihu's temporary upload credentials, and `platformdirs` for configuration paths.

Planned commands are `login`, `whoami`, `logout`, `render`, `publish`, `publish-dir`, and `upload-image`. `publish` will accept `--draft` and `--dry-run`; `publish-dir` will default to the extension's one-minute delay and allow an explicit override. The command's output and exit status will distinguish success, skipped files, and failures.

For authenticated commands, `ZHIHU_COOKIE` overrides the cookie saved by `login`. `login` accepts a cookie from an explicit stdin option or hidden interactive input, validates it with a read-only `/api/v4/me` request, and then persists it under the `platformdirs` user config directory. `logout` removes the saved cookie. On POSIX the credential file will be mode `0600`; on Windows it will stay under the current user's config directory. Secret values will never be printed, committed, or included in test fixtures. HTTP calls will use timeouts and explicit status/error handling; write requests will not be automatically retried.

Markdown rendering will preserve the README's supported CommonMark features, task lists, math, references, and Zhihu link cards. Relative image paths will resolve against the Markdown file's directory. Non-Zhihu images will be uploaded using the API-provided temporary OSS credentials; SVG remains unsupported. Hard-coded OSS credentials from the extension will not be copied.

## Safety and failures

`render` will only render locally, and `--dry-run` will not make any Zhihu or OSS requests; image references remain as supplied in dry-run HTML. API errors, invalid front matter or URLs, missing local images, rejected image uploads, and partial batch failures will produce actionable diagnostics and nonzero exit status where appropriate. A batch run will continue after an individual file fails and report a final summary. Tests will mock all network and OSS operations; verification will not create or publish a real Zhihu post.

## Verification

Unit tests will cover front matter and URL routing, title derivation and URL write-back, Markdown conversion against the existing fixture, cookie parsing without exposing values, image URL rewriting, and publish API request construction. CLI tests will cover dry-run output and batch summaries using mocked clients. The README will document installation, cookie setup, front matter, command examples, and supported Markdown behavior.

## Known compatibility risk

Zhihu's undocumented endpoints and Markdown sanitization can change independently of this repository. API integration will follow the current service implementation, but successful live publishing cannot be established safely by automated tests; only read-only authenticated account validation may use the supplied test cookie.
