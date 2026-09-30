"""Allowlist of languages a summary can be written in."""

from collections.abc import Mapping
from types import MappingProxyType

from vidbrief.domain.errors import UnsupportedLanguageError

# Keys are the BCP 47 tags users choose from; values are the English names placed in the
# LLM prompt, so user-supplied text never reaches the prompt verbatim.
SUPPORTED_SUMMARY_LANGUAGES: Mapping[str, str] = MappingProxyType(
    {
        "pt-BR": "Brazilian Portuguese",
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "ja": "Japanese",
        "zh-CN": "Simplified Chinese",
    }
)


def summary_language_name(code: str) -> str:
    """Return the English name of an allowlisted summary language, for use in prompts.

    Raises:
        UnsupportedLanguageError: If ``code`` is not in the allowlist.
    """
    try:
        return SUPPORTED_SUMMARY_LANGUAGES[code]
    except KeyError:
        raise UnsupportedLanguageError("unsupported_language") from None
