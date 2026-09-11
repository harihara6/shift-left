"""Which compliance a feature needs, proposed from what its PRD says. A person approves the list.

The catalog (`seed/data/kickoff_catalog.json`) is reference data: the frameworks that can be
approved, their triggers and the obligations the analysis plans against, plus the third-party
providers offered as quick picks.

The rule-based suggester is deterministic and always available. A framework is proposed:

* **strong**: one of its triggers is in the PRD ("PSD2", "cardholder"), or the PRD names the
  framework's region and one of its region terms ("open banking" in a PRD that says "Germany").
* **possible**: only a weak term matched ("card", "API"). Shown, never pre-selected.

Every suggestion quotes the PRD lines it came from. Claude, when configured, proposes from the
same catalog and its output is held to the same rule: a suggestion without a real quoted line is
dropped. Neither is a decision; the approved selection is, and it records who approved it.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent / "seed" / "data" / "kickoff_catalog.json"
MAX_QUOTES = 3


@lru_cache
def catalog() -> dict[str, Any]:
    return json.loads(DATA.read_text())


def frameworks() -> list[dict[str, Any]]:
    return catalog()["compliance"]


def framework(key: str) -> dict[str, Any] | None:
    return next((f for f in frameworks() if f["key"] == key), None)


def providers() -> list[dict[str, Any]]:
    return catalog()["providers"]


def provider(key: str) -> dict[str, Any] | None:
    return next((p for p in providers() if p["key"] == key), None)


@lru_cache(maxsize=512)
def _pattern(term: str, exact_case: bool = False) -> re.Pattern[str]:
    flags = 0 if exact_case else re.IGNORECASE
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", flags)


def quote(lines: list[str], index: int) -> dict[str, Any]:
    """Line `index` (0-based) as a quote: its 1-based number, text and section heading."""
    section = next((ln[3:] for ln in reversed(lines[:index]) if ln.startswith("## ")), "")
    text = lines[index]
    return {"line": index + 1, "text": text[2:] if text.startswith("- ") else text, "section": section}


def _hits(lines: list[str], terms: list[str], exact_case: bool = False) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            continue
        for term in terms:
            if _pattern(term, exact_case).search(line):
                found.append((i, term))
                break
    return found


def regions(lines: list[str]) -> dict[str, list[int]]:
    """Regions the PRD names, with the lines that name them. Codes (US, EU) match case exactly."""
    out: dict[str, list[int]] = {}
    for region, words in catalog()["regions"].items():
        rows = {i for i, _ in _hits(lines, words["codes"], exact_case=True)}
        rows |= {i for i, _ in _hits(lines, words["names"])}
        if rows:
            out[region] = sorted(rows)
    return out


def suggest(lines: list[str]) -> list[dict[str, Any]]:
    named = regions(lines)
    out: list[dict[str, Any]] = []
    for item in frameworks():
        strong = _hits(lines, item["triggers"])
        region_rows: list[int] = []
        if item["region"] in named:
            local = _hits(lines, item["region_terms"])
            if local:
                strong += local
                region_rows = named[item["region"]][:1]
        weak = [] if strong else _hits(lines, item["weak"])
        if not strong and not weak:
            continue
        matched = strong or weak
        terms = list(dict.fromkeys(term for _, term in matched))[:4]
        rows = list(dict.fromkeys([i for i, _ in matched] + region_rows))[:MAX_QUOTES]
        why = "The PRD mentions " + ", ".join(f"“{t}”" for t in terms)
        if region_rows:
            why += f" and names the {item['region']} market"
        why += "." if strong else ", which only sometimes means this applies."
        out.append(
            {
                "key": item["key"],
                "name": item["name"],
                "confidence": "strong" if strong else "possible",
                "why": why,
                "quotes": [quote(lines, i) for i in sorted(rows)],
                "by": "rules",
            }
        )
    out.sort(key=lambda s: (s["confidence"] != "strong", s["name"]))
    return out


def mentioned_providers(lines: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Catalog providers the PRD names, with the lines that name them."""
    out: dict[str, list[dict[str, Any]]] = {}
    for item in providers():
        rows = [i for i, _ in _hits(lines, item["aliases"])][:MAX_QUOTES]
        if rows:
            out[item["key"]] = [quote(lines, i) for i in rows]
    return out
