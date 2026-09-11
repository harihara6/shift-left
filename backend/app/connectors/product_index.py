"""Reading the product index from where it lives (software.backbase.eu), through a pluggable parser.

Fetching is here; reading the markup is `product_index_parser.parse`, written separately in the
environment that can reach the site. Whatever goes wrong (not configured, parser not written,
site unreachable, page changed shape) the result is `available=False` with the reason, so the
plan says the index couldn't be read instead of treating it as empty (product rule 1).
"""

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import httpx

from app.connectors import http, product_index_parser
from app.core.config import get_settings

logger = logging.getLogger("shiftleft.kickoff")


@dataclass
class IndexRead:
    available: bool
    note: str
    title: str = "Product index"
    url: str = ""
    version: str = ""
    features: list[dict] = field(default_factory=list)


def state() -> tuple[str, str]:
    """(state, note) for the connections list, without fetching anything."""
    settings = get_settings()
    if not settings.product_index_url:
        return "not_configured", "No product index URL is configured (SHIFTLEFT_PRODUCT_INDEX_URL)."
    if not product_index_parser.WRITTEN:
        return "not_built", (
            "The parser isn't written yet (app/connectors/product_index_parser.py). Index rows are "
            "drafted on the plan and handed off to a person."
        )
    return "configured", f"Read from {settings.product_index_url}. No writer yet: rows are handed off."


async def read() -> IndexRead:
    settings = get_settings()
    url = settings.product_index_url
    status, note = state()
    if status != "configured":
        # Nothing to fetch with no URL, and no point fetching a page nothing can read yet.
        return IndexRead(False, note, url=url)
    headers = {}
    if settings.product_index_token:
        headers["Authorization"] = f"Bearer {settings.product_index_token.get_secret_value()}"
    try:
        async with http.client() as c:
            response = await c.get(url, headers=headers, follow_redirects=True)
    except httpx.HTTPError as exc:
        return IndexRead(False, f"Couldn't reach the product index ({type(exc).__name__}).", url=url)
    if response.status_code >= 400:
        return IndexRead(False, f"The product index answered HTTP {response.status_code}.", url=url)
    try:
        parsed = product_index_parser.parse(response.text, url)
    except product_index_parser.ParserNotWritten as exc:
        return IndexRead(False, str(exc), url=url)
    except Exception as exc:  # a parser that breaks on a changed page must not break the kickoff
        logger.warning("The product index parser failed: %s", exc)
        return IndexRead(False, f"The parser couldn't read the page ({type(exc).__name__}); it may "
                                "have changed shape.", url=url)
    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    version = parsed.version or f"content {hashlib.sha256(response.content).hexdigest()[:10]}"
    return IndexRead(True, f"Read {len(parsed.features)} feature(s) at {retrieved}.", url=url,
                     version=version, features=[asdict(f) for f in parsed.features])
