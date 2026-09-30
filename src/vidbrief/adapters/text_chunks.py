"""Token estimation and splitting of long text into pieces that fit a token budget."""

import math
import re

# Tokenizers never emit more tokens than UTF-8 bytes, and in practice English averages
# about four bytes per token and CJK text about three, so this ratio errs on the safe side
# without shipping a model-specific tokenizer.
_BYTES_PER_TOKEN = 3
# CJK full stop and full-width marks are written as escapes because they look like ASCII.
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s)|[\u3002\uff01\uff1f]|\n")
_WHITESPACE_RE = re.compile(r"\s")


def estimate_tokens(text: str) -> int:
    """Return a conservative estimate of how many tokens ``text`` takes."""
    return math.ceil(len(text.encode()) / _BYTES_PER_TOKEN)


def split_off(text: str, max_tokens: int) -> tuple[str, str]:
    """Split ``text`` into a head within ``max_tokens`` and the remaining text.

    The head ends at the last sentence end that fits, else at the last space, and only
    as a last resort in the middle of a word; it never splits a character.
    """
    max_bytes = max_tokens * _BYTES_PER_TOKEN
    if len(text.encode()) <= max_bytes:
        return text, ""
    window = text.encode()[:max_bytes].decode(errors="ignore")
    # Cutting in the first half would produce many tiny requests, which cost more quota
    # than a cut in the middle of a sentence.
    minimum = len(window) // 2
    cut = (
        _last_end(_SENTENCE_END_RE, text, len(window), minimum)
        or _last_start(_WHITESPACE_RE, window, minimum)
        or max(len(window), 1)
    )
    return text[:cut].rstrip(), text[cut:].lstrip()


def _last_end(pattern: re.Pattern[str], text: str, limit: int, minimum: int) -> int | None:
    ends = [match.end() for match in pattern.finditer(text, 0, limit)]
    return ends[-1] if ends and ends[-1] > minimum else None


def _last_start(pattern: re.Pattern[str], text: str, minimum: int) -> int | None:
    starts = [match.start() for match in pattern.finditer(text)]
    return starts[-1] if starts and starts[-1] > minimum else None
