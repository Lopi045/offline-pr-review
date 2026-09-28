"""Self-check for the unified-diff parser. Run: `python -m pytest` or directly."""
from prreview.diff import parse_diff

SAMPLE = """diff --git a/foo.py b/foo.py
index 111..222 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 line one
-old line
+new line
+added line
 line three"""


def test_parse_diff():
    files = parse_diff(SAMPLE)
    assert len(files) == 1 and files[0]["path"] == "foo.py"
    lines = files[0]["hunks"][0]["lines"]
    assert lines[0] == {"type": "ctx", "old": 1, "new": 1, "text": "line one"}
    assert lines[1] == {"type": "del", "old": 2, "new": None, "text": "old line"}
    assert lines[2] == {"type": "add", "old": None, "new": 2, "text": "new line"}
    assert lines[3] == {"type": "add", "old": None, "new": 3, "text": "added line"}
    assert lines[4] == {"type": "ctx", "old": 3, "new": 4, "text": "line three"}


if __name__ == "__main__":
    test_parse_diff()
    print("ok")
