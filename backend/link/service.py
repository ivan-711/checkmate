"""Link service: the entity and rule side of approve, reject, revoke and split (ADR-002, ADR-011).

Every function runs on the caller's connection inside the caller's transaction. W3a's
review endpoint writes the decision row first, then calls ``apply_approve`` or
``apply_reject`` with the new decision id. Entities are union-find components of the
current LINKED decisions, rebuilt from scratch on every change; the rule runs over each
affected entity in the same transaction; all SQL values are bound parameters. Events go through W3a's
``backend.events.writer.write_event`` on the same connection; request id, mode and entry
point come from the request context the middleware binds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from backend.events.writer import write_event
from backend.golden.service import load_members, read_alerts, read_entity
from backend.link.union_find import components
from backend.rule.bl_amox_01 import RuleFlag, alert_key, evaluate, to_safety_alert
from backend.rule.resources import parse_member
from backend.rule.terminology import load_terminology
from contracts.models.alerts import AlertStatus, SafetyAlert
from contracts.models.common import ActorType, DecisionStatus, EventType, ReasonCode
from contracts.models.entities import Entity
from contracts.models.pairs import MergePreview
from contracts.version import RULE_ID, RULE_VERSION

# One fixed key for the whole link graph: every rebuild of the union-find serializes on it
# for the rest of the transaction, so no approve can read edges another approve is writing.
LINK_GRAPH_LOCK_KEY = 0x434B4D4C  # "CKML"
_LOCK_GRAPH = text("SELECT pg_advisory_xact_lock(:key)")


class LinkError(ValueError):
    """The decision row does not say what the caller claims (wrong pair or status)."""


class CannotLinkConflict(LinkError):
    """A not_a_match row sits inside the would-be entity: the API answers 409 CANNOT_LINK_CONFLICT.
    ``public_message`` is what the client sees; the exception text (record ids) stays server-side."""

    public_message = "the link would join records a registrar marked as different people"


class AlreadyLinked(CannotLinkConflict):
    """A DIFFERENT_PERSON reject of a pair whose records already share an entity through another
    approved link. Recording not_a_match there would leave the entity linked and make every later
    approve in it a conflict, so the reject is refused (lead decision) and nothing is written."""

    public_message = (
        "the two records are already linked through another approved link; undoing that is a split, not a reject"
    )


@dataclass(frozen=True)
class SplitResult:
    entities: list[Entity]
    revoked_decision_ids: list[UUID] = field(default_factory=list)
    retracted_alert_ids: list[UUID] = field(default_factory=list)


_DECISION = text(
    "SELECT md.id, md.pair_id, md.version, md.status, md.actor, md.actor_type, md.reason_code, "
    "cp.record_a_id, cp.record_b_id FROM match_decision md JOIN candidate_pair cp ON cp.id = md.pair_id "
    "WHERE md.id = :decision_id"
)
# An approved edge is a current LINKED decision written by a registrar. ADR-015 says only humans
# create LINKED; this clause makes the identity gate hold even if a future writer forgets that.
APPROVING_ACTOR_TYPE = ActorType.REGISTRAR
_LINKED_EDGES = text(
    "SELECT cp.id AS pair_id, cp.record_a_id, cp.record_b_id FROM candidate_pair cp "
    "JOIN LATERAL (SELECT status, actor_type FROM match_decision WHERE pair_id = cp.id ORDER BY version DESC LIMIT 1) d "
    "ON true WHERE d.status = 'LINKED' AND d.actor_type = :actor_type"
)
_INGEST_ORDER = text("SELECT id FROM source_record WHERE id = ANY(:ids) ORDER BY ingested_at, id")
_MEMBERSHIP = text("SELECT entity_id, source_record_id FROM entity_member WHERE source_record_id = ANY(:ids)")
_ENTITY_MEMBERS = text("SELECT source_record_id FROM entity_member WHERE entity_id = :entity_id")
_NOT_A_MATCH_INSIDE = text(
    "SELECT record_a_id, record_b_id FROM not_a_match WHERE record_a_id = ANY(:ids) AND record_b_id = ANY(:ids)"
)
_INSERT_ENTITY = text("INSERT INTO entity (id, version) VALUES (:id, 1)")
_BUMP_ENTITY = text("UPDATE entity SET version = version + 1 WHERE id = :id")
_DELETE_MEMBERS = text("DELETE FROM entity_member WHERE source_record_id = ANY(:ids)")
_INSERT_MEMBER = text("INSERT INTO entity_member (entity_id, source_record_id) VALUES (:entity_id, :record_id)")
_MOVE_ALERTS = text("UPDATE safety_alert SET entity_id = :keeper WHERE entity_id = ANY(:ids)")
_MOVE_ALERTS_WITH_RECORDS = text(
    "UPDATE safety_alert SET entity_id = :new_id WHERE entity_id = :old_id "
    "AND allergy_record_id = ANY(:ids) AND order_record_id = ANY(:ids)"
)
_DELETE_EMPTY_ENTITIES = text(
    "DELETE FROM entity WHERE id = ANY(:ids) AND NOT EXISTS (SELECT 1 FROM entity_member em WHERE em.entity_id = entity.id)"
)
_INSERT_NOT_A_MATCH = text(
    "INSERT INTO not_a_match (record_a_id, record_b_id, decision_id, actor) VALUES (:a, :b, :decision_id, :actor) "
    "ON CONFLICT DO NOTHING"
)
_INSERT_ALERT = text(
    "INSERT INTO safety_alert (id, entity_id, rule_id, rule_version, tier, allergy_record_id, allergy_resource_id, "
    "order_record_id, order_resource_id, revealed_by_merge, severity, status, card_text, citation, "
    "constructed_scenario, identified_at) VALUES (:id, :entity_id, :rule_id, :rule_version, :tier, :allergy_record_id, "
    ":allergy_resource_id, :order_record_id, :order_resource_id, :revealed_by_merge, :severity, :status, :card_text, "
    "CAST(:citation AS jsonb), :constructed_scenario, :identified_at)"
)
_RETRACT_ALERT = text("UPDATE safety_alert SET status = 'RETRACTED', retracted_at = :at WHERE id = :id")
_LOCK_PAIR = text("SELECT id FROM candidate_pair WHERE id = :pair_id FOR UPDATE")
_INSERT_REVOKED_DECISION = text(
    "INSERT INTO match_decision (id, pair_id, version, logit, p, raw_score, band, negative_rules_fired, "
    "evidence_snapshot, status, actor, actor_type, reason_code, note, scorer_version, threshold_set_id) "
    "SELECT :id, pair_id, version + 1, logit, p, raw_score, band, negative_rules_fired, evidence_snapshot, 'REVOKED', "
    ":actor, :actor_type, :reason_code, :note, scorer_version, threshold_set_id "
    "FROM match_decision WHERE pair_id = :pair_id ORDER BY version DESC LIMIT 1"
)


def _now() -> datetime:
    return datetime.now(UTC)


def lock_link_graph(conn: Connection) -> None:
    """Taken first by every writer; released when the caller's transaction ends."""
    conn.execute(_LOCK_GRAPH, {"key": LINK_GRAPH_LOCK_KEY})


def _decision(conn: Connection, pair_id: UUID, decision_id: UUID, expected: DecisionStatus):
    row = conn.execute(_DECISION, {"decision_id": decision_id}).mappings().first()
    if row is None or row["pair_id"] != pair_id:
        raise LinkError(f"decision {decision_id} is not a decision on pair {pair_id}")
    if row["status"] != expected.value:
        raise LinkError(f"decision {decision_id} is {row['status']}, expected {expected.value}")
    return row


@dataclass(frozen=True)
class Actor:
    """Who acted, copied onto every event the service writes (the decision row's actor, or the splitter)."""

    actor: str
    actor_type: ActorType


def _actor(row) -> Actor:
    return Actor(actor=row["actor"], actor_type=ActorType(row["actor_type"]))


def _event(conn: Connection, who: Actor, event_type: EventType, **fields) -> None:
    write_event(conn, event_type=event_type, actor=who.actor, actor_type=who.actor_type, **fields)


def _linked_edges(conn: Connection) -> list[tuple[UUID, UUID, UUID]]:
    rows = conn.execute(_LINKED_EDGES, {"actor_type": APPROVING_ACTOR_TYPE.value}).mappings()
    return [(r["record_a_id"], r["record_b_id"], r["pair_id"]) for r in rows]


def _ingest_order(conn: Connection, ids: set[UUID]) -> list[UUID]:
    return [r[0] for r in conn.execute(_INGEST_ORDER, {"ids": list(ids)})]


def _membership(conn: Connection, ids: set[UUID]) -> dict[UUID, UUID]:
    return {r["source_record_id"]: r["entity_id"] for r in conn.execute(_MEMBERSHIP, {"ids": list(ids)}).mappings()}


# Entity membership ----------------------------------------------------------------------


def _merge_component(conn: Connection, component: set[UUID]) -> tuple[UUID, list[UUID], bool]:
    """Put every record of one component under one entity. The entity holding the
    earliest-ingested member keeps its id (ADR-002); the others are absorbed and deleted.
    Returns (keeper, absorbed entity ids, whether membership changed)."""
    order = _ingest_order(conn, component)
    membership = _membership(conn, component)
    rank = {rid: i for i, rid in enumerate(order)}
    entities = sorted(
        {e for e in membership.values()}, key=lambda e: min(rank[r] for r, ent in membership.items() if ent == e)
    )
    if entities:
        keeper = entities[0]
    else:
        keeper = uuid4()
        conn.execute(_INSERT_ENTITY, {"id": keeper})
    absorbed = entities[1:]
    to_add = [rid for rid in order if membership.get(rid) != keeper]
    if to_add:
        if absorbed:
            conn.execute(_MOVE_ALERTS, {"keeper": keeper, "ids": absorbed})
        conn.execute(_DELETE_MEMBERS, {"ids": to_add})
        for rid in to_add:
            conn.execute(_INSERT_MEMBER, {"entity_id": keeper, "record_id": rid})
        if absorbed:
            conn.execute(_DELETE_EMPTY_ENTITIES, {"ids": absorbed})
        if entities:
            conn.execute(_BUMP_ENTITY, {"id": keeper})
    return keeper, absorbed, bool(to_add)


def _split_entity(conn: Connection, entity_id: UUID, groups: list[frozenset[UUID]]) -> list[UUID]:
    """Partition one entity's members. The group with the earliest-ingested member keeps
    the id; every other group becomes a new entity (singletons included, so the UI can
    navigate to each side)."""
    order = _ingest_order(conn, set().union(*groups))
    groups = sorted(groups, key=lambda g: min(order.index(r) for r in g))
    conn.execute(_BUMP_ENTITY, {"id": entity_id})
    result = [entity_id]
    for group in groups[1:]:
        new_id = uuid4()
        conn.execute(_INSERT_ENTITY, {"id": new_id})
        conn.execute(_DELETE_MEMBERS, {"ids": list(group)})
        for rid in group:
            conn.execute(_INSERT_MEMBER, {"entity_id": new_id, "record_id": rid})
        # an alert whose allergy and order both move keeps its id and its approved path
        conn.execute(_MOVE_ALERTS_WITH_RECORDS, {"new_id": new_id, "old_id": entity_id, "ids": list(group)})
        result.append(new_id)
    return result


# Rule run and alert reconciliation --------------------------------------------------------

# Why a flag was retracted: the rule no longer finds an approved path between the allergy record
# and the order record (a split or revocation removed it). An enum, never prose (writer rule).
RETRACT_REASON_NO_APPROVED_PATH = "NO_APPROVED_PATH"


def _raise_alert(conn: Connection, who: Actor, entity_id: UUID, flag: RuleFlag, at: datetime) -> SafetyAlert:
    alert = to_safety_alert(flag, alert_id=uuid4(), entity_id=entity_id, identified_at=at)
    term = load_terminology()
    conn.execute(
        _INSERT_ALERT,
        {
            "id": alert.id,
            "entity_id": entity_id,
            "rule_id": RULE_ID,
            "rule_version": RULE_VERSION,
            "tier": alert.tier.value,
            "allergy_record_id": alert.allergy_ref.source_record_id,
            "allergy_resource_id": alert.allergy_ref.resource_id,
            "order_record_id": alert.order_ref.source_record_id,
            "order_resource_id": alert.order_ref.resource_id,
            "revealed_by_merge": alert.revealed_by_merge,
            "severity": alert.severity,
            "status": alert.status.value,
            "card_text": alert.card_text,
            "citation": json.dumps(alert.citation.model_dump()) if alert.citation else None,
            "constructed_scenario": alert.constructed_scenario,
            "identified_at": at,
        },
    )
    _event(
        conn,
        who,
        EventType.ALERT_RAISED,
        entity_id=entity_id,
        outcome=f"TIER_{alert.tier.value}",
        payload={
            "alertId": str(alert.id),
            "ruleId": RULE_ID,
            "ruleVersion": RULE_VERSION,
            "tier": alert.tier.value,
            "classId": term.class_id,
            "rxnavVersion": term.rxnav_version,
            # internal record UUIDs, never FHIR resource ids: those have no length bound and the writer
            # refuses strings over 64 characters (ids and enums only); the full refs live on the alert row
            "revealedByMerge": alert.revealed_by_merge,
            "allergyRecordId": str(alert.allergy_ref.source_record_id),
            "orderRecordId": str(alert.order_ref.source_record_id),
            "constructedScenario": alert.constructed_scenario,
        },
    )
    return alert


def _retract_alert(conn: Connection, who: Actor, alert: SafetyAlert, at: datetime) -> None:
    conn.execute(_RETRACT_ALERT, {"id": alert.id, "at": at})
    _event(
        conn,
        who,
        EventType.ALERT_RETRACTED,
        entity_id=alert.entity_id,
        outcome=f"TIER_{alert.tier.value}",
        payload={
            "alertId": str(alert.id),
            "ruleId": RULE_ID,
            "ruleVersion": RULE_VERSION,
            "reason": RETRACT_REASON_NO_APPROVED_PATH,
        },
    )


def reconcile_alerts(conn: Connection, who: Actor, entity_id: UUID) -> tuple[list[SafetyAlert], list[UUID]]:
    """Run BL-AMOX-01 over the entity and make safety_alert agree with it: flags the rule
    no longer supports are RETRACTED, new ones are raised, matching ones are kept.
    Returns (current PRELIMINARY alerts, retracted alert ids)."""
    at = _now()
    wanted = {flag.key: flag for flag in evaluate(load_members(conn, entity_id))}
    retracted: list[UUID] = []
    kept: set[tuple] = set()
    for alert in read_alerts(conn, entity_id, status=AlertStatus.PRELIMINARY):
        key = alert_key(
            alert.allergy_ref.source_record_id,
            alert.allergy_ref.resource_id,
            alert.order_ref.source_record_id,
            alert.order_ref.resource_id,
            alert.tier,
        )
        if key in wanted:
            kept.add(key)
        else:
            _retract_alert(conn, who, alert, at)
            retracted.append(alert.id)
    for key, flag in wanted.items():
        if key not in kept:
            _raise_alert(conn, who, entity_id, flag, at)
    return read_alerts(conn, entity_id, status=AlertStatus.PRELIMINARY), retracted


# Public seam -----------------------------------------------------------------------------


def apply_approve(conn: Connection, pair_id: UUID, decision_id: UUID) -> tuple[Entity, list[SafetyAlert]]:
    """After the LINKED decision row exists: rebuild the component, write the entity and
    its members, append ENTITY_MERGED, run the rule, raise or retract alerts."""
    lock_link_graph(conn)
    row = _decision(conn, pair_id, decision_id, DecisionStatus.LINKED)
    if row["actor_type"] != APPROVING_ACTOR_TYPE.value:  # spec section 5 row 13: no human approval, no link
        raise LinkError(
            f"decision {decision_id} is LINKED by {row['actor']}; only a registrar's approval links records"
        )
    who = _actor(row)
    edges = _linked_edges(conn)
    component = set(
        components([(a, b) for a, b, _ in edges], [row["record_a_id"], row["record_b_id"]])[row["record_a_id"]]
    )
    conflicts = conn.execute(_NOT_A_MATCH_INSIDE, {"ids": list(component)}).all()
    if conflicts:
        raise CannotLinkConflict(f"not_a_match inside the would-be entity: {[(str(a), str(b)) for a, b in conflicts]}")
    keeper, absorbed, changed = _merge_component(conn, component)
    if changed:  # a retried approve changes nothing and logs nothing
        _event(
            conn,
            who,
            EventType.ENTITY_MERGED,
            entity_id=keeper,
            pair_id=pair_id,
            decision_id=decision_id,
            outcome="MERGED",
            payload={
                "memberCount": len(component),
                "absorbedEntityIds": [str(e) for e in absorbed],
                "linkedEdgeCount": sum(1 for a, b, _ in edges if a in component and b in component),
            },
        )
    alerts, _ = reconcile_alerts(conn, who, keeper)
    entity = read_entity(conn, keeper)
    assert entity is not None
    return entity, alerts


def apply_reject(conn: Connection, pair_id: UUID, decision_id: UUID) -> None:
    """A REJECTED decision changes no entity and the rule stays silent. DIFFERENT_PERSON
    remembers the pair in not_a_match (idempotent); INSUFFICIENT_EVIDENCE writes nothing.
    Raises AlreadyLinked for a DIFFERENT_PERSON reject of records that already share an entity:
    the caller's transaction rolls back, so the decision and its not_a_match row are not written."""
    lock_link_graph(conn)
    row = _decision(conn, pair_id, decision_id, DecisionStatus.REJECTED)
    if row["reason_code"] == ReasonCode.DIFFERENT_PERSON.value:
        membership = _membership(conn, {row["record_a_id"], row["record_b_id"]})
        if len(membership) == 2 and len(set(membership.values())) == 1:
            raise AlreadyLinked(f"pair {pair_id}: both records are members of entity {next(iter(membership.values()))}")
        conn.execute(
            _INSERT_NOT_A_MATCH,
            {"a": row["record_a_id"], "b": row["record_b_id"], "decision_id": decision_id, "actor": row["actor"]},
        )


def _regroup(
    conn: Connection,
    who: Actor,
    entity_id: UUID,
    *,
    pair_id: UUID | None,
    decision_id: UUID | None,
    revoked: list[UUID],
    linked_edges: list[tuple[UUID, UUID, UUID]],
) -> SplitResult:
    """After edges were revoked: regroup the entity's members by the remaining LINKED
    edges; ENTITY_SPLIT is written only when the entity actually came apart."""
    members = {r[0] for r in conn.execute(_ENTITY_MEMBERS, {"entity_id": entity_id})}
    edges = [(a, b) for a, b, _ in linked_edges if a in members and b in members]
    groups = list({c for c in components(edges, members).values()})
    entity_ids = [entity_id]
    if len(groups) > 1:
        entity_ids = _split_entity(conn, entity_id, groups)
        _event(
            conn,
            who,
            EventType.ENTITY_SPLIT,
            entity_id=entity_id,
            pair_id=pair_id,
            decision_id=decision_id,
            outcome="SPLIT",
            payload={
                "resultingEntityIds": [str(e) for e in entity_ids],
                "revokedDecisionIds": [str(d) for d in revoked],
            },
        )
    retracted: list[UUID] = []
    entities: list[Entity] = []
    for eid in entity_ids:
        _, gone = reconcile_alerts(conn, who, eid)
        retracted.extend(gone)
        entity = read_entity(conn, eid)
        assert entity is not None
        entities.append(entity)
    return SplitResult(entities=entities, revoked_decision_ids=revoked, retracted_alert_ids=retracted)


def apply_revoke(conn: Connection, pair_id: UUID, decision_id: UUID) -> SplitResult | None:
    """After a REVOKED decision row exists: recompute the entity's components and retract
    flags that lost their approved path. None when neither record is in an entity."""
    lock_link_graph(conn)
    row = _decision(conn, pair_id, decision_id, DecisionStatus.REVOKED)
    who = _actor(row)
    if row["reason_code"] == ReasonCode.DIFFERENT_PERSON.value:
        conn.execute(
            _INSERT_NOT_A_MATCH,
            {"a": row["record_a_id"], "b": row["record_b_id"], "decision_id": decision_id, "actor": row["actor"]},
        )
    membership = _membership(conn, {row["record_a_id"], row["record_b_id"]})
    if not membership:
        return None
    entity_id = next(iter(membership.values()))
    return _regroup(
        conn,
        who,
        entity_id,
        pair_id=pair_id,
        decision_id=decision_id,
        revoked=[decision_id],
        linked_edges=_linked_edges(conn),
    )


def apply_split(
    conn: Connection,
    entity_id: UUID,
    source_record_ids: list[UUID],
    *,
    actor: str,
    actor_type: ActorType = ActorType.REGISTRAR,
    reason_code: ReasonCode,
    note: str | None = None,
) -> SplitResult:
    """Scaffold for Q4.2 (POST /entities/{id}/splits): move ``source_record_ids`` out of
    the entity by revoking every LINKED edge that crosses the partition (ADR-002)."""
    lock_link_graph(conn)
    members = {r[0] for r in conn.execute(_ENTITY_MEMBERS, {"entity_id": entity_id})}
    side = set(source_record_ids)
    if not members:
        raise LinkError(f"entity {entity_id} has no members")
    if not side or not side < members:
        raise LinkError("sourceRecordIds must be a non-empty proper subset of the entity's members")
    who = Actor(actor=actor, actor_type=actor_type)
    revoked: list[UUID] = []
    edges = _linked_edges(conn)
    remaining: list[tuple[UUID, UUID, UUID]] = []
    for a, b, pair_id in edges:
        crosses = a in members and b in members and (a in side) != (b in side)
        if not crosses:
            remaining.append((a, b, pair_id))
            continue
        decision_id = uuid4()
        conn.execute(_LOCK_PAIR, {"pair_id": pair_id})  # same lock as the review path: versions never collide
        conn.execute(
            _INSERT_REVOKED_DECISION,
            {
                "id": decision_id,
                "pair_id": pair_id,
                "actor": actor,
                "actor_type": actor_type.value,
                "reason_code": reason_code.value,
                "note": note,
            },
        )
        _event(
            conn,
            who,
            EventType.LINK_REVOKED,
            entity_id=entity_id,
            pair_id=pair_id,
            decision_id=decision_id,
            outcome=reason_code.value,
            reason_code=reason_code.value,
            payload={"reasonCode": reason_code.value},
        )
        if reason_code == ReasonCode.DIFFERENT_PERSON:
            conn.execute(_INSERT_NOT_A_MATCH, {"a": a, "b": b, "decision_id": decision_id, "actor": actor})
        revoked.append(decision_id)
    return _regroup(conn, who, entity_id, pair_id=None, decision_id=None, revoked=revoked, linked_edges=remaining)


# W3a seam additions (ported from W3a's stand-in; same signatures the pair and review routes call) --

_PAIR_RECORDS = text("SELECT record_a_id, record_b_id FROM candidate_pair WHERE id = :pair_id")
_RECORDS_BY_ID = text(
    "SELECT id, source_system, source_local_id, kind, raw_payload, is_constructed, ingested_at "
    "FROM source_record WHERE id = ANY(:ids) ORDER BY ingested_at, id"
)


def _pair_records(conn: Connection, pair_id: UUID) -> tuple[UUID, UUID]:
    row = conn.execute(_PAIR_RECORDS, {"pair_id": pair_id}).mappings().one()
    return row["record_a_id"], row["record_b_id"]


def preview_approve(conn: Connection, pair_id: UUID) -> MergePreview:
    """The entity an approve of this pair would produce and whether BL-AMOX-01 would fire over it.
    Read-only: the would-be component is the current LINKED graph plus this pair's edge."""
    a, b = _pair_records(conn, pair_id)
    edges = [(x, y) for x, y, _ in _linked_edges(conn)] + [(a, b)]
    component = set(components(edges, [a, b])[a])
    membership = _membership(conn, component)
    entity_id: UUID | None = None
    if membership:  # the entity holding the earliest-ingested member keeps its id (ADR-002)
        rank = {rid: i for i, rid in enumerate(_ingest_order(conn, component))}
        entity_id = min(
            set(membership.values()), key=lambda e: min(rank[r] for r, ent in membership.items() if ent == e)
        )
    rows = conn.execute(_RECORDS_BY_ID, {"ids": list(component)}).mappings().all()
    members = [
        parse_member(
            source_record_id=r["id"],
            source_system=r["source_system"],
            source_local_id=r["source_local_id"],
            kind=r["kind"],
            is_constructed=r["is_constructed"],
            ingested_at=r["ingested_at"],
            raw_payload=r["raw_payload"],
        )
        for r in rows
    ]
    return MergePreview(
        entity_id_if_approved=entity_id,
        member_count_if_approved=len(component),
        alert_would_fire=bool(evaluate(members)),
    )


def entity_for_pair(conn: Connection, pair_id: UUID) -> Entity | None:
    """The entity a LINKED pair belongs to (entity_member lookup); None while its records are unlinked."""
    a, _ = _pair_records(conn, pair_id)
    membership = _membership(conn, {a})
    return read_entity(conn, membership[a]) if membership else None
