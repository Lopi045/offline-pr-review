"""Offline GitHub PR review — local web app.

Reuses the `gh` CLI you're already logged into. No token handling, no DB.
Reviews are saved as JSON files in ./reviews/ so you can review with no internet
and publish later with one button.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import markdown
from flask import Flask, request, redirect, url_for, render_template_string, jsonify
from markupsafe import Markup

app = Flask(__name__)

_MD = markdown.Markdown(extensions=["fenced_code", "tables", "nl2br", "sane_lists"])


def render_md(text):
    """Render Markdown to HTML, then strip script/on*=/javascript: so a
    malicious PR body can't run JS against this local app. ponytail: regex
    scrub, not a full sanitizer — swap for bleach if you review hostile repos.
    """
    if not text:
        return ""
    _MD.reset()
    html = _MD.convert(text)
    html = re.sub(r"(?is)<script.*?</script>", "", html)
    html = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html)
    html = re.sub(r"(?i)javascript:", "", html)
    return Markup(html)


app.jinja_env.filters["md"] = render_md


def text_on(hexcolor):
    """Black or white text for a given bg hex, by perceived luminance."""
    try:
        r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
        return "#000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#fff"
    except (ValueError, IndexError):
        return "#000"


app.jinja_env.filters["texton"] = text_on
REVIEWS = Path(__file__).parent / "reviews"
REVIEWS.mkdir(exist_ok=True)


def gh(args, cwd=None, check=True):
    """Run a gh command, return stdout. Raises with stderr on failure."""
    r = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True,
                        encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"gh {' '.join(args)} failed")
    return r.stdout


def key_of(repo, number):
    return f"{repo.replace('/', '__')}__{number}"


def load(key):
    return json.loads((REVIEWS / f"{key}.json").read_text(encoding="utf-8"))


def save(key, data):
    (REVIEWS / f"{key}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


PATHS = REVIEWS / "_paths.json"  # {repo: local project path}, so you type it once


def get_path(repo):
    if PATHS.exists():
        return json.loads(PATHS.read_text(encoding="utf-8")).get(repo, "")
    return ""


def set_path(repo, path):
    d = json.loads(PATHS.read_text(encoding="utf-8")) if PATHS.exists() else {}
    d[repo] = path
    PATHS.write_text(json.dumps(d, indent=2), encoding="utf-8")


def parse_diff(text):
    """Unified diff -> [{path, hunks:[{header, lines:[{type,old,new,text}]}]}].

    type: 'ctx' | 'add' | 'del'. old/new are the line numbers (None when N/A).
    GitHub inline comments use the RIGHT-side (new) line for add/ctx, LEFT (old)
    for del.
    """
    files, cur = [], None
    old_n = new_n = 0
    for line in text.splitlines():
        if line.startswith("diff --git"):
            cur = None
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            path = path[2:] if path.startswith("b/") else path
            cur = {"path": path, "hunks": []}
            files.append(cur)
            continue
        if line.startswith("--- ") or line.startswith("index ") or \
           line.startswith("new file") or line.startswith("deleted file") or \
           line.startswith("similarity") or line.startswith("rename ") or \
           line.startswith("old mode") or line.startswith("new mode"):
            continue
        if line.startswith("@@"):
            m = re.search(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m and cur is not None:
                old_n, new_n = int(m.group(1)), int(m.group(2))
                cur["hunks"].append({"header": line, "lines": []})
            continue
        if cur is None or not cur["hunks"]:
            continue
        hunk = cur["hunks"][-1]
        if line.startswith("+"):
            hunk["lines"].append({"type": "add", "old": None, "new": new_n, "text": line[1:]})
            new_n += 1
        elif line.startswith("-"):
            hunk["lines"].append({"type": "del", "old": old_n, "new": None, "text": line[1:]})
            old_n += 1
        elif line.startswith("\\"):  # \ No newline at end of file
            continue
        else:
            hunk["lines"].append({"type": "ctx", "old": old_n, "new": new_n, "text": line[1:]})
            old_n += 1
            new_n += 1
    return files


# ---------------------------------------------------------------- routes

@app.route("/")
def home():
    try:
        # /user/repos with all affiliations = owned + collaborator + org repos.
        # --paginate walks every page; jq flattens to the two fields we render.
        raw = gh(["api", "--paginate",
                  "/user/repos?affiliation=owner,collaborator,organization_member&per_page=100",
                  "--jq", ".[] | {nameWithOwner: .full_name, description: .description}"])
        repos = [json.loads(l) for l in raw.splitlines() if l.strip()]
        repos.sort(key=lambda r: r["nameWithOwner"].lower())
    except Exception as e:
        repos = []
        app.logger.warning("repo list failed: %s", e)
    drafts = []
    for f in sorted(REVIEWS.glob("*.json")):
        if f.name.startswith("_"):  # _paths.json etc, not a review
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        drafts.append({"key": f.stem, "repo": d["repo"], "number": d["number"],
                       "title": d["title"], "published": d.get("published", False)})
    return render_template_string(HOME, repos=repos, drafts=drafts)


@app.route("/pulls")
def pulls():
    repo = request.args.get("repo", "").strip()
    if not repo:
        return redirect(url_for("home"))
    try:
        raw = gh(["pr", "list", "--repo", repo, "--state", "open", "--limit", "100",
                  "--json", "number,title,author,headRefName,updatedAt"])
        prs = json.loads(raw)
        err = None
    except Exception as e:
        prs, err = [], str(e)
    return render_template_string(PULLS, repo=repo, prs=prs, err=err, path=get_path(repo))


def download_one(repo, number, path):
    meta = json.loads(gh(["pr", "view", number, "--repo", repo, "--json",
                          "title,body,author,headRefName,baseRefName,url,comments,labels"]))
    diff = gh(["pr", "diff", number, "--repo", repo])

    # existing inline review comments (read-only, shown in the diff, never re-uploaded)
    existing = []
    try:
        raw = gh(["api", "--paginate", f"/repos/{repo}/pulls/{number}/comments?per_page=100",
                  "--jq", ".[] | {path, line, original_line, side, body, author: .user.login}"])
        for l in raw.splitlines():
            if not l.strip():
                continue
            c = json.loads(l)
            line = c.get("line") or c.get("original_line")
            if line:
                existing.append({"path": c["path"], "line": line,
                                 "side": c.get("side") or "RIGHT",
                                 "body": c["body"], "author": c["author"]})
    except Exception as e:
        app.logger.warning("inline comments fetch failed: %s", e)
    checkout_msg = ""
    if path:
        try:
            gh(["pr", "checkout", number, "--repo", repo], cwd=path)
            checkout_msg = f"Checked out branch in {path}"
        except Exception as e:
            checkout_msg = f"Checkout failed: {e}"
    key = key_of(repo, number)
    save(key, {
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


@app.route("/download", methods=["POST"])
def download():
    repo = request.form["repo"].strip()
    numbers = request.form.getlist("number")  # checkboxes
    path = request.form.get("path", "").strip()
    if path:
        set_path(repo, path)
    keys = [download_one(repo, n, path) for n in numbers]
    # one PR -> straight into its review; several -> back home to the saved list
    return redirect(url_for("review", key=keys[0]) if len(keys) == 1 else url_for("home"))


@app.route("/review/<key>")
def review(key):
    data = load(key)
    files = parse_diff(data["diff"])
    return render_template_string(REVIEW, d=data, files=files, key=key)


@app.route("/save/<key>", methods=["POST"])
def save_review(key):
    data = load(key)
    body = request.get_json()
    data["review_body"] = body.get("review_body", "")
    data["event"] = body.get("event", "COMMENT")
    data["comments"] = body.get("comments", [])
    data["pr_comment"] = body.get("pr_comment", "")
    save(key, data)
    return jsonify(ok=True)


def do_publish(data):
    """Push the draft review (+ optional PR comment) to GitHub. Mutates data,
    returns (ok, error). Caller saves. No-op-safe: empty draft still submits a
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


@app.route("/publish/<key>", methods=["POST"])
def publish(key):
    data = load(key)
    ok, err = do_publish(data)
    save(key, data)
    if not ok:
        return jsonify(ok=False, error=err), 400
    # refresh so the draft clears and the just-published comments come back as
    # existing (read-only) ones — this is what stops a later Update re-publishing
    try:
        download_one(data["repo"], str(data["number"]), data.get("path", ""))
        d2 = load(key)
        d2["published"] = True
        save(key, d2)
    except Exception as e:
        return jsonify(ok=False, error=f"Published, but refresh failed: {e}"), 400
    return jsonify(ok=True)


@app.route("/update/<key>", methods=["POST"])
def update(key):
    """Sync: publish the local draft (if any), then re-download the latest PR
    state (diff, comments, labels). Re-download resets the draft, so publishing
    first is what pushes your work up."""
    data = load(key)
    has_draft = (data.get("review_body", "").strip() or data.get("comments")
                 or data.get("pr_comment", "").strip())
    if has_draft:
        ok, err = do_publish(data)
        save(key, data)
        if not ok:
            return jsonify(ok=False, error=err), 400
    try:
        download_one(data["repo"], str(data["number"]), data.get("path", ""))
    except Exception as e:
        return jsonify(ok=False, error=f"Published, but refresh failed: {e}"), 400
    return jsonify(ok=True)


# ---------------------------------------------------------------- templates

BASE_CSS = """
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 :root{--bg:#f6f8fa;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--accent:#0969da;
       --green:#1f883d;--card:#fff;--radius:10px}
 *{box-sizing:border-box}
 body{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      max-width:1080px;margin:0 auto;padding:1.5rem 1rem 5rem;color:var(--fg);background:var(--bg)}
 a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
 h1{font-size:1.5rem;margin:.2rem 0} h3{margin:1.5rem 0 .5rem}
 .crumb{font-size:.9rem;color:var(--muted);margin-bottom:1rem}
 .card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
       padding:.9rem 1.1rem;margin:.6rem 0}
 .card.hover:hover{border-color:var(--accent);box-shadow:0 1px 6px rgba(0,0,0,.06)}
 input,select,textarea,button{font:inherit}
 input[type=text],input:not([type]),textarea,select{border:1px solid var(--line);
       border-radius:8px;padding:.45rem .6rem;background:#fff}
 textarea{width:100%;resize:vertical;font-family:inherit}
 button{cursor:pointer;background:var(--green);color:#fff;border:0;border-radius:8px;
        padding:.5rem 1rem;font-weight:600}
 button:hover{filter:brightness(1.05)} button.sec{background:#fff;color:var(--fg);border:1px solid var(--line)}
 button.sec:hover{background:var(--bg)}
 .muted{color:var(--muted)}
 .pill{font-size:.72rem;font-weight:600;padding:.15rem .55rem;border-radius:20px;
       background:#dafbe1;color:#1a7f37;vertical-align:middle}
 .num{font-family:ui-monospace,monospace;color:var(--muted)}
 /* rendered markdown */
 .md{overflow-wrap:anywhere} .md>*:first-child{margin-top:0} .md>*:last-child{margin-bottom:0}
 .md h1,.md h2{border-bottom:1px solid var(--line);padding-bottom:.3rem}
 .md code{background:rgba(129,139,152,.15);padding:.15em .4em;border-radius:6px;
          font:.85em ui-monospace,monospace}
 .md pre{background:#f6f8fa;border:1px solid var(--line);border-radius:8px;padding:.8rem;overflow:auto}
 .md pre code{background:none;padding:0}
 .md blockquote{margin:0;padding:0 1rem;color:var(--muted);border-left:3px solid var(--line)}
 .md table{border-collapse:collapse} .md td,.md th{border:1px solid var(--line);padding:.3rem .6rem}
 .md img{max-width:100%}
 /* diff */
 .file{margin-top:1.2rem;border:1px solid var(--line);border-radius:var(--radius);overflow:hidden}
 .fname{font:600 .82rem ui-monospace,monospace;background:#f6f8fa;padding:.55rem .8rem;
        border-bottom:1px solid var(--line)}
 table.diff{border-collapse:collapse;width:100%;font:12.5px/1.5 ui-monospace,Consolas,monospace}
 table.diff td{padding:0 .5rem;white-space:pre-wrap;vertical-align:top}
 td.ln{color:#8c959f;text-align:right;user-select:none;width:1%;background:#f6f8fa;
       border-right:1px solid var(--line)}
 tr.add td.code{background:#e6ffec} tr.del td.code{background:#ffebe9}
 td.code.add{background:#e6ffec} td.code.del{background:#ffebe9}
 tr.hunk td{background:#ddf4ff;color:#4269a8;border-top:1px dashed #9cc4ff;
            border-bottom:1px dashed #9cc4ff;font-weight:600}
 tr.hunk td.code::before{content:"⋮ skipped lines  ";opacity:.7}
 tr.hunk+tr td{border-top:0}
 td.addbtn{width:1%;color:#fff;cursor:pointer;user-select:none;text-align:center}
 tr:hover td.addbtn{color:var(--accent)}
 /* split view: two code columns */
 td.code.sel,td.gutter.sel{outline:2px solid var(--accent);outline-offset:-2px}
 table.split td.code{border-left:1px solid var(--line)}
 table.split td.empty{background:#f6f8fa}
 .viewtoggle{margin:.5rem 0}
 .viewtoggle button{padding:.3rem .8rem;font-weight:500}
 .viewtoggle button.on{background:var(--accent);color:#fff;border-color:var(--accent)}
 .cbox{background:#fff8c5;padding:.5rem;border-radius:8px;margin:.3rem 0}
 .cbox textarea{height:3.5rem;background:#fff}
 .ebox{background:#eef3fb;border:1px solid #cdd9ec;padding:.5rem;border-radius:8px;margin:.3rem 0}
 .ebox .who{font-weight:600;font-size:.85rem;color:#4269a8}
 /* sticky review bar */
 .bar{position:sticky;bottom:0;background:var(--card);border:1px solid var(--line);
      border-radius:var(--radius);padding:.75rem 1rem;margin-top:1rem;
      box-shadow:0 -2px 12px rgba(0,0,0,.06);display:flex;gap:.6rem;align-items:center;flex-wrap:wrap}
 .disc{border-left:3px solid var(--line);padding-left:.9rem;margin:.5rem 0}
 .disc .who{font-weight:600;font-size:.9rem}
 code.branch{background:#ddf4ff;color:#0969da;padding:.15em .5em;border-radius:6px;
             cursor:pointer;font:.85em ui-monospace,monospace;font-weight:600}
 code.branch:hover{background:#b6e3ff}
 .label{display:inline-block;font-size:.75rem;font-weight:600;padding:.15rem .6rem;
        border-radius:20px;margin:.15rem .3rem .15rem 0}
</style>
"""

HOME = BASE_CSS + """
<h1>📥 Offline PR Review</h1>
<div class="card">
 <form action="/pulls" method="get" style="display:flex;gap:.6rem;flex-wrap:wrap">
  <input name="repo" placeholder="owner/name — jump to any repo" size="35" required style="flex:1">
  <button type="submit">List open PRs</button>
 </form>
</div>
{% if drafts %}<h3>Saved reviews <span class="muted">(available offline)</span></h3>
 {% for d in drafts %}<div class="card hover" style="display:flex;justify-content:space-between;align-items:center;gap:1rem">
   <div>
    <a href="/review/{{d.key}}"><b>#{{d.number}}</b> {{d.title}}</a>
    {% if d.published %}<span class="pill">published</span>{% endif %}
    <div class="muted num">{{d.repo}}</div>
   </div>
   <button class="sec" onclick="sync('{{d.key}}',this)" title="publish draft + re-download latest">⟳ Update</button>
 </div>{% endfor %}
 <script>
 async function sync(key,btn){
  if(!confirm('Publish saved draft (if any) and re-download latest PR state?'))return;
  const t=btn.textContent; btn.textContent='syncing…'; btn.disabled=true;
  const j=await (await fetch('/update/'+key,{method:'POST'})).json();
  if(j.ok){location.reload();} else {btn.textContent=t;btn.disabled=false;alert('❌ '+j.error);}
 }
 </script>
{% endif %}
<h3>Your repos</h3>
{% for r in repos %}<div class="card hover">
  <a href="/pulls?repo={{r.nameWithOwner}}"><b>{{r.nameWithOwner}}</b></a>
  {% if r.description %}<div class="muted">{{r.description}}</div>{% endif %}
</div>{% else %}<p class="muted">No repos listed (or gh not authed). Use the box above.</p>{% endfor %}
"""

PULLS = BASE_CSS + """
<div class="crumb"><a href="/">home</a> / {{repo}}</div>
<h1>Open PRs</h1>
{% if err %}<div class="card" style="border-color:#cf222e">Error: {{err}}</div>{% endif %}
{% if prs %}
<form action="/download" method="post">
 <input type="hidden" name="repo" value="{{repo}}">
 <div class="card">
  Local project path (branches get checked out here, optional):
  <input name="path" value="{{path}}" placeholder="C:\\path\\to\\repo" size="45">
  <div style="margin-top:.5rem">
   <button type="submit">Download selected for offline review</button>
   <a href="#" class="muted" onclick="toggleAll(event)">select all / none</a>
  </div>
 </div>
 {% for p in prs %}<div class="card">
  <label style="display:flex;gap:.5rem;align-items:baseline">
   <input type="checkbox" name="number" value="{{p.number}}">
   <span><b>#{{p.number}}</b> {{p.title}}
    <span class="muted">by {{p.author.login}} · {{p.headRefName}}</span></span>
  </label>
 </div>{% endfor %}
</form>
<script>
function toggleAll(e){e.preventDefault();
 const b=document.querySelectorAll('input[name=number]');
 const on=![...b].every(c=>c.checked); b.forEach(c=>c.checked=on);}
</script>
{% else %}<p class="muted">No open PRs (or repo not found).</p>{% endif %}
"""

REVIEW = BASE_CSS + """
<div class="crumb"><a href="/">home</a> / {{d.repo}} /
 <a href="{{d.url}}" target="_blank">#{{d.number}} on GitHub ↗</a></div>
<h1>{{d.title}} <span class="num">#{{d.number}}</span>
 {% if d.published %}<span class="pill">published</span>{% endif %}</h1>
<p class="muted"><b>{{d.author}}</b> wants to merge
 <code class="branch" title="click to copy branch name"
       onclick="copyBranch(this)">{{d.head}}</code> → <span class="num">{{d.base}}</span></p>
{% if d.labels %}<div style="margin:.3rem 0 .6rem">
 {% for l in d.labels %}<span class="label"
   style="background:#{{l.color}};color:{{l.color|texton}}">{{l.name}}</span>{% endfor %}
</div>{% endif %}
{% if d.checkout_msg %}<div class="card muted">🌿 {{d.checkout_msg}}</div>{% endif %}
{% if d.body %}<div class="card md">{{ d.body|md }}</div>{% endif %}

{% if d.discussion %}<h3>Discussion</h3>
 {% for c in d.discussion %}<div class="card">
  <div class="disc"><div class="who">{{c.author}}</div>
   <div class="md">{{ c.body|md }}</div></div>
 </div>{% endfor %}
{% endif %}

<h3>Files changed <span class="muted">({{files|length}})</span></h3>
<div class="viewtoggle">
 <button id="btn-unified" class="sec" onclick="setView('unified')">Unified</button>
 <button id="btn-split" class="sec" onclick="setView('split')">Split</button>
 <span class="muted" style="margin-left:.5rem">tip: click a line number to comment; click a
  second number in the same file &amp; side to make it a range.</span>
</div>
<div id="diff"></div>

<h3>Comment on the PR <span class="muted">(conversation, optional)</span></h3>
<div class="card">
 <textarea id="pr_comment" rows="3" placeholder="A general comment on the PR…">{{d.pr_comment or ''}}</textarea>
</div>

<div class="bar">
 <select id="event">
  {% for e,label in [('COMMENT','💬 Comment'),('APPROVE','✅ Approve'),('REQUEST_CHANGES','🔴 Request changes')] %}
  <option value="{{e}}" {{'selected' if d.event==e}}>{{label}}</option>{% endfor %}
 </select>
 <input id="review_body" placeholder="Overall review summary…" style="flex:1;min-width:200px"
        value="{{d.review_body}}">
 <button class="sec" onclick="saveDraft()">Save draft</button>
 <button onclick="publish()">Publish to GitHub</button>
 <button class="sec" onclick="syncPR()" title="publish draft, then re-download latest PR state">⟳ Update</button>
 <span id="status" class="muted"></span>
</div>

<script>
const KEY = {{ key|tojson }};
const FILES = {{ files|tojson }};
const EXISTING = {{ d.existing_comments|tojson if d.existing_comments else '[]' }};
let comments = {{ d.comments|tojson }};
let view = localStorage.getItem('prview') || 'unified';
let pending = null;  // {path, side, line} first click of a potential range

const esc = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

function copyBranch(el){
 navigator.clipboard.writeText(el.textContent).then(()=>{
  const old=el.textContent; el.textContent='✓ copied';
  setTimeout(()=>{el.textContent=old;},900);
 });
}

function prefix(t){return t==='add'?'+':t==='del'?'-':' ';}

function renderDiff(){
 const out = FILES.map(f=>{
  const rows = f.hunks.map(h=>{
   const hd = view==='split'
     ? `<tr class="hunk"><td class="ln"></td><td class="code">${esc(h.header)}</td>`+
       `<td class="ln"></td><td class="code"></td></tr>`
     : `<tr class="hunk"><td class="ln"></td><td class="ln"></td><td class="code">${esc(h.header)}</td></tr>`;
   return hd + (view==='split' ? splitLines(f.path,h.lines) : unifiedLines(f.path,h.lines));
  }).join('');
  const cls = view==='split' ? 'diff split' : 'diff';
  return `<div class="file"><div class="fname">${esc(f.path)}</div>
    <table class="${cls}"><tbody>${rows}</tbody></table></div>`;
 }).join('');
 document.getElementById('diff').innerHTML = out;
 bindGutters();
 renderComments();
}

function unifiedLines(path,lines){
 return lines.map(l=>{
  const side = l.type==='del' ? 'LEFT' : 'RIGHT';
  const line = l.type==='del' ? l.old : l.new;
  return `<tr class="${l.type}">
    <td class="ln gut" data-path="${esc(path)}" data-line="${line}" data-side="${side}">${l.old||''}</td>
    <td class="ln gut" data-path="${esc(path)}" data-line="${line}" data-side="${side}">${l.new||''}</td>
    <td class="code">${esc(prefix(l.type)+l.text)}</td></tr>`;
 }).join('');
}

function splitLines(path,lines){
 // pair del/add runs; context aligns on both sides
 const rows=[]; let i=0;
 const cell=(side,num,txt,type)=> num==null
   ? `<td class="ln"></td><td class="code empty"></td>`
   : `<td class="ln gut" data-path="${esc(path)}" data-line="${num}" data-side="${side}">${num}</td>`+
     `<td class="code ${type}">${esc((type==='del'?'-':type==='add'?'+':' ')+txt)}</td>`;
 while(i<lines.length){
  const l=lines[i];
  if(l.type==='ctx'){
   rows.push(`<tr>${cell('LEFT',l.old,l.text,'ctx')}${cell('RIGHT',l.new,l.text,'ctx')}</tr>`); i++;
  } else {
   const dels=[],adds=[];
   while(i<lines.length&&lines[i].type==='del') dels.push(lines[i++]);
   while(i<lines.length&&lines[i].type==='add') adds.push(lines[i++]);
   const n=Math.max(dels.length,adds.length);
   for(let k=0;k<n;k++){
    const d=dels[k], a=adds[k];
    rows.push(`<tr>${d?cell('LEFT',d.old,d.text,'del'):cell('LEFT',null)}`+
              `${a?cell('RIGHT',a.new,a.text,'add'):cell('RIGHT',null)}</tr>`);
   }
  }
 }
 return rows.join('');
}

function bindGutters(){
 document.querySelectorAll('td.gut').forEach(td=>{
  td.style.cursor='pointer'; td.title='click to comment / range';
  td.onclick=()=>onGutter(td);
 });
}

function onGutter(td){
 const path=td.dataset.path, side=td.dataset.side, line=parseInt(td.dataset.line);
 // second click in same file & side extends the pending comment into a range
 if(pending && pending.path===path && pending.side===side && line!==pending.anchor){
  const c=comments[pending.idx];
  c.start_line=Math.min(pending.anchor,line); c.line=Math.max(pending.anchor,line);
  pending=null; clearSel(); renderComments(); return;
 }
 // first click: drop a single-line comment box and arm it for a range
 comments.push({path,side,line,start_line:line,body:''});
 pending={path,side,anchor:line,idx:comments.length-1};
 renderComments(); markPending(td);
}
function markPending(td){clearSel(); td.classList.add('sel');}
function clearSel(){document.querySelectorAll('.sel').forEach(e=>e.classList.remove('sel'));}

function renderComments(){
 document.querySelectorAll('tr.cbox-row').forEach(e=>e.remove());
 const cols = view==='split' ? 4 : 3;
 // existing (read-only) comments already on GitHub
 EXISTING.forEach(c=>{
  const sel=`td.gut[data-path="${CSS.escape(c.path)}"][data-line="${c.line}"][data-side="${c.side}"]`;
  const td=document.querySelector(sel); if(!td) return;
  const nr=document.createElement('tr'); nr.className='cbox-row';
  nr.innerHTML=`<td colspan="${cols}"><div class="ebox">
    <div class="who">${esc(c.author)}</div>${esc(c.body).replace(/\\n/g,'<br>')}</div></td>`;
  td.closest('tr').after(nr);
 });
 comments.forEach((c,i)=>{
  const sel=`td.gut[data-path="${CSS.escape(c.path)}"][data-line="${c.line}"][data-side="${c.side}"]`;
  const td=document.querySelector(sel); if(!td) return;
  const range = c.start_line && c.start_line<c.line ? `lines ${c.start_line}–${c.line}` : `line ${c.line}`;
  const nr=document.createElement('tr'); nr.className='cbox-row';
  nr.innerHTML=`<td colspan="${cols}"><div class="cbox">
    <div class="muted" style="font-size:.8rem">${esc(c.path)} · ${range} · ${c.side}</div>
    <textarea>${esc(c.body)}</textarea>
    <button class="sec" onclick="delComment(${i})">delete</button></div></td>`;
  nr.querySelector('textarea').addEventListener('input',e=>{comments[i].body=e.target.value;});
  td.closest('tr').after(nr);
 });
}
function delComment(i){comments.splice(i,1); pending=null; clearSel(); renderComments();}

function setView(v){
 view=v; localStorage.setItem('prview',v);
 document.getElementById('btn-unified').classList.toggle('on',v==='unified');
 document.getElementById('btn-split').classList.toggle('on',v==='split');
 pending=null; renderDiff();
}

async function post(url){
 const payload={review_body:document.getElementById('review_body').value,
   event:document.getElementById('event').value,
   pr_comment:document.getElementById('pr_comment').value,
   comments:comments.filter(c=>c.body.trim())};
 return fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify(payload)});
}
async function saveDraft(){
 await post('/save/'+KEY);
 document.getElementById('status').textContent='saved '+new Date().toLocaleTimeString();
}
async function publish(){
 if(!confirm('Publish review to GitHub now? Your draft will be pushed and then '+
             'reloaded as read-only comments.'))return;
 await saveDraft();
 document.getElementById('status').textContent='publishing…';
 const j=await (await post('/publish/'+KEY)).json();
 if(j.ok){location.reload();} else {document.getElementById('status').textContent='❌ '+j.error;}
}
async function syncPR(){
 if(!confirm('Publish your saved draft (if any) and re-download the latest PR state?\\n'+
             'Note: refreshing resets the local draft.'))return;
 await saveDraft();
 document.getElementById('status').textContent='syncing…';
 const j=await (await fetch('/update/'+KEY,{method:'POST'})).json();
 if(j.ok){location.reload();} else {document.getElementById('status').textContent='❌ '+j.error;}
}
setView(view);
</script>
"""

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"Offline PR Review -> http://127.0.0.1:{port}")
    app.run(port=port, debug=True)
