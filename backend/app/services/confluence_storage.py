"""Confluence storage format (XHTML), read and edited without a round trip through Markdown.

Two jobs:

* **Reading a PRD** into the same line shape the fixtures use ("## Section", "- bullet", text),
  so the extractor, the quotes and the rules don't know which source a page came from.
* **Editing the software catalog table** in place: add a row, or change one cell, with every
  other byte of the page left exactly as it was. Nothing here rewrites a page.

The catalog's layout is still an open decision (proposal s11). Until it's settled, a catalog is
the first table whose header names a component and a repository; `CATALOG_COLUMNS` lists the
header texts accepted for each field. A table this can't read safely (a nested table, no header)
is reported as unreadable, never guessed at.
"""

import html
import re
from dataclasses import dataclass, field
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


# --- The catalog table ----------------------------------------------------------------------------

CATALOG_COLUMNS: dict[str, tuple[str, ...]] = {
    "name": ("component", "service", "name"),
    "owner": ("owner", "owning team", "team"),
    "jira_project": ("jira project", "jira"),
    "repo": ("repository", "repo", "github"),
    "spec_path": ("spec path", "api spec", "openapi", "spec"),
    "ref": ("branch", "ref"),
    "status": ("status",),
    "planned": ("planned operations", "planned"),
    "depends_on": ("depends on", "dependencies"),
    "standards": ("standards",),
}

TABLE = re.compile(r"<table\b[^>]*>.*?</table>", re.S | re.I)
ROW = re.compile(r"<tr\b[^>]*>.*?</tr>", re.S | re.I)
CELL = re.compile(r"(<t([hd])\b[^>]*>)(.*?)(</t\2>)", re.S | re.I)
TAG = re.compile(r"<[^>]+>")


class TableUnreadable(ValueError):
    """The page has no catalog table this can read and edit safely."""


def cell_text(fragment: str) -> str:
    return " ".join(html.unescape(TAG.sub(" ", fragment)).split())


def _column_key(header: str) -> str | None:
    text = header.lower().strip(" :")
    return next((key for key, names in CATALOG_COLUMNS.items() if text in names), None)


@dataclass
class Table:
    start: int
    end: int
    columns: list[str]
    keys: list[str | None]
    rows: list[dict] = field(default_factory=list)

    def has(self, key: str) -> bool:
        return key in self.keys


def catalog_table(storage: str) -> Table:
    for match in TABLE.finditer(storage):
        inner = match.group(0)
        if "<table" in inner[6:].lower():
            continue  # a nested table: its rows can't be told apart safely
        rows = ROW.findall(inner)
        if not rows:
            continue
        columns = [cell_text(c[2]) for c in CELL.findall(rows[0])]
        keys = [_column_key(c) for c in columns]
        if "name" not in keys or "repo" not in keys:
            continue
        table = Table(match.start(), match.end(), columns, keys)
        for row in rows[1:]:
            cells = [cell_text(c[2]) for c in CELL.findall(row)]
            record = {k: (cells[i] if i < len(cells) else "") for i, k in enumerate(keys) if k}
            if record.get("name"):
                record["repo"] = re.sub(r"^https?://[^/]+/", "", record.get("repo", "")).strip("/")
                table.rows.append(record)
        return table
    raise TableUnreadable(
        "No table on the catalog page has both a component and a repository column "
        f"(accepted headers: {', '.join(CATALOG_COLUMNS['name'] + CATALOG_COLUMNS['repo'])})."
    )


def split_list(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;\n]", text) if p.strip()]


def _cell(value: str) -> str:
    return f"<td><p>{html.escape(value)}</p></td>"


def add_row(storage: str, fields: dict[str, str]) -> str:
    """The page with one row appended to the catalog table. Columns the table lacks are dropped."""
    table = catalog_table(storage)
    row = "<tr>" + "".join(_cell(fields.get(k, "") if k else "") for k in table.keys) + "</tr>"
    inner = storage[table.start:table.end]
    at = inner.lower().rfind("</tbody>")
    if at < 0:
        at = inner.lower().rfind("</table>")
    return storage[:table.start] + inner[:at] + row + inner[at:] + storage[table.end:]


def set_cell(storage: str, name: str, key: str, value: str) -> str:
    """The page with one cell of `name`'s row replaced. Its attributes and every other cell stay."""
    table = catalog_table(storage)
    if key not in table.keys:
        raise TableUnreadable(f"The catalog table has no {key.replace('_', ' ')} column.")
    column, name_column = table.keys.index(key), table.keys.index("name")
    inner = storage[table.start:table.end]
    for row in list(ROW.finditer(inner))[1:]:
        cells = list(CELL.finditer(row.group(0)))
        if column >= len(cells) or cell_text(cells[name_column].group(3)).lower() != name.lower():
            continue
        target = cells[column]
        text = row.group(0)
        new_row = text[:target.start(3)] + f"<p>{html.escape(value)}</p>" + text[target.end(3):]
        edited = inner[:row.start()] + new_row + inner[row.end():]
        return storage[:table.start] + edited + storage[table.end:]
    raise TableUnreadable(f"{name} isn't a row in the catalog table.")
