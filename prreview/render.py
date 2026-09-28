"""Jinja filters: Markdown rendering (sanitized) and label-text contrast."""
import re

import markdown
from markupsafe import Markup

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


def text_on(hexcolor):
    """Black or white text for a given bg hex, by perceived luminance."""
    try:
        r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
        return "#000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#fff"
    except (ValueError, IndexError):
        return "#000"
