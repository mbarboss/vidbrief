"""Tests for the language choices shown in the web form."""

from vidbrief.domain.languages import SUPPORTED_SUMMARY_LANGUAGES
from vidbrief.web.languages import LANGUAGE_OPTIONS


def test_offers_exactly_the_allowlisted_languages_in_the_same_order() -> None:
    assert [option.code for option in LANGUAGE_OPTIONS] == list(SUPPORTED_SUMMARY_LANGUAGES)


def test_labels_are_written_in_each_language() -> None:
    labels = {option.code: (option.label, option.region) for option in LANGUAGE_OPTIONS}

    assert labels["pt-BR"] == ("Português", "BR")
    assert labels["en"] == ("English", None)
    assert labels["ja"] == ("日本語", None)
    assert labels["zh-CN"] == ("简体中文", None)
