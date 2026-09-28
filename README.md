# Offline PR Review

A tiny local web app to review GitHub pull requests **offline**: download open PRs,
read the diff, write inline + range comments and a verdict with no internet, then
publish the whole review in one click when you're back online.

Auth is delegated entirely to the [GitHub CLI](https://cli.github.com/) (`gh`) —
this app stores **no tokens**. Reviews are saved as plain JSON in `reviews/`.

## Requirements

- Python 3.9+
- [`gh`](https://cli.github.com/) installed and logged in: `gh auth login`

## Setup

```bash
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
python app.py 8731       # use another port if 5000 is taken
```

## Project layout

```
app.py                 entry point (creates the app, runs the dev server)
prreview/              application package
  __init__.py          app factory: create_app()
  routes.py            HTTP routes (Flask blueprint)
  github.py            all gh-CLI calls: list repos/PRs, download, publish
  storage.py           reviews + remembered paths, as JSON on disk
  diff.py              unified-diff parser
  render.py            Jinja filters: Markdown (sanitized) + label contrast
templates/             Jinja HTML (base + home/pulls/review)
static/                style.css, home.js, pulls.js, review.js
reviews/               downloaded PRs + drafts (gitignored)
```

## Usage

1. **Home** — lists repos you can access (owned + collaborator + org). Or type `owner/name`.
2. **PR list** — tick the PRs you want, optionally set the local project path once
   (branches get checked out there via `gh pr checkout`), then **Download selected**.
3. **Review** (works offline) — unified/split diff toggle, PR body & discussion rendered
   as Markdown, labels, existing inline comments shown read-only. Click a line number to
   comment; click a second number in the same file & side to make it a range. Add a
   general PR comment too.
4. **Save draft** — stores your review locally.
5. **Publish** — uploads this PR's review (verdict + inline comments + PR comment) to
   GitHub, then reloads it as read-only.
6. **Update** — publishes any draft, then re-downloads the latest PR state.

## Notes

- `reviews/` (downloaded PR data + your local project paths in `_paths.json`) is
  gitignored — nothing personal is committed.
- Markdown from PRs is sanitized (`<script>`, `on*=`, `javascript:` stripped) before render.
- Split view pairs deletions/additions line-by-line (no intraline highlighting).
