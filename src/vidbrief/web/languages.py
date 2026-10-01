"""How each summary language is presented in the web form."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageOption:
    """A summary language as shown to users: its own name plus an optional region tag."""

    code: str
    label: str
    region: str | None = None


# Names are written in each language so people find theirs without reading English.
LANGUAGE_OPTIONS: tuple[LanguageOption, ...] = (
    LanguageOption("pt-BR", "Português", "BR"),
    LanguageOption("en", "English"),
    LanguageOption("es", "Español"),
    LanguageOption("fr", "Français"),
    LanguageOption("de", "Deutsch"),
    LanguageOption("it", "Italiano"),
    LanguageOption("ja", "日本語"),
    LanguageOption("zh-CN", "简体中文"),
)
