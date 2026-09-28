"""Unified-diff parser — turns `git diff` text into structured hunks."""
import re


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
