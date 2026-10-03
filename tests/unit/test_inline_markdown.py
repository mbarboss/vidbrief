"""Tests for the inline Markdown subset allowed in summaries."""

from html.parser import HTMLParser

import pytest

from vidbrief.services.inline_markdown import escape_markdown, to_inline_html, to_inline_markdown

ALLOWED_TAGS = {"strong", "em", "code"}
HOSTILE_SAMPLES = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '<a href="javascript:alert(1)">x</a>',
    "[click](javascript:alert(1))",
    "![pixel](https://evil.example/p.png)",
    "<https://evil.example>",
    "https://evil.example/path?q=1",
    "**<b>bold</b>** and `<i>code</i>`",
    "*<svg onload=alert(1)>*",
    "&lt;script&gt; &#60;b&#62; &amp;",
    "# Heading | table ~~strike~~",
    "line one\n\n- injected\n> quote",
    "\x1b[31mred\x07 ‮reversed",
    "<!-- comment --> <![CDATA[x]]> <?php ?>",
    '<code class="x" onclick="alert(1)">c</code>',
    "`` a`b `` and ```` ` ````",
]


class TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, list[tuple[str, str | None]]]] = []
        self.other: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, attrs))

    def handle_comment(self, data: str) -> None:
        self.other.append(data)

    def handle_decl(self, decl: str) -> None:
        self.other.append(decl)

    def handle_pi(self, data: str) -> None:
        self.other.append(data)

    def unknown_decl(self, data: str) -> None:
        self.other.append(data)


def _parse(html: str) -> TagCollector:
    collector = TagCollector()
    collector.feed(html)
    collector.close()
    return collector


class TestInlineHtml:
    @pytest.mark.parametrize(
        ("text", "html"),
        [
            ("Plain text.", "Plain text."),
            ("A **key** term", "A <strong>key</strong> term"),
            ("An *aside* and _another_", "An <em>aside</em> and <em>another</em>"),
            ("Run `uv sync` first", "Run <code>uv sync</code> first"),
            ("***both***", "<em><strong>both</strong></em>"),
            ("Use `a<b>`", "Use <code>a&lt;b&gt;</code>"),
            ("**unclosed", "**unclosed"),
            ("snake_case_name", "snake_case_name"),
            (r"\*literal\*", "*literal*"),
        ],
    )
    def test_renders_emphasis_and_code(self, text: str, html: str) -> None:
        assert to_inline_html(text) == html

    @pytest.mark.parametrize("text", HOSTILE_SAMPLES)
    def test_hostile_text_yields_only_allowed_tags_without_attributes(self, text: str) -> None:
        parsed = _parse(to_inline_html(text))

        assert {tag for tag, _ in parsed.tags} <= ALLOWED_TAGS
        assert all(attrs == [] for _, attrs in parsed.tags)
        assert parsed.other == []

    def test_links_images_and_html_stay_visible_as_text(self) -> None:
        html = to_inline_html("[a](javascript:x) ![b](http://e/p.png) <b>c</b> &amp;")

        assert html == ("[a](javascript:x) ![b](http://e/p.png) &lt;b&gt;c&lt;/b&gt; &amp;amp;")

    def test_flattens_lines_and_drops_control_characters(self) -> None:
        assert to_inline_html("one\n\n# two\x1b\x07‮") == "one # two"


class TestInlineMarkdown:
    @pytest.mark.parametrize(
        ("text", "markdown"),
        [
            ("Plain text.", "Plain text."),
            ("A **key** term", "A **key** term"),
            ("A __key__ term", "A **key** term"),
            ("An *aside* and _another_", "An *aside* and *another*"),
            ("Run `uv sync` first", "Run `uv sync` first"),
            ("``a`b``", "``a`b``"),
            ("`` `tick` ``", "`` `tick` ``"),
            ("***both***", "***both***"),
            ("**unclosed", "\\*\\*unclosed"),
            ("snake_case_name", "snake\\_case\\_name"),
            ("[a](javascript:x) <b>", "\\[a\\](javascript:x) \\<b\\>"),
            ("Tom & Jerry &amp; &#60;", "Tom & Jerry \\&amp; \\&\\#60;"),
            ("one\n\n# two\x1b‮", "one \\# two"),
        ],
    )
    def test_keeps_emphasis_and_code_and_escapes_the_rest(self, text: str, markdown: str) -> None:
        assert to_inline_markdown(text) == markdown

    @pytest.mark.parametrize(
        ("text", "markdown"),
        [
            ("- nested", "\\- nested"),
            ("+ plus", "\\+ plus"),
            ("1. first", "1\\. first"),
            ("2) second", "2\\) second"),
            ("---", "\\---"),
            ("**bold** start", "**bold** start"),
        ],
    )
    def test_a_leading_block_marker_cannot_start_a_list_or_rule(
        self, text: str, markdown: str
    ) -> None:
        assert to_inline_markdown(text) == markdown

    @pytest.mark.parametrize(
        "text",
        [
            *HOSTILE_SAMPLES,
            "A **key** term with *aside*, `code` and __more__.",
            "x*y*z and foo_bar_ and **[link]**",
            "``a`b`` then ` lead` and `trail `",
        ],
    )
    def test_renders_to_the_same_html_as_the_original(self, text: str) -> None:
        assert to_inline_html(to_inline_markdown(text)) == to_inline_html(text)


def test_escape_markdown_escapes_formatting_too() -> None:
    assert escape_markdown("**bold** `code` <b> 1. x") == "\\*\\*bold\\*\\* \\`code\\` \\<b\\> 1. x"
    assert escape_markdown("1. first") == "1\\. first"


@pytest.mark.parametrize("text", ["", "  \n\t", "\x00\x1b"])
def test_blank_text_stays_empty(text: str) -> None:
    assert to_inline_markdown(text) == ""
    assert to_inline_html(text) == ""
    assert escape_markdown(text) == ""
