"""Tests for token estimation and budget-based text splitting."""

import pytest

from vidbrief.adapters.text_chunks import estimate_tokens, split_off


@pytest.mark.parametrize(
    ("text", "tokens"), [("", 0), ("abc", 1), ("abcd", 2), ("漢", 1), ("漢字", 2)]
)
def test_estimates_one_token_per_three_utf8_bytes(text: str, tokens: int) -> None:
    assert estimate_tokens(text) == tokens


def test_returns_the_whole_text_when_it_fits() -> None:
    assert split_off("Short text.", 100) == ("Short text.", "")


def test_cuts_after_the_last_sentence_that_fits() -> None:
    text = "First sentence here. Second sentence here. Third sentence here."

    head, rest = split_off(text, 15)

    assert head == "First sentence here. Second sentence here."
    assert rest == "Third sentence here."


def test_cuts_between_words_when_there_is_no_punctuation() -> None:
    text = " ".join(f"word{number}" for number in range(100))

    head, rest = split_off(text, 50)

    assert estimate_tokens(head) <= 50
    assert f"{head} {rest}" == text


def test_ignores_a_sentence_end_that_would_leave_a_tiny_chunk() -> None:
    text = "Hi. " + " ".join(f"word{number}" for number in range(100))

    head, _ = split_off(text, 50)

    assert head != "Hi."
    assert estimate_tokens(head) > 25


def test_cuts_after_cjk_full_stops() -> None:
    text = "漢字漢字漢字漢字漢字。" * 10

    head, rest = split_off(text, 25)

    assert head.endswith("。")
    assert head + rest == text


def test_never_splits_a_multibyte_character_without_boundaries() -> None:
    text = "漢" * 100

    head, rest = split_off(text, 10)

    assert head == "漢" * 10
    assert head + rest == text


@pytest.mark.parametrize("budget", [5, 17, 40, 333])
def test_repeated_splits_keep_every_word_in_order(budget: int) -> None:
    text = " ".join(
        f"Sentence {number} has some words{'.' if number % 3 == 0 else ''}" for number in range(60)
    )
    pieces = []
    rest = text
    while rest:
        head, rest = split_off(rest, budget)
        assert head
        assert estimate_tokens(head) <= budget
        pieces.append(head)

    assert " ".join(pieces).split() == text.split()
