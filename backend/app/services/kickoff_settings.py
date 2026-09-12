"""Service-wide Feature Kickoff defaults: the values a new analysis starts filled in with.

These exist because the requirement-to-backlog loop is run over and over: the TDD template, the
backlog, the labels a team's tickets carry and the standing instruction to the drafter are the
same every time, and retyping them per analysis is how they end up inconsistent.

They are defaults, never a lock. Everything here is copied onto an analysis when it is created and
stays editable there, so a later change to these settings never reaches an analysis already under
way. No credential lives here: those stay in Settings -> Connectors and the vault.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kickoff import KickoffSettings
from app.schemas import kickoff as out
from app.services import kickoff_tdd as tdd


async def load(session: AsyncSession) -> KickoffSettings:
    """The single row. Created on the spot if a store predates it, so callers never see None."""
    row = await session.get(KickoffSettings, 1)
    if row is None:
        row = KickoffSettings(id=1)
        session.add(row)
        await session.flush()
    return row


def view(row: KickoffSettings, *, editable: bool) -> out.KickoffSettingsOut:
    return out.KickoffSettingsOut(
        tdd_template_url=row.tdd_template_url,
        tdd_space_key=row.tdd_space_key,
        tdd_parent_url=row.tdd_parent_url,
        tdd_sections=list(row.tdd_sections or []),
        jira_project_url=row.jira_project_url,
        jira_defaults=out.JiraDefaults(**(row.jira_defaults or {})),
        analysis_prompt=row.analysis_prompt,
        tdd_prompt=row.tdd_prompt,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
        section_catalog=[
            out.TddCatalogSection(**{k: entry[k] for k in out.TddCatalogSection.model_fields})
            for entry in tdd.sections()
        ],
        editable=editable,
    )


def write(row: KickoffSettings, body: out.KickoffSettingsWrite, actor: str) -> None:
    row.tdd_template_url = body.tdd_template_url.strip()
    row.tdd_space_key = body.tdd_space_key.strip().upper()
    row.tdd_parent_url = body.tdd_parent_url.strip()
    row.tdd_sections = list(dict.fromkeys(body.tdd_sections))
    row.jira_project_url = body.jira_project_url.strip()
    row.jira_defaults = body.jira_defaults.model_dump()
    row.analysis_prompt = body.analysis_prompt.strip()
    row.tdd_prompt = body.tdd_prompt.strip()
    row.updated_by = actor


def prefill(row: KickoffSettings) -> dict[str, Any]:
    """What a new analysis inherits. Only the keys that are actually set: an empty default is
    nothing to inherit, and writing one would make a step look answered when it isn't."""
    inherited: dict[str, Any] = {}
    if row.jira_project_url:
        inherited["backlog_target"] = {"url": row.jira_project_url, "project_key": "", "board_id": ""}
    if row.jira_defaults:
        inherited["backlog_options"] = dict(row.jira_defaults)
    if row.analysis_prompt:
        inherited["instructions"] = row.analysis_prompt
    if row.tdd_template_url or row.tdd_sections or row.tdd_space_key:
        inherited["tdd"] = {
            "enabled": False,
            "mode": "sample",
            "template_url": row.tdd_template_url,
            "space_key": row.tdd_space_key,
            "parent_url": row.tdd_parent_url,
            "selected": list(row.tdd_sections or []),
        }
    return inherited
