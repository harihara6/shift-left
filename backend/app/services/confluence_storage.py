"""Confluence storage format (XHTML), read into lines without a round trip through Markdown.

A PRD becomes "## Section", "- bullet" and plain text lines, one per block; a table row becomes
one line with its cells joined by " | ". Feature Kickoff numbers these lines, so every quote in an
analysis points at a line of the page as it was read.
"""

from html.parser import HTMLParser

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
BLOCKS = {"p", "li", "tr", "div", "blockquote", "pre", "ul", "ol", "table"}
# Macro parameters and code bodies are configuration, not prose.
SKIP = {"ac:parameter", "ac:plain-text-body", "script", "style"}


class _Lines(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.buf: list[str] = []
        self.prefix = ""
        self.skip = 0
        self.cell = 0

    def _flush(self) -> None:
        text = " ".join("".join(self.buf).split())
        if text:
            self.lines.append(self.prefix + text)
            self.prefix = ""
        self.buf = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in SKIP:
            self.skip += 1
        elif tag in ("td", "th"):
            if self.buf and "".join(self.buf).strip():
                self.buf.append(" | ")
            self.cell += 1
        elif self.cell:
            return  # paragraphs inside a table cell stay on the row's line
        elif tag in HEADINGS:
            self._flush()
            self.prefix = "## "
        elif tag == "li":
            self._flush()
            self.prefix = "- "
        elif tag in BLOCKS or tag == "br":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th"):
            self.cell = max(0, self.cell - 1)
        elif self.cell:
            return
        elif tag in HEADINGS or tag == "li":
            self._flush()
            self.prefix = ""
        elif tag in BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.buf.append(data)


def body_lines(storage: str) -> list[str]:
    parser = _Lines()
    parser.feed(storage)
    parser.close()
    parser._flush()
    return parser.lines
