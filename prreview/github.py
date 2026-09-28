"""Everything that talks to GitHub — all via the `gh` CLI, so no tokens here."""
import json
import logging
import subprocess

from . import storage

log = logging.getLogger(__name__)


def gh(args, cwd=None, check=True):
    """Run a gh command, return stdout. Raises with stderr on failure."""
    r = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"gh {' '.join(args)} failed")
    return r.stdout


def list_repos():
    """Every repo you can access: owned + collaborator + org member."""
    raw = gh(["api", "--paginate",
              "/user/repos?affiliation=owner,collaborator,organization_member&per_page=100",
              "--jq", ".[] | {nameWithOwner: .full_name, description: .description}"])
    repos = [json.loads(l) for l in raw.splitlines() if l.strip()]
    repos.sort(key=lambda r: r["nameWithOwner"].lower())
    return repos


def list_prs(repo):
    raw = gh(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100",
              "--json", "number,title,author,headRefName,updatedAt"])
    return json.loads(raw)


def _existing_comments(repo, number):
    """Inline review comments already on GitHub (read-only, never re-uploaded)."""
    out = []
    try:
        raw = gh(["api", "--paginate", f"/repos/{repo}/pulls/{number}/comments?per_page=100",
                  "--jq", ".[] | {path, line, original_line, side, body, author: .user.login}"])
        for l in raw.splitlines():
            if not l.strip():
                continue
            c = json.loads(l)
            line = c.get("line") or c.get("original_line")
            if line:
                out.append({"path": c["path"], "line": line,
                            "side": c.get("side") or "RIGHT",
                            "body": c["body"], "author": c["author"]})
    except Exception as e:
        log.warning("inline comments fetch failed: %s", e)
    return out


def download_one(repo, number, path):
    """Fetch a PR's metadata + diff + comments and save it locally for offline
    review. Optionally checks out its branch in `path`. Returns the storage key."""
    meta = json.loads(gh(["pr", "view", number, "--repo", repo, "--json",
                          "title,body,author,headRefName,baseRefName,url,comments,labels"]))
    diff = gh(["pr", "diff", number, "--repo", repo])
    existing = _existing_comments(repo, number)

    checkout_msg = ""
    if path:
        try:
            gh(["pr", "checkout", number, "--repo", repo], cwd=path)
            checkout_msg = f"Checked out branch in {path}"
        except Exception as e:
            checkout_msg = f"Checkout failed: {e}"

    key = storage.key_of(repo, number)
    storage.save(key, {
        "repo": repo, "number": int(number), "title": meta["title"],
        "body": meta.get("body", ""), "author": meta["author"]["login"],
        "url": meta["url"], "head": meta["headRefName"], "base": meta["baseRefName"],
        "diff": diff, "path": path, "checkout_msg": checkout_msg,
        "discussion": [{"author": c["author"]["login"], "body": c["body"]}
                       for c in meta.get("comments", [])],
        "labels": [{"name": l["name"], "color": l["color"]}
                   for l in meta.get("labels", [])],
        "existing_comments": existing,
        "review_body": "", "event": "COMMENT", "comments": [],
        "published": False,
    })
    return key


def do_publish(data):
    """Push the draft review (+ optional PR comment) to GitHub. Mutates data,
    returns (ok, error). Caller saves. No-op-safe: an empty draft still submits a
    plain review, which is what Publish has always done."""
    payload = {"event": data["event"], "body": data["review_body"]}
    comments = []
    for c in data["comments"]:
        item = {"path": c["path"], "line": c["line"], "side": c["side"], "body": c["body"]}
        # multi-line range: start_line/start_side (GitHub requires start < line, same side)
        if c.get("start_line") and c["start_line"] < c["line"]:
            item["start_line"] = c["start_line"]
            item["start_side"] = c["side"]
        comments.append(item)
    if comments:
        payload["comments"] = comments
    endpoint = f"/repos/{data['repo']}/pulls/{data['number']}/reviews"
    # gh api reads --input '-' from stdin
    r = subprocess.run(["gh", "api", "--method", "POST", endpoint, "--input", "-"],
                       input=json.dumps(payload), capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0:
        return False, r.stderr.strip()

    # a general PR conversation comment, if drafted (guard against re-posting same text)
    pc = data.get("pr_comment", "").strip()
    if pc and data.get("pr_comment_posted") != pc:
        try:
            gh(["pr", "comment", str(data["number"]), "--repo", data["repo"], "--body", pc])
            data["pr_comment_posted"] = pc
        except Exception as e:
            data["published"] = True
            return False, f"Review published, but PR comment failed: {e}"

    data["published"] = True
    return True, None
