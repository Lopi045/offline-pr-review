"""HTTP routes — thin glue between the browser and the github/storage modules."""
import logging

from flask import (Blueprint, jsonify, redirect, render_template, request, url_for)

from . import github, storage
from .diff import parse_diff

log = logging.getLogger(__name__)
bp = Blueprint("bp", __name__)


@bp.route("/")
def home():
    try:
        repos = github.list_repos()
    except Exception as e:
        repos = []
        log.warning("repo list failed: %s", e)
    return render_template("home.html", repos=repos, drafts=storage.list_drafts())


@bp.route("/pulls")
def pulls():
    repo = request.args.get("repo", "").strip()
    if not repo:
        return redirect(url_for("bp.home"))
    try:
        prs, err = github.list_prs(repo), None
    except Exception as e:
        prs, err = [], str(e)
    return render_template("pulls.html", repo=repo, prs=prs, err=err,
                           path=storage.get_path(repo))


@bp.route("/download", methods=["POST"])
def download():
    repo = request.form["repo"].strip()
    numbers = request.form.getlist("number")  # checkboxes
    path = request.form.get("path", "").strip()
    if path:
        storage.set_path(repo, path)
    keys = [github.download_one(repo, n, path) for n in numbers]
    # one PR -> straight into its review; several -> back home to the saved list
    return redirect(url_for("bp.review", key=keys[0]) if len(keys) == 1
                    else url_for("bp.home"))


@bp.route("/review/<key>")
def review(key):
    data = storage.load(key)
    return render_template("review.html", d=data, files=parse_diff(data["diff"]), key=key)


@bp.route("/save/<key>", methods=["POST"])
def save_review(key):
    data = storage.load(key)
    body = request.get_json()
    data["review_body"] = body.get("review_body", "")
    data["event"] = body.get("event", "COMMENT")
    data["comments"] = body.get("comments", [])
    data["pr_comment"] = body.get("pr_comment", "")
    storage.save(key, data)
    return jsonify(ok=True)


@bp.route("/publish/<key>", methods=["POST"])
def publish(key):
    data = storage.load(key)
    ok, err = github.do_publish(data)
    storage.save(key, data)
    if not ok:
        return jsonify(ok=False, error=err), 400
    # refresh so the draft clears and the just-published comments come back as
    # existing (read-only) ones — this is what stops a later Update re-publishing
    try:
        github.download_one(data["repo"], str(data["number"]), data.get("path", ""))
        d2 = storage.load(key)
        d2["published"] = True
        storage.save(key, d2)
    except Exception as e:
        return jsonify(ok=False, error=f"Published, but refresh failed: {e}"), 400
    return jsonify(ok=True)


@bp.route("/update/<key>", methods=["POST"])
def update(key):
    """Sync: publish the local draft (if any), then re-download the latest PR
    state (diff, comments, labels). Re-download resets the draft, so publishing
    first is what pushes your work up."""
    data = storage.load(key)
    has_draft = (data.get("review_body", "").strip() or data.get("comments")
                 or data.get("pr_comment", "").strip())
    if has_draft:
        ok, err = github.do_publish(data)
        storage.save(key, data)
        if not ok:
            return jsonify(ok=False, error=err), 400
    try:
        github.download_one(data["repo"], str(data["number"]), data.get("path", ""))
    except Exception as e:
        return jsonify(ok=False, error=f"Published, but refresh failed: {e}"), 400
    return jsonify(ok=True)
