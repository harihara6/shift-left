"""Guided project setup — the alternate path to the manual form, never a replacement for it.

Two endpoints do the work, and the split between them is the product rule:

* `POST /onboarding/discover` reads sources and drafts a setup. It creates no project, no
  dashboard and no binding.
* `POST /onboarding/{id}/accept` is where a named person turns the draft into a project. The
  acceptance is recorded on the session and in the audit log.

Discovery reads with the caller's own permissions, so a draft is readable only by the person
who ran it. Acceptance is an ordinary project creation and carries the same rules: the creator
becomes its admin, and nobody else can see it until they are granted access.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import CurrentUser, current_user
from app.db.session import get_session
from app.models.onboarding import OnboardingSession
from app.models.template import ProjectTemplate, Template, WidgetBinding
from app.schemas.onboarding import (
    AcceptRequest,
    AcceptResult,
    BindingOut,
    CandidateOut,
    DiscoverRequest,
    DraftOut,
    SlotOut,
    SourceOut,
    TemplateOut,
)
from app.services import audit, onboarding, projects, templating

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _candidate_out(candidate) -> CandidateOut:
    return CandidateOut(
        id=candidate.id, connector_key=candidate.connector_key, slot=candidate.slot,
        ref=candidate.ref, title=candidate.title, url=candidate.url,
        detail={k: str(v) for k, v in candidate.detail.items()},
        matched_on=list(candidate.matched_on),
    )


def _draft_out(row: OnboardingSession) -> DraftOut:
    return DraftOut(id=row.id, status=row.status, mode=row.mode, accepted_by=row.accepted_by,
                    accepted_at=row.accepted_at, project_id=row.project_id, **row.draft)


def _serialize(draft: onboarding.Draft) -> dict:
    by_slot = {choice.slot: choice for choice in draft.resolution.resolution.slots}
    return DraftOut(
        id=0, status="draft", mode=draft.resolution.mode, hint=draft.hint,
        note=" ".join(filter(None, [draft.note, draft.resolution.note])),
        discovery_available=draft.discovery_available,
        caveats=draft.resolution.caveats,
        project_name=draft.resolution.resolution.project_name,
        project_key=draft.resolution.resolution.project_key,
        owner=draft.resolution.resolution.owner,
        sources=[
            SourceOut(
                connector_key=s.connector_key, connector_name=s.connector_name,
                available=s.available, state=s.state, note=s.note,
                candidates=[_candidate_out(c) for c in s.candidates],
            )
            for s in draft.sources
        ],
        slots=[
            SlotOut(
                slot=slot, candidate=_candidate_out(candidate),
                confidence=by_slot[slot].confidence if slot in by_slot else 0.0,
                rationale=by_slot[slot].rationale if slot in by_slot else "",
            )
            for slot, candidate in draft.filled.items()
        ],
        templates=[
            TemplateOut(
                template_key=t.template_key, name=t.name, perspective=t.perspective,
                propose_enabled=t.propose_enabled, reason=t.reason,
                bindings=[
                    BindingOut(
                        template_key=b.template_key, widget_name=b.widget_name,
                        connector_key=b.connector_key, position=b.position,
                        catalog_query=b.catalog_query, query=b.query,
                        filled_slots=b.filled_slots, unresolved_slots=b.unresolved_slots,
                        leftovers=b.leftovers, validated=b.validated, row_count=b.row_count,
                        note=b.note, ready=b.ready, generic=b.generic,
                    )
                    for b in t.bindings
                ],
            )
            for t in draft.templates
        ],
    ).model_dump(mode="json", exclude={"id", "status", "mode", "accepted_by", "accepted_at",
                                       "project_id"})


@router.post("/discover", response_model=DraftOut, status_code=status.HTTP_201_CREATED)
async def discover(
    body: DiscoverRequest,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> DraftOut:
    """Search every source that can answer to a name, and draft a setup from what came back.

    Creates nothing but the draft itself. If no source can be searched, the response says so
    and the manual form is the path — that is a normal outcome, not a failure.
    """
    draft = await onboarding.discover(session, body.hint.strip())
    await onboarding.validate(session, draft.templates)
    row = OnboardingSession(
        actor=user.email, hint=body.hint.strip(), status="draft",
        mode=draft.resolution.mode, draft=_serialize(draft), note=draft.note,
    )
    session.add(row)
    await audit.record(
        session, actor=user.email, action="discover", resource_type="onboarding_session",
        resource_id=body.hint.strip(),
        detail={"mode": draft.resolution.mode, "slots_resolved": len(draft.filled)},
        note="Read-only — no project, dashboard or binding was created.",
    )
    await session.commit()
    return _draft_out(row)


async def _own_draft(
    session_id: int, user: CurrentUser, session: AsyncSession
) -> OnboardingSession:
    row = await session.get(OnboardingSession, session_id)
    # A draft holds what the actor's own Atlassian permissions could see, so it is theirs. A
    # 404 rather than a 403: an unauthorized caller learns nothing about what exists.
    if row is None or (row.actor != user.email and not user.is_platform_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Onboarding session not found")
    return row


@router.get("/{session_id}", response_model=DraftOut)
async def get_draft(
    session_id: int,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> DraftOut:
    return _draft_out(await _own_draft(session_id, user, session))


@router.post("/{session_id}/accept", response_model=AcceptResult)
async def accept(
    session_id: int,
    body: AcceptRequest,
    user: CurrentUser = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> AcceptResult:
    """Create the project the draft proposed, as edited and accepted by this person.

    The draft counts toward nothing until this call runs: it is what records who accepted it,
    and it is the only place in the flow that writes a project.
    """
    row = await _own_draft(session_id, user, session)
    if row.status == "accepted":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This draft has already been accepted. Run discovery again to propose another project.",
        )

    now = datetime.now(timezone.utc)
    try:
        project = await projects.create(
            session, key=body.key, name=body.name, owner=body.owner, creator=user.email
        )
        project_id = project.id

        enabled: list[str] = []
        for template_key in dict.fromkeys(body.templates):
            template = await session.get(Template, template_key)
            if template is None:
                continue
            await templating.enable(session, project_id, template)
            enabled.append(template_key)
        await session.flush()

        applied, left_empty = await _apply_bindings(session, project_id, enabled, body)

        row.status = "accepted"
        row.accepted_by = user.email
        row.accepted_at = now
        row.project_id = project_id

        await audit.record(
            session, actor=user.email, action="accept_onboarding",
            resource_type="onboarding_session", resource_id=str(row.id), project_id=project_id,
            detail={
                "mode": row.mode, "hint": row.hint, "templates": enabled,
                "bindings_applied": applied, "bindings_left_empty": left_empty,
            },
            note=(
                "A drafted setup counts toward nothing until a named person accepts it. This "
                "entry is that acceptance."
            ),
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Project key already in use") from exc

    return AcceptResult(
        project=await projects.detail(session, project_id),
        templates_enabled=enabled,
        bindings_applied=applied,
        bindings_left_empty=left_empty,
        accepted_by=user.email,
        accepted_at=now,
        note=(
            f"{applied} widget(s) bound from discovered sources; {left_empty} left empty and "
            "rendering Missing until someone binds them. You are this project's admin — grant "
            "access to anyone else who needs it."
        ),
    )


async def _apply_bindings(
    session: AsyncSession, project_id: str, enabled: list[str], body: AcceptRequest
) -> tuple[int, int]:
    """Write the accepted queries onto the copied widgets.

    A widget the person left empty is written empty rather than keeping the catalog's exemplar
    query — an inherited query would point the new project at another team's data and look
    finished doing it.
    """
    rows = (
        await session.execute(
            select(ProjectTemplate).where(
                ProjectTemplate.project_id == project_id,
                ProjectTemplate.template_key.in_(enabled or [""]),
            )
        )
    ).scalars().all()
    accepted = {(b.template_key, b.widget_name): b.query.strip() for b in body.bindings}

    applied = 0
    left_empty = 0
    for parent in rows:
        bindings = (
            await session.execute(
                select(WidgetBinding).where(WidgetBinding.project_template_id == parent.id)
            )
        ).scalars().all()
        for binding in bindings:
            # Every copied widget is set from what was accepted — a widget nobody accepted a
            # query for is emptied, never left holding the catalog's exemplar.
            binding.query = accepted.get((parent.template_key, binding.name), "")
            if binding.query:
                applied += 1
            else:
                left_empty += 1
    return applied, left_empty
