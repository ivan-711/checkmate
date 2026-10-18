"""Off-script reader for REPLAY: typed text that matches no scripted line is read by plain rules.

Used only when the replay adapter has no scripted line for the typed text and
``FRONTDESK_OFFSCRIPT_READER=on``. No model, no network. It answers the loop with the same steps a
model would (``search_patients``, then ``propose_new_chart``), so every write still goes through the
executor and the gate. Every value it passes is the patient's own typed substring and every evidence
quote is that substring; only the birth date value is the ISO form the tool schema requires, and its
quote is what was typed. Each reader step is logged (ids and step kind only, never the patient's
text), and its tool calls carry ``modelCallId = offscript-reader/1``.

Author: Christian Flores (offscript-reader builder).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from backend.frontdesk.model import ErrorStep, ModelRequest, ModelStep, TextStep, ToolCallStep
from backend.frontdesk.replay import ReplayAgentModel
from backend.frontdesk.templates import TEMPLATE_LINE
from backend.policy.args import MONTH_NAMES
from contracts.models.intake import AgentMode
from contracts.models.policy import Language, PolicyReason, ToolName

log = logging.getLogger("checkmate.frontdesk.offscript")

READER_CALL_ID = "offscript-reader/1"  # free-form modelCallId on the audit row; no contract change
_NO_SCRIPT = frozenset({"REPLAY_INPUT_MISMATCH", "REPLAY_DIVERGED"})
MAX_GIVEN_LEN = 60  # contracts/models/policy.py Demographics
MAX_FAMILY_LEN = 80
MAX_PHONE_LEN = 20
MAX_ADDRESS_LEN = 120
MAX_NAME_TOKENS = 4
EARLIEST_BIRTH_YEAR = 1900

REPLIES: dict[Language, dict[str, str]] = {
    Language.EN: {
        "ask_name_dob": "Please tell me your full name and date of birth.",
        "ask_contact": "Please tell me your phone number or your street address.",
        "started": "Thank you, {given}. We have started your registration; a registrar will finish it with you in a moment.",
        "held": "Thank you, {given}. A registrar will confirm your record in a moment.",
    },
    Language.ES: {
        "ask_name_dob": "Por favor, dígame su nombre completo y su fecha de nacimiento.",
        "ask_contact": "Por favor, dígame su número de teléfono o su dirección.",
        "started": "Gracias, {given}. Hemos iniciado su registro; una persona de registro lo termina con usted en un momento.",
        "held": "Gracias, {given}. Una persona de registro va a confirmar su expediente en un momento.",
    },
}
_HELD_REASONS = frozenset(
    {PolicyReason.CANDIDATE_IN_REVIEW_OR_HIGHER, PolicyReason.INTAKE_ALREADY_RECORDED, PolicyReason.ALREADY_LINKED}
)

# ---- extraction rules ---------------------------------------------------------------------------

_NAME_CUE = re.compile(r"\b(?:my name is|i['’]m|i am|me llamo|mi nombre es|soy)\s+", re.IGNORECASE)
_NAME_END = re.compile(r"[,.;\n]|\s+(?:born|nac[ií])", re.IGNORECASE)
_NAME_TOKEN = re.compile(r"^[^\W\d_]+(?:['’\-][^\W\d_]+)*$")
_NOT_A_NAME_START = frozenset(
    {"hi", "hello", "hey", "hola", "buenos", "buenas", "good", "thanks", "thank", "gracias", "yes", "no", "si", "sí",
     "ok", "okay", "my", "mi", "i", "the", "el", "la", "born", "phone"}
)  # fmt: skip
_MONTHS = "|".join(sorted((n for names in MONTH_NAMES.values() for n in names), key=len, reverse=True))
_MONTH_NUMBER = {n: m for m, names in MONTH_NAMES.items() for n in names}
_DATE_PATTERNS = (
    re.compile(rf"\b(?P<d>\d{{1,2}})\s+de\s+(?P<mn>{_MONTHS})\s+(?:de|del)\s+(?P<y>\d{{4}})\b", re.IGNORECASE),
    re.compile(rf"\b(?P<mn>{_MONTHS})\s+(?P<d>\d{{1,2}}),?\s+(?P<y>\d{{4}})\b", re.IGNORECASE),
    re.compile(rf"\b(?P<d>\d{{1,2}})\s+(?P<mn>{_MONTHS}),?\s+(?P<y>\d{{4}})\b", re.IGNORECASE),
    re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})\b"),
    re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})\b"),  # US order: month first
)
_PHONE = re.compile(r"(?<![\d/\-])\(?\d{3}\)?[\s.\-]*\d{3}[\s.\-]*\d{4}(?![\d/\-]?\d)")
_ADDRESS_CUE = re.compile(r"\b(?:i live at|my address is|vivo en)\s+([^,\n]+)", re.IGNORECASE)
_ZIP = re.compile(r"(?<![\d\-/])\d{5}(?![\d\-/])")


@dataclass(frozen=True)
class Field:
    value: str  # what goes into the tool argument
    quote: str  # the patient's exact words, for the evidence block


@dataclass(frozen=True)
class Extracted:
    given_name: Field | None = None
    family_name: Field | None = None
    birth_date: Field | None = None
    phone: Field | None = None
    address_line: Field | None = None
    postal_code: Field | None = None
    name_cued: bool = False

    def _demographics(self) -> dict:
        fields = {
            "givenName": self.given_name,
            "familyName": self.family_name,
            "birthDate": self.birth_date,
            "phone": self.phone,
            "addressLine": self.address_line,
            "postalCode": self.postal_code,
        }
        present = {k: f for k, f in fields.items() if f is not None}
        return {**{k: f.value for k, f in present.items()}, "evidence": {k: f.quote for k, f in present.items()}}

    def search_args(self) -> dict:
        return self._demographics()

    def propose_args(self, language: Language) -> dict:
        return {**self._demographics(), "sex": "UNKNOWN", "preferredLanguage": language.value}


def _name(text: str) -> tuple[Field, Field, bool] | None:
    cues = list(_NAME_CUE.finditer(text))
    for cue in cues:
        split = _split_name(_until_name_end(text[cue.end() :]))
        if split:
            return (*split, True)
    if cues:  # "I'm Ana" names one token only: ask, rather than read "I'm Ana" as a full name
        return None
    lead = _until_name_end(text)
    if lead and lead.split()[0].casefold() not in _NOT_A_NAME_START:
        split = _split_name(lead)
        if split:
            return (*split, False)
    return None


def _until_name_end(rest: str) -> str:
    end = _NAME_END.search(rest)
    return (rest[: end.start()] if end else rest).strip()


def _split_name(candidate: str) -> tuple[Field, Field] | None:
    tokens = candidate.split()
    if not 2 <= len(tokens) <= MAX_NAME_TOKENS or not all(_NAME_TOKEN.match(t) for t in tokens):
        return None
    given, family = candidate.split(None, 1)  # the last token(s) are the family name, as typed
    if len(given) > MAX_GIVEN_LEN or len(family) > MAX_FAMILY_LEN:
        return None
    return Field(given, given), Field(family, family)


def _birth_date(text: str) -> Field | None:
    matches = sorted((m for p in _DATE_PATTERNS for m in p.finditer(text)), key=lambda m: m.start())
    for m in matches:
        parts = m.groupdict()
        month = int(parts["m"]) if parts.get("m") else _MONTH_NUMBER[parts["mn"].casefold()]
        try:
            born = date(int(parts["y"]), month, int(parts["d"]))
        except ValueError:
            continue
        if EARLIEST_BIRTH_YEAR <= born.year <= date.today().year:
            return Field(born.isoformat(), m.group(0))
    return None


def _phone(text: str) -> Field | None:
    m = _PHONE.search(text)
    return Field(m.group(0), m.group(0)) if m and len(m.group(0)) <= MAX_PHONE_LEN else None


def _address(text: str) -> Field | None:
    m = _ADDRESS_CUE.search(text)
    if not m:
        return None
    line = m.group(1).strip().rstrip(".").strip()
    return Field(line, line) if line and len(line) <= MAX_ADDRESS_LEN else None


def _postal_code(text: str) -> Field | None:
    zips = _ZIP.findall(text)
    return Field(zips[-1], zips[-1]) if zips else None


def extract(text: str) -> Extracted:
    name = _name(text)
    return Extracted(
        given_name=name[0] if name else None,
        family_name=name[1] if name else None,
        birth_date=_birth_date(text),
        phone=_phone(text),
        address_line=_address(text),
        postal_code=_postal_code(text),
        name_cued=bool(name and name[2]),
    )


def merge(texts: list[str]) -> Extracted:
    """Earlier turns count: a later message fills or replaces a field, and a cued name ("my name is")
    is never replaced by a bare leading name. Each value still comes from one typed text."""
    merged = Extracted()
    for found in map(extract, texts):
        take_name = found.given_name is not None and (found.name_cued or not merged.name_cued)
        merged = Extracted(
            given_name=found.given_name if take_name else merged.given_name,
            family_name=found.family_name if take_name else merged.family_name,
            birth_date=found.birth_date or merged.birth_date,
            phone=found.phone or merged.phone,
            address_line=found.address_line or merged.address_line,
            postal_code=found.postal_code or merged.postal_code,
            name_cued=found.name_cued if take_name else merged.name_cued,
        )
    return merged


# ---- the reader and the replay wrapper ----------------------------------------------------------


def _text(req: ModelRequest, key: str, given: str = "") -> TextStep:
    reply = REPLIES[req.language][key].format(given=given[:1].upper() + given[1:])
    return TextStep(text=reply, latency_ms=0, mode=AgentMode.REPLAY)


def _call(tool: ToolName, args: dict) -> ToolCallStep:
    return ToolCallStep(
        tool_name=tool.value, args=args, model_call_id=READER_CALL_ID, latency_ms=0, mode=AgentMode.REPLAY
    )


def read_step(req: ModelRequest) -> ModelStep:
    """One deterministic step: ask, search, propose, or answer from the gate's last result."""
    last_user = max(i for i, m in enumerate(req.messages) if m.role == "user")
    results = [m for m in req.messages[last_user + 1 :] if m.role == "function"]
    found = merge([m.text for m in req.messages if m.role == "user" and m.text is not None])
    if not results:
        if found.given_name is None or found.birth_date is None:
            return _text(req, "ask_name_dob")
        if found.phone is None and found.address_line is None:
            return _text(req, "ask_contact")
        return _call(ToolName.SEARCH_PATIENTS, found.search_args())
    last = results[-1]
    status = (last.tool_result or {}).get("status")
    tool = last.tool_call.tool_name if last.tool_call else None
    given = found.given_name.value if found.given_name else ""
    if tool == ToolName.SEARCH_PATIENTS.value and status == "ALLOWED":
        return _call(ToolName.PROPOSE_NEW_CHART, found.propose_args(req.language))
    if tool == ToolName.PROPOSE_NEW_CHART.value and status == "ALLOWED":
        return _text(req, "started", given)
    if (last.tool_result or {}).get("reasonCode") in _HELD_REASONS:
        return _text(req, "held", given)
    return TextStep(text=TEMPLATE_LINE[req.language], latency_ms=0, mode=AgentMode.REPLAY)


class OffscriptReplayModel:
    """The replay adapter first; the reader only for text with no scripted line at this turn."""

    mode: AgentMode = AgentMode.REPLAY

    def __init__(self, inner: ReplayAgentModel) -> None:
        self.inner = inner
        self.transcript_sha256 = inner.transcript_sha256

    def next_step(self, req: ModelRequest) -> ModelStep:
        step = self.inner.next_step(req)
        if not isinstance(step, ErrorStep) or step.kind not in _NO_SCRIPT:
            return step
        try:
            # A divergence inside a scripted turn still degrades; only an unscripted text is read.
            if self.inner.transcript.turn(req.turn_index, req.user_text_folded) is not None:
                return step
            read = read_step(req)
        except Exception:  # the reader never raises to the loop; it degrades like the replay
            log.exception("offscript reader failed turn=%s step=%s", req.turn_index, req.step_index)
            return step
        kind = read.tool_name if isinstance(read, ToolCallStep) else "TEXT"
        log.info(
            "offscript reader session=%s turn=%s step=%s kind=%s", req.session_id, req.turn_index, req.step_index, kind
        )
        return read
