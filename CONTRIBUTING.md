# Contributing

Thanks for considering a contribution! `master` is protected, so all changes go
through a pull request.

## Setup

```bash
git clone https://github.com/Lopi045/offline-pr-review.git
cd offline-pr-review
pip install -r requirements.txt pytest
gh auth login          # the app uses your gh login; no tokens are stored
```

## Workflow

```bash
git checkout -b my-change
# ...make your changes...
python -m pytest -q            # run tests
python app.py 8731             # sanity-check in the browser
git commit -am "Describe the change"
git push -u origin my-change
gh pr create --fill
```

Open the PR against `master`. CI (byte-compile + tests + JS syntax check) and CodeQL
run automatically; only the repo owner can merge.

## Guidelines

- Match the surrounding code style and keep the diff focused on one thing.
- Never commit anything under `reviews/` (downloaded PRs, local paths) — it's gitignored.
- Prefer the standard library; don't add a dependency for what a few lines can do.
- Non-trivial logic (a parser, a branch, a money/security path) gets a small test in `tests/`.

## Reporting

- Bugs and ideas: open an [issue](https://github.com/Lopi045/offline-pr-review/issues).
- Security problems: use the private advisory flow described in [`SECURITY.md`](SECURITY.md).

By contributing, you agree your contributions are licensed under the project's
[AGPL-3.0](LICENSE).
