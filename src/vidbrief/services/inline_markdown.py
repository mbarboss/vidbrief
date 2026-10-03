"""The inline Markdown subset summaries may use: bold, italics and code, nothing else.

Summaries are untrusted LLM output. Links, images, raw HTML and block structure are never
interpreted; they stay visible as plain text in both the page and the Markdown file.
"""

import re
import unicodedata

import nh3
from markdown_it import MarkdownIt
from markdown_it.token import Token

_ALLOWED_TAGS = {"strong", "em", "code"}
# "&" only matters where it starts a character reference.
_MARKDOWN_SPECIAL_RE = re.compile(
    r"([\\`*_\[\]<>#|~]|&(?=#\d+;|#[xX][0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]*;))"
)
_LEADING_BLOCK_MARKER_RE = re.compile(r"^([-+]+|\d{1,9}[.)])(?=\s|$)")
_DELIMITERS = {
    "strong_open": "**",
    "strong_close": "**",
    "em_open": "*",
    "em_close": "*",
}

# The "zero" preset turns every rule off, so links, images, autolinks, raw HTML and
# entities are left as literal text.
_PARSER = MarkdownIt("zero").enable(["emphasis", "backticks", "escape"])


def escape_markdown(text: str) -> str:
    """Flatten ``text`` to one visible line and escape everything Markdown would interpret."""
    return _escape_block_marker(_escape_text(normalize(text)))


def to_inline_markdown(text: str) -> str:
    """Rewrite ``text`` as one line of Markdown that keeps only bold, italics and code.

    Delimiters are written in one canonical form (``**``, ``*`` and backticks), and every
    other character Markdown would interpret is escaped.
    """
    parts = [_token_markdown(token) for token in _inline_tokens(normalize(text))]
    return _escape_block_marker("".join(parts))


def to_inline_html(text: str) -> str:
    """Render ``text`` as HTML that can only contain ``strong``, ``em`` and ``code``."""
    html = _PARSER.renderInline(normalize(text))
    # Defence in depth: the parser already escapes everything else.
    return nh3.clean(html, tags=_ALLOWED_TAGS, attributes={}, link_rel=None)


def normalize(text: str) -> str:
    """Collapse ``text`` onto one line and drop control, format and bidi characters."""
    # Whitespace is collapsed before control characters are dropped, so a newline becomes
    # a space instead of gluing two words together.
    flat = " ".join(text.split())
    return "".join(char for char in flat if not unicodedata.category(char).startswith("C")).strip()


def _inline_tokens(text: str) -> list[Token]:
    if not text:
        return []
    [inline] = _PARSER.parseInline(text)
    return inline.children or []


def _token_markdown(token: Token) -> str:
    if token.type == "code_inline":
        return _code_span(token.content)
    if token.type in _DELIMITERS:
        return _DELIMITERS[token.type]
    return _escape_text(token.content)


def _code_span(content: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    fence = "`" * (longest + 1)
    # A space on each side keeps an edge backtick from merging with the fence, and keeps
    # spaces on both edges; the parser strips exactly one space from each side again.
    spaced = content.startswith(" ") and content.endswith(" ")
    if content.strip() and (spaced or content.startswith("`") or content.endswith("`")):
        content = f" {content} "
    return f"{fence}{content}{fence}"


def _escape_text(text: str) -> str:
    return _MARKDOWN_SPECIAL_RE.sub(r"\\\1", text)


def _escape_block_marker(line: str) -> str:
    return _LEADING_BLOCK_MARKER_RE.sub(_escape_marker, line)


def _escape_marker(match: re.Match[str]) -> str:
    marker = match.group(1)
    if marker[-1] in ".)":
        return f"{marker[:-1]}\\{marker[-1]}"
    return f"\\{marker}"
