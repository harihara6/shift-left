"""Parse the product index into rows. **Write this in the environment that can reach it.**

The product index lives at software.backbase.eu (under /product/index), outside Confluence and
out of reach of the machine this was built on, so the parser is left as a contract with no body.
`app/connectors/product_index.py` fetches `SHIFTLEFT_PRODUCT_INDEX_URL` and hands the response
text here; everything after that (duplicate detection, the diff on the plan, the hand-off result)
already works against the fixtures and needs no change.

To finish it:

1. Fetch the page once and look at its markup (or its JSON, if the site has a data endpoint).
2. Implement `parse()` to return every feature row: name, product, status, and a link if rows
   have their own pages. Keep it deterministic: no model, no guessing. If a row can't be read,
   leave it out rather than inventing fields.
3. Return `version` if the page states one (a release, a "last updated"); leave it empty and a
   content hash is used, so a change between drafting and applying is still detected.
4. Set `WRITTEN = True`, and add a test in `tests/test_kickoff_live.py` with a saved copy of the
   page (scrubbed of anything internal) as the fixture.

Writing to the index is a separate decision (proposal s11): if the site is generated from a
repository, the natural writer is a pull request with the new row, reviewed like any other change.
Until a writer exists, index rows on a confirmed plan are handed off to a person, never dropped.
"""

from dataclasses import dataclass, field

# Flip to True once `parse` is implemented. Settings and the kickoff page read it to say whether
# the index can be read at all.
WRITTEN = False


class ParserNotWritten(NotImplementedError):
    """The index can't be read yet. Reported as unavailable, never as an empty index."""


@dataclass
class IndexFeature:
    feature: str
    product: str
    status: str = ""
    url: str = ""


@dataclass
class ParsedIndex:
    features: list[IndexFeature] = field(default_factory=list)
    # What the page says its version is. Empty means "use a hash of the content".
    version: str = ""


def parse(document: str, url: str) -> ParsedIndex:
    """Every feature row on the index page at `url`, whose response body is `document`."""
    raise ParserNotWritten(
        "The product index parser isn't written yet (app/connectors/product_index_parser.py)."
    )
