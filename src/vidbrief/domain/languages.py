"""Allowlist of languages a summary can be written in."""

from collections.abc import Mapping
from types import MappingProxyType

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
