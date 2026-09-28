# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's
[**Report a vulnerability**](https://github.com/Lopi045/offline-pr-review/security/advisories/new)
button (Security tab) rather than opening a public issue.

## Scope & design notes

This is a **local, single-user** tool that runs on `127.0.0.1`:

- Authentication is delegated entirely to the GitHub CLI (`gh`). **No tokens are
  stored** by this app.
- Downloaded PR data and your local project paths live in `reviews/` and are
  never committed (gitignored).
- Markdown from PR bodies/comments is sanitized (`<script>`, `on*=` handlers, and
  `javascript:` URIs are stripped) before rendering, so a malicious PR can't run
  scripts in the local app.

Do not expose the dev server to untrusted networks — it is meant for localhost.
