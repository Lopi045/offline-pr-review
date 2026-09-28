"""Local persistence: reviews and remembered project paths, as JSON on disk."""
import json
from pathlib import Path

REVIEWS = Path(__file__).resolve().parent.parent / "reviews"
PATHS = REVIEWS / "_paths.json"  # {repo: local project path}, so you type it once


def key_of(repo, number):
    return f"{repo.replace('/', '__')}__{number}"


def load(key):
    return json.loads((REVIEWS / f"{key}.json").read_text(encoding="utf-8"))


def save(key, data):
    (REVIEWS / f"{key}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_drafts():
    """Saved reviews for the home page (underscore files are not reviews)."""
    drafts = []
    for f in sorted(REVIEWS.glob("*.json")):
        if f.name.startswith("_"):
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        drafts.append({"key": f.stem, "repo": d["repo"], "number": d["number"],
                       "title": d["title"], "published": d.get("published", False)})
    return drafts


def get_path(repo):
    if PATHS.exists():
        return json.loads(PATHS.read_text(encoding="utf-8")).get(repo, "")
    return ""


def set_path(repo, path):
    d = json.loads(PATHS.read_text(encoding="utf-8")) if PATHS.exists() else {}
    d[repo] = path
    PATHS.write_text(json.dumps(d, indent=2), encoding="utf-8")
