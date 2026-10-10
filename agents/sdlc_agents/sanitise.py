"""
Untrusted text in, safe text out.

- Input side: issue, PR, diff and log text is wrapped in tags carrying a fresh random nonce, so the
  model can tell data from instructions and the data cannot forge the closing tag.
- Output side: model JSON is parsed strictly (duplicate keys and NaN rejected); model markdown is
  defanged before it is posted to GitHub (images, raw HTML, @mentions, closing keywords).
- Markers: JSON embedded in an HTML comment has every '<', '>' and '&' escaped, so text inside
  it can never close the comment.

Stdlib only.
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

HEAD_LIMIT = 2_000        # chars kept from a log head (failures sit at the tail)
TAIL_LIMIT = 58_000       # chars kept from a log tail
INPUT_CHAR_LIMIT = HEAD_LIMIT + TAIL_LIMIT


# ---------------------------------------------------------------------------
# Strict JSON
# ---------------------------------------------------------------------------

def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate JSON key: {key!r}")
        seen[key] = value
    return seen


def _bad_constant(name: str) -> None:
    raise ValueError(f"JSON constant not allowed: {name}")


def parse_json_strict(text: str) -> Any:
    """Parse JSON rejecting duplicate keys and the NaN/Infinity constants."""
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_bad_constant)


def encode_marker_json(value: Any) -> str:
    """Compact JSON that is safe inside an HTML comment (no '<', '>' or '&' characters)."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


# ---------------------------------------------------------------------------
# Input wrapping
# ---------------------------------------------------------------------------

def new_nonce() -> str:
    return secrets.token_hex(8)


def wrap_untrusted(name: str, text: str, nonce: str, *, keep_tail: bool = False) -> str:
    """
    Wrap one untrusted section. Over-long text keeps its head, or for logs (keep_tail) a short
    head plus the long tail, with a truncation note that carries the nonce so it cannot be forged.
    """
    if len(text) > INPUT_CHAR_LIMIT:
        if keep_tail:
            text = (
                text[:HEAD_LIMIT]
                + f"\n\n[LOG TRUNCATED nonce={nonce}: first {HEAD_LIMIT} and last {TAIL_LIMIT} chars]\n\n"
                + text[-TAIL_LIMIT:]
            )
        else:
            text = text[:INPUT_CHAR_LIMIT] + f"\n\n[INPUT TRUNCATED AT {INPUT_CHAR_LIMIT} CHARS nonce={nonce}]"
    return f"<untrusted_input nonce={nonce} name={name}>\n{text}\n</untrusted_input nonce={nonce}>"


# ---------------------------------------------------------------------------
# Markdown output sanitisation
# ---------------------------------------------------------------------------

# Regex cannot reliably tell where a renderer sees code, so the sanitiser never trusts code
# spans or fences: HTML-ish markup is stripped everywhere, and any '<' left over is escaped.
# Comments and CDATA that never close run to end of text, the way a renderer swallows the rest.
# Images cover inline and reference style (![alt][ref] / ![alt]): both can beacon when rendered.
_MARKUP_RE = re.compile(
    r"(?P<comment><!--.*?(?:-->|\Z))"
    r"|(?P<cdata><!\[CDATA\[.*?(?:\]\]>|\Z))"
    r"|(?P<tag><[A-Za-z/!?][^>]{0,200}>)"
    r"|(?P<image>!\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\])?)",
    re.DOTALL,
)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)|\[([^\]]*)\]\[[^\]]*\]")
_MENTION_RE = re.compile(r"(?<!\w)@([\w/-]+)")
# GitHub closing keywords (close/fix/resolve + s/d forms) followed by #N, owner/repo#N, GH-N or a URL.
_FIXES_RE = re.compile(
    r"\b((?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+(?:https?://\S+|[\w./-]*#\d+|GH-\d+))",
    re.IGNORECASE,
)


def _strip_markup(match: re.Match[str]) -> str:
    return "[image removed]" if match.group("image") else ""


def sanitise_markdown(text: str) -> str:
    """
    Strip or neutralise markdown images, links, raw HTML, @mentions and closing keywords in model output
    before it is posted to GitHub. Every remaining '<' is escaped, so generics in code show as '&lt;'.
    """
    # Strip to a fixed point: removing one construct can splice the pieces of another together
    # (e.g. "!<b>[a](http://x)" becomes an image once the tag is gone).
    for _ in range(8):
        stripped = _MARKUP_RE.sub(_strip_markup, text)
        if stripped == text:
            break
        text = stripped
    # Links keep their text and lose their target: model output never points readers elsewhere.
    text = _LINK_RE.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), text)
    text = text.replace("<", "&lt;")
    text = _MENTION_RE.sub(r"`@\1`", text)
    # Backticks put the keyword in a code span, where GitHub does not parse closing keywords.
    return _FIXES_RE.sub(lambda m: f"`{m.group(1)}` [keyword defanged]", text)


def one_line(text: str, limit: int = 300) -> str:
    """Collapse whitespace and cap length, for short model text shown in summaries."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."
