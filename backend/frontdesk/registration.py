"""Registration state derived on read from the database, never toggled (ADR-016 §4 notice vs state).

Order, first match wins: LINKED (a handoff pair of this session is LINKED); NEW_CHART (the chart
effect ``chart:v1:{session}`` exists: after a DIFFERENT_PERSON release the allowed propose wins over
RELEASED); PENDING_REGISTRAR (a pair is PROPOSED); RELEASED (pairs exist and all are REJECTED or
REVOKED); NONE.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.frontdesk import store
from backend.frontdesk.executor import chart_effect_key
from contracts.models.common import DecisionStatus
from contracts.models.intake import Registration, RegistrationState

_HANDOFF_PAIRS = text(
    "SELECT cp.id AS pair_id, d.status, em.entity_id FROM candidate_pair cp "
    "JOIN LATERAL (SELECT status FROM match_decision m WHERE m.pair_id = cp.id ORDER BY m.version DESC LIMIT 1) d "
    "ON true LEFT JOIN entity_member em ON em.source_record_id = :intake_record_id "
    "WHERE cp.origin = 'FRONTDESK_HANDOFF' AND cp.intake_session_id = :session_id ORDER BY cp.created_at"
)


def derive(conn: Connection, session_id: UUID) -> Registration:
    session = store.read_session(conn, session_id)
    if session is None or session.intake_record_id is None:
        return Registration(state=RegistrationState.NONE)
    rows = list(conn.execute(_HANDOFF_PAIRS, {"session_id": session_id, "intake_record_id": session.intake_record_id}))
    pair_ids = [r.pair_id for r in rows]
    statuses = {DecisionStatus(r.status) for r in rows}
    entity_id = next((r.entity_id for r in rows if r.entity_id is not None), None)
    if DecisionStatus.LINKED in statuses:
        state = RegistrationState.LINKED
    elif store.has_effect_key(conn, chart_effect_key(session_id)):
        state = RegistrationState.NEW_CHART
    elif DecisionStatus.PROPOSED in statuses:
        state = RegistrationState.PENDING_REGISTRAR
    elif rows and statuses <= {DecisionStatus.REJECTED, DecisionStatus.REVOKED}:
        state = RegistrationState.RELEASED
    else:
        state = RegistrationState.NONE
    return Registration(
        state=state, intake_record_id=session.intake_record_id, handoff_pair_ids=pair_ids, entity_id=entity_id
    )
