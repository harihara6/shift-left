"""The Confluence pages Feature Kickoff creates, in storage format.

The feasibility page is the kickoff's record where people already look: the facts with their
quotes, every rule outcome including what was ruled out and why, and every finding with its link.
Page Properties carry the epic key and status, so a Page Properties Report can list them.

HLD, LLD and test plan pages are starting points: the sections the evidence checklist expects,
with what the kickoff already knows filled in. Once created they belong to the team; ShiftLeft
never rewrites a page it created.

Every value is escaped. PRD text is untrusted and ends up in a page body.
"""

from html import escape

GLYPH = {"ok": "✓ OK", "gap": "! Gap", "blocker": "✕ Blocker", "not_checked": "? Not checked"}


def _p(text: str) -> str:
    return f"<p>{escape(text)}</p>"


def _a(text: str, url: str) -> str:
    return f'<a href="{escape(url, quote=True)}">{escape(text)}</a>' if url else escape(text)


def _row(*cells: str, head: bool = False) -> str:
    tag = "th" if head else "td"
    return "<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>"


def _table(head: list[str], rows: list[list[str]]) -> str:
    body = _row(*(_p(h) for h in head), head=True) + "".join(_row(*r) for r in rows)
    return f"<table><tbody>{body}</tbody></table>"


def _jira(key: str) -> str:
    if not key:
        return _p("Not created")
    return (f'<ac:structured-macro ac:name="jira" ac:schema-version="1">'
            f'<ac:parameter ac:name="key">{escape(key)}</ac:parameter></ac:structured-macro>')


def _prd_label(prd: dict) -> str:
    return f"{prd['title']} (v{prd['version']})"


def _info(text: str) -> str:
    return (f'<ac:structured-macro ac:name="info" ac:schema-version="1"><ac:rich-text-body>{_p(text)}'
            "</ac:rich-text-body></ac:structured-macro>")


def feasibility(record: dict, epic_key: str) -> str:
    prd = record["prd"]
    properties = _table(["Property", "Value"], [
        [_p("Epic"), _jira(epic_key)],
        [_p("Status"), _p("Planned")],
        [_p("PRD"), f"<p>{_a(_prd_label(prd), prd['url'])}</p>"],
        [_p("Risk tier"), _p(record["tier"])],
        [_p("Confirmed by"), _p(f"{record['approved_by']}, {record['approved_at']}")],
    ])
    parts = [
        '<ac:structured-macro ac:name="details" ac:schema-version="1"><ac:rich-text-body>'
        f"{properties}</ac:rich-text-body></ac:structured-macro>",
        _info(f"Drafted by {record['drafted_by']} in ShiftLeft Feature Kickoff #{record['session_id']} "
              f"and confirmed by {record['approved_by']}. The team owns this page; ShiftLeft won't "
              "overwrite it."),
        "<h2>What the PRD says</h2>",
        _table(["Fact", "Value", "From the PRD"], [
            [_p(f["label"]), _p(", ".join(f["values"]) or "Not stated"),
             "".join(_p(f"“{q['text']}” ({q.get('section') or 'PRD'})") for q in f["quotes"])
             or _p(f"Confirmed by {f['confirmed_by']}" if f.get("confirmed_by") else "—")]
            for f in record["facts"]
        ]),
        f"<h2>What runs, and what was ruled out</h2>{_p(record['tier_reason'])}",
        _table(["Action", "Outcome", "Why", "Chosen"], [
            [_p(a["label"]), _p(a["outcome_label"]), _p(a["reason"]),
             _p("Yes" if a["selected"] else f"No: {a['skip_reason'] or 'not recommended'}"
                + (" (flagged: not an acceptable rationale)" if a.get("skip_flagged") else ""))]
            for a in record["actions"]
        ]),
        "<h2>What the checks found</h2>",
        "<ul>" + "".join(f"<li>{escape(r)}</li>" for r in record["headline"]) + "</ul>"
        if record["headline"] else _p("No checks were selected, so nothing was verified."),
    ]
    for check in record["checks"]:
        parts.append(f"<h3>{escape(check['label'])}</h3>{_p(check['note'])}")
        parts.append("<ul>" + "".join(
            f"<li><strong>{escape(GLYPH.get(f['status'], f['status']))}</strong>: {escape(f['title'])}"
            + (f". {escape(f['detail'])}" if f.get("detail") else "")
            + (f" {_a(f['link']['label'], f['link']['url'])}" if f.get("link") else "") + "</li>"
            for f in check["findings"]
        ) + "</ul>")
    parts.append(_p("There is no “feasible” verdict: this lists what was found and what wasn't looked at."))
    return "".join(parts)


SECTIONS: dict[str, list[tuple[str, str]]] = {
    "hld": [
        ("Context", "Why this feature exists; link the PRD."),
        ("Scope and non-goals", ""),
        ("Architecture overview", "Components, and the flow between them."),
        ("Integrations and dependencies", ""),
        ("Security and data", "Data classes, trust boundaries, and where the threat model lives."),
        ("Standards alignment", ""),
        ("Open questions", ""),
    ],
    "lld": [
        ("Components", ""), ("APIs and contracts", "Link each spec at its commit."),
        ("Data model", ""), ("Error handling and fallbacks", ""), ("Observability", ""),
        ("Rollout and migration", ""),
    ],
    "test_plan": [
        ("Scope", ""), ("Test levels", "Tag every test @L1–@L4."),
        ("Non-functional testing", "Performance, security and accessibility, as the tier requires."),
        ("Environments and data", ""), ("Entry and exit criteria", ""),
        ("Traceability", "The Xray test plan and the stories each test covers."),
    ],
}


def starting_page(kind: str, record: dict, epic_key: str) -> str:
    known = {
        "Integrations and dependencies": ", ".join(record["services"]),
        "Standards alignment": ", ".join(record["standards"]),
        "Security and data": ", ".join(record["data_classes"]),
        "Traceability": f"Xray test plan: {record['test_plan_key']}" if record.get("test_plan_key") else "",
    }
    prd = record["prd"]
    parts = [
        _info(f"Started by ShiftLeft Feature Kickoff #{record['session_id']}, confirmed by "
              f"{record['approved_by']}. Replace each prompt; the team owns this page."),
        f"<p>PRD: {_a(_prd_label(prd), prd['url'])}. Epic:</p>{_jira(epic_key)}",
    ]
    for title, prompt in SECTIONS[kind]:
        parts.append(f"<h2>{escape(title)}</h2>")
        if known.get(title):
            parts.append(_p(f"From the kickoff: {known[title]}."))
        if prompt:
            parts.append(f"<p><em>{escape(prompt)}</em></p>")
    return "".join(parts)
