"""Turns the design prototype's two-quarter deck into per-period fact sets.

Run it when the prototype data changes:  python -m app.seed.generate

Why this exists: the prototype encodes one hardcoded comparison (Q2 2026 against Q3 2026) with
its distributions only ever computed for Q3. A period filter needs every period to stand on its
own, so this script:

* keeps every number the prototype states, exactly, for Q2-2026 and Q3-2026;
* derives the distributions Q2 never had, reconciled to Q2's stated totals;
* generates earlier quarters deterministically, seeded per team and period so a rerun is stable.

Everything it writes is fixture data standing in for connector output - `provenance` on each
period says whether it came from the prototype or from here.
"""

import json
import random
import re
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data"
SOURCE = DATA / "prototype_decks.json"
TARGET = DATA / "facts.json"

# The prototype's own two quarters, and the quarters generated behind them.
PROTOTYPE_CURRENT = "Q3-2026"
PROTOTYPE_BASELINE = "Q2-2026"
GENERATED = ["Q1-2026", "Q4-2025", "Q3-2025", "Q2-2025", "Q1-2025"]

# The last day the fixtures hold data for. Q3-2026 is deliberately partial - that is what makes
# the "compare rates, not counts" caveat real rather than decorative.
DATA_THROUGH = "2026-08-30"

WEEKS_IN_QUARTER = 13.0
PROTOTYPE_CURRENT_WEEKS = 8.7


def _number(text: str) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace("−", "-"))
    return float(match.group()) if match else 0.0


def _named(text: str, name: str) -> float | None:
    """Pull `median 66d` / `P85 119d` / `avg 0.34d` out of the prototype's summary strings."""
    match = re.search(rf"\b{name}\s*=?\s*(\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match else None


def _sample(text: str) -> int:
    """The `(n=8)` sample size. Anchored so it cannot match the n inside `median`."""
    match = re.search(r"\(n\s*=\s*(\d+)\)", text)
    return int(match.group(1)) if match else 0


def _merged(text: str) -> int:
    """The `329 PRs` count out of a PR summary string."""
    match = re.search(r"(\d+)\s*PRs", text)
    return int(match.group(1)) if match else 0


def _spread(total: int, shape: list[float], rng: random.Random) -> list[int]:
    """Split `total` across buckets shaped like `shape`, landing exactly on the total."""
    weight = sum(shape) or 1
    raw = [total * part / weight for part in shape]
    out = [int(value) for value in raw]
    remainder = total - sum(out)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)
    for index in range(remainder):
        out[order[index % len(order)]] += 1
    if total and not any(out):
        out[rng.randrange(len(out))] = total
    return out


def _scaled(values: list[float], factor: float, digits: int = 1) -> list[float]:
    return [round(value * factor, digits) for value in values]


def _week_labels(count: int, first: int) -> list[str]:
    return [f"W{first + index}" for index in range(count)]


def _cadence(total: int, count: int, rng: random.Random) -> list[int]:
    shape = [rng.uniform(0.7, 1.3) for _ in range(count)]
    return _spread(total, shape, rng)


def _current_facts(deck: dict[str, Any]) -> dict[str, Any]:
    """Q3-2026, entirely as the prototype states it."""
    epics, stories, maint, prs, detection = (
        deck["epics"], deck["stories"], deck["maint"], deck["prs"], deck["detection"]
    )
    opened, resolved = (float(part) for part in maint["flow"].split("/"))
    return {
        "provenance": "prototype",
        "epics": {
            "avg_cycle_days": _number(epics["q3avg"]),
            "median_days": _named(epics["q3sub"], "median"),
            "p85_days": _named(epics["q3sub"], "P85"),
            "sample": _sample(epics["q3sub"]),
            "throughput": epics["tq3"],
            "size": epics["size"],
        },
        "stories": {
            "avg_cycle_days": _number(stories["q3avg"]),
            "median_days": _named(stories["q3sub"], "median"),
            "p85_days": _named(stories["q3sub"], "P85"),
            "sample": _sample(stories["q3sub"]),
            "throughput": stories["tq3"],
            "weekly": {"labels": stories["weeks"], "done": stories["done"]},
            "size": stories["size"],
        },
        "maint": {
            "avg_cycle_days": _number(maint["q3avg"]),
            "median_days": _named(maint["q3sub"], "median"),
            "sample": sum(maint["priority"]["count"]),
            "opened": int(opened),
            "resolved": int(resolved),
            "backlog_end": int(_number(maint["backlog"])),
            "priority": maint["priority"],
        },
        "prs": {
            "median_cycle_days": _number(prs["q3median"]),
            "avg_cycle_days": _named(prs["q3sub"], "avg") or _number(prs["q3sub"]),
            "merged": _merged(prs["q3sub"]),
            "small_pct": _number(prs["small"]),
            "huge_count": int(_number(prs["huge"])),
            "buckets": prs["buckets"],
            "cadence": {"labels": prs["periods"], "merged": prs["merged"]},
        },
        "detection": {
            "labels": detection["weeks"],
            "pr": detection["pr"],
            "nightly": detection["nightly"],
            "prod": detection["prod"],
        },
    }


def _baseline_facts(deck: dict[str, Any], current: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Q2-2026. Every stated number is kept; only the distributions the prototype never had
    are derived, and they reconcile to the totals it does state."""
    epics, stories, maint, prs = deck["epics"], deck["stories"], deck["maint"], deck["prs"]

    epic_avg = _number(epics["q2avg"])
    epic_ratio = epic_avg / (current["epics"]["avg_cycle_days"] or 1)
    story_avg = _number(stories["q2avg"])
    story_ratio = story_avg / (current["stories"]["avg_cycle_days"] or 1)
    maint_avg = _number(maint["q2avg"])
    maint_ratio = maint_avg / (current["maint"]["avg_cycle_days"] or 1)

    story_throughput = stories["tq2"]
    maint_resolved = int(_number(deck["glance"][3][1]))
    backlog_end = int(_named(maint["backlogSub"], "was") or 0)
    # Q2 opened is not stated. Hold the closure rate Q3 shows, which is the least-invented option.
    closure = current["maint"]["opened"] / (current["maint"]["resolved"] or 1)
    prs_merged = _merged(prs["q2sub"])

    return {
        "provenance": "prototype",
        "derived_fields": [
            "epics.size", "stories.weekly", "stories.size", "maint.priority",
            "maint.opened", "prs.huge_count", "prs.buckets", "prs.cadence", "detection",
        ],
        "epics": {
            "avg_cycle_days": epic_avg,
            "median_days": _named(epics["q2sub"], "median"),
            "p85_days": _named(epics["q2sub"], "P85"),
            "sample": _sample(epics["q2sub"]),
            "throughput": epics["tq2"],
            "size": {
                "labels": current["epics"]["size"]["labels"],
                "count": _spread(epics["tq2"], current["epics"]["size"]["count"], rng),
                "cycle": _scaled(current["epics"]["size"]["cycle"], epic_ratio, 0),
            },
        },
        "stories": {
            "avg_cycle_days": story_avg,
            "median_days": _named(stories["q2sub"], "median"),
            "p85_days": _named(stories["q2sub"], "P85"),
            "sample": _sample(stories["q2sub"]),
            "throughput": story_throughput,
            "weekly": {
                "labels": _week_labels(13, 14),
                "done": _cadence(story_throughput, 13, rng),
            },
            "size": {
                "labels": current["stories"]["size"]["labels"],
                "count": _spread(story_throughput, current["stories"]["size"]["count"], rng),
                "cycle": _scaled(current["stories"]["size"]["cycle"], story_ratio, 0),
            },
        },
        "maint": {
            "avg_cycle_days": maint_avg,
            "median_days": _named(maint["q2sub"], "median"),
            "sample": _sample(maint["q2sub"]),
            "opened": round(maint_resolved * closure),
            "resolved": maint_resolved,
            "backlog_end": backlog_end,
            "priority": {
                "labels": current["maint"]["priority"]["labels"],
                "count": _spread(maint_resolved, current["maint"]["priority"]["count"], rng),
                "cycle": _scaled(current["maint"]["priority"]["cycle"], maint_ratio, 0),
            },
        },
        "prs": {
            "median_cycle_days": _number(prs["q2median"]),
            "avg_cycle_days": _named(prs["q2sub"], "avg") or 0.0,
            "merged": prs_merged,
            "small_pct": _number(deck["glance"][5][1]),
            "huge_count": round(prs_merged * (1 - _number(deck["glance"][5][1]) / 100) * 0.55),
            "buckets": {
                "labels": current["prs"]["buckets"]["labels"],
                "cycle": _scaled(current["prs"]["buckets"]["cycle"], rng.uniform(1.2, 1.7), 2),
            },
            "cadence": {
                "labels": ["Apr 1", "Apr 15", "Apr 29", "May 13", "May 27", "Jun 10", "Jun 24"],
                "merged": _cadence(prs_merged, 7, rng),
            },
        },
        "detection": _drift_detection(current["detection"], rng, backwards=True),
    }


def _drift_detection(detection: dict[str, Any], rng: random.Random, backwards: bool) -> dict[str, Any]:
    """Shift-left is meant to improve over time, so earlier periods catch less at PR."""
    direction = -1 if backwards else 1
    step = rng.uniform(4, 9) * direction
    pr = [max(5, min(95, round(value + step))) for value in detection["pr"]]
    nightly = [max(3, round(value - step * 0.5)) for value in detection["nightly"]]
    prod = [max(1, round(value - step * 0.25)) for value in detection["prod"]]
    return {"labels": detection["labels"], "pr": pr, "nightly": nightly, "prod": prod}


def _generate_quarter(previous: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """One quarter older than `previous`, drifting the numbers rather than inventing new shapes."""

    def drift(value: float, low: float = 0.85, high: float = 1.25, digits: int = 1) -> float:
        return round(value * rng.uniform(low, high), digits)

    epic_throughput = max(1, round(previous["epics"]["throughput"] * rng.uniform(0.7, 1.35)))
    story_throughput = max(4, round(previous["stories"]["throughput"] * rng.uniform(0.75, 1.3)))
    maint_resolved = max(5, round(previous["maint"]["resolved"] * rng.uniform(0.75, 1.3)))
    maint_opened = max(5, round(maint_resolved * rng.uniform(0.85, 1.35)))
    prs_merged = max(5, round(previous["prs"]["merged"] * rng.uniform(0.7, 1.3)))
    small_pct = round(max(25, min(95, previous["prs"]["small_pct"] * rng.uniform(0.88, 1.08))))

    return {
        "provenance": "generated",
        "epics": {
            "avg_cycle_days": drift(previous["epics"]["avg_cycle_days"]),
            "median_days": drift(previous["epics"]["median_days"] or 0, digits=0) or None,
            "p85_days": drift(previous["epics"]["p85_days"] or 0, digits=0) or None,
            "sample": max(1, round(epic_throughput * rng.uniform(0.6, 1.0))),
            "throughput": epic_throughput,
            "size": {
                "labels": previous["epics"]["size"]["labels"],
                "count": _spread(epic_throughput, previous["epics"]["size"]["count"], rng),
                "cycle": _scaled(previous["epics"]["size"]["cycle"], rng.uniform(0.85, 1.3), 0),
            },
        },
        "stories": {
            "avg_cycle_days": drift(previous["stories"]["avg_cycle_days"]),
            "median_days": drift(previous["stories"]["median_days"] or 0, digits=0) or None,
            "p85_days": drift(previous["stories"]["p85_days"] or 0, digits=0) or None,
            "sample": max(3, round(story_throughput * rng.uniform(0.8, 1.0))),
            "throughput": story_throughput,
            "weekly": {
                "labels": _week_labels(13, 1),
                "done": _cadence(story_throughput, 13, rng),
            },
            "size": {
                "labels": previous["stories"]["size"]["labels"],
                "count": _spread(story_throughput, previous["stories"]["size"]["count"], rng),
                "cycle": _scaled(previous["stories"]["size"]["cycle"], rng.uniform(0.85, 1.3), 0),
            },
        },
        "maint": {
            "avg_cycle_days": drift(previous["maint"]["avg_cycle_days"]),
            "median_days": drift(previous["maint"]["median_days"] or 0, digits=0) or None,
            "sample": maint_resolved,
            "opened": maint_opened,
            "resolved": maint_resolved,
            # Backlog rolls backwards consistently: this period's end is the next one's start.
            "backlog_end": max(
                0, previous["maint"]["backlog_end"] - maint_opened + maint_resolved
            ),
            "priority": {
                "labels": previous["maint"]["priority"]["labels"],
                "count": _spread(maint_resolved, previous["maint"]["priority"]["count"], rng),
                "cycle": _scaled(previous["maint"]["priority"]["cycle"], rng.uniform(0.85, 1.3), 0),
            },
        },
        "prs": {
            "median_cycle_days": round(previous["prs"]["median_cycle_days"] * rng.uniform(0.8, 1.4), 2),
            "avg_cycle_days": round(previous["prs"]["avg_cycle_days"] * rng.uniform(0.8, 1.4), 2),
            "merged": prs_merged,
            "small_pct": small_pct,
            "huge_count": round(prs_merged * (1 - small_pct / 100) * rng.uniform(0.4, 0.7)),
            "buckets": {
                "labels": previous["prs"]["buckets"]["labels"],
                "cycle": _scaled(previous["prs"]["buckets"]["cycle"], rng.uniform(0.9, 1.4), 2),
            },
            "cadence": {
                "labels": ["Wk 1", "Wk 3", "Wk 5", "Wk 7", "Wk 9", "Wk 11", "Wk 13"],
                "merged": _cadence(prs_merged, 7, rng),
            },
        },
        "detection": _drift_detection(previous["detection"], rng, backwards=True),
    }


def build() -> dict[str, Any]:
    decks = json.loads(SOURCE.read_text())
    out: dict[str, Any] = {"data_through": DATA_THROUGH, "teams": {}}

    for team, deck in decks.items():
        rng = random.Random(f"shiftleft::{team}")
        current = _current_facts(deck)
        baseline = _baseline_facts(deck, current, rng)
        periods = {PROTOTYPE_CURRENT: current, PROTOTYPE_BASELINE: baseline}

        previous = baseline
        for key in GENERATED:
            previous = _generate_quarter(previous, rng)
            periods[key] = previous

        out["teams"][team] = {
            "label": deck["label"],
            "pr_scope": deck["prs"]["scope"],
            "periods": periods,
        }
    return out


if __name__ == "__main__":
    TARGET.write_text(json.dumps(build(), indent=1, ensure_ascii=False))
    print(f"wrote {TARGET}")
