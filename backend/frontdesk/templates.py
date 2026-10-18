"""Deterministic EN/ES text: the degraded-turn template, the ToolResult messages and the banned-phrase check.

The model's text is untrusted (ADR-016 §8). When it claims an effect the gate never produced, or
uses a phrase from the say/never-say list, the turn shows the template instead and the swap is
logged. This is a best-effort list, not a guarantee; the tool card is authoritative.
"""

from __future__ import annotations

import re
import unicodedata

from contracts.models.policy import Language, PolicyOutcome, PolicyReason

TEMPLATE_LINE: dict[Language, str] = {
    Language.ES: "Un momento, una persona de registro le va a ayudar.",
    Language.EN: "One moment, a registrar will help you.",
}

# What the model (and the UI's tool card) is told after each gate decision, by message key.
# Keys follow backend.policy.decide.MESSAGE_KEYS: gate.allow.<tool> and gate.deny.<reason>.
_MESSAGES: dict[str, dict[Language, str]] = {
    "gate.allow.search_patients": {
        Language.EN: "Search completed. Candidates, if any, are listed by reference only.",
        Language.ES: "Búsqueda completada. Los candidatos, si los hay, se listan solo por referencia.",
    },
    "gate.allow.propose_new_chart": {
        Language.EN: "A new chart was created for this intake.",
        Language.ES: "Se creó un expediente nuevo para este registro.",
    },
    "gate.allow.attach_history": {
        Language.EN: "History recorded as patient-reported, unverified.",
        Language.ES: "Antecedentes registrados como reportados por el paciente, sin verificar.",
    },
    "gate.deny.unknown_tool": {
        Language.EN: "That tool does not exist. Use search_patients, propose_new_chart or attach_history.",
        Language.ES: "Esa herramienta no existe. Use search_patients, propose_new_chart o attach_history.",
    },
    "gate.deny.session_closed": {
        Language.EN: "This intake session is closed. A registrar will help the patient.",
        Language.ES: "Esta sesión de registro está cerrada. Una persona de registro ayudará al paciente.",
    },
    "gate.deny.invalid_arguments": {
        Language.EN: "The arguments did not match the tool schema. Fix them and try once more, or ask the patient.",
        Language.ES: "Los argumentos no cumplen el esquema de la herramienta. Corríjalos o pregunte al paciente.",
    },
    "gate.deny.ungrounded_field": {
        Language.EN: "A field was not supported by the patient's words. Only use what the patient typed.",
        Language.ES: "Un campo no está respaldado por las palabras del paciente. Use solo lo que escribió.",
    },
    "gate.deny.loop_guard": {
        Language.EN: "Too many tool calls. Stop and tell the patient a registrar will help.",
        Language.ES: "Demasiadas llamadas a herramientas. Diga al paciente que una persona de registro le ayudará.",
    },
    "gate.deny.incomplete_demographics": {
        Language.EN: "Missing name, date of birth, sex, or a phone or full address. Ask the patient for what is missing.",
        Language.ES: "Faltan nombre, fecha de nacimiento, sexo, o teléfono o dirección completa. Pregunte lo que falta.",
    },
    "gate.deny.intake_already_recorded": {
        Language.EN: "This intake already has recorded demographics. A registrar handles corrections.",
        Language.ES: "Este registro ya tiene datos demográficos. Una persona de registro atiende correcciones.",
    },
    "gate.deny.already_linked": {
        Language.EN: "This patient's record was found and linked. Use attach_history for anything they tell you.",
        Language.ES: "El expediente del paciente fue encontrado y vinculado. Use attach_history para lo que cuente.",
    },
    "gate.deny.candidate_in_review_or_higher": {
        Language.EN: "A registrar must review a possible existing record first. Tell the patient a registrar will confirm.",
        Language.ES: "Una persona de registro debe revisar un posible expediente existente. Dígalo al paciente.",
    },
    "gate.deny.no_intake_record": {
        Language.EN: "There is no intake record yet. Collect the demographics and propose the chart first.",
        Language.ES: "Aún no hay registro de ingreso. Reúna los datos demográficos y proponga el expediente primero.",
    },
}


# backend.policy.decide names the allow keys by the short tool word.
_KEY_ALIASES = {
    "gate.allow.search": "gate.allow.search_patients",
    "gate.allow.propose": "gate.allow.propose_new_chart",
    "gate.allow.attach": "gate.allow.attach_history",
}


def message_for(message_key: str, outcome: PolicyOutcome, reason: PolicyReason | None, language: Language) -> str:
    """Template text for a gate decision; the key wins, the outcome/reason pair is the fallback."""
    entry = _MESSAGES.get(_KEY_ALIASES.get(message_key, message_key))
    if entry is None:
        fallback = (
            f"gate.allow.{message_key}" if outcome == PolicyOutcome.ALLOW else f"gate.deny.{reason.value.lower()}"
        )
        entry = _MESSAGES.get(fallback, {})
    return entry.get(language) or entry.get(Language.EN) or TEMPLATE_LINE[language]


def fold(value: str) -> str:
    """NFKD, strip combining marks, casefold, collapse whitespace (same rule as the grounding check)."""
    stripped = "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped.casefold()).strip()


# Claims of an effect the model cannot know happened, and the say/never-say phrases. Folded form.
EFFECT_CLAIMS: tuple[str, ...] = (
    "created your chart",
    "created a chart",
    "created a new chart",
    "your chart has been created",
    "your chart is created",
    "chart was created",
    "chart has been created",
    "registered you as a new patient",
    "you are now registered",
    "cree su expediente",
    "cree un expediente",
    "cree un nuevo expediente",
    "su expediente fue creado",
    "su expediente ha sido creado",
    "se creo su expediente",
    "se creo un expediente",
    "ya esta registrado como paciente nuevo",
    "lo registre como paciente nuevo",
    "la registre como paciente nuevo",
)
NEVER_SAY: tuple[str, ...] = (
    "would have died",
    "saved a life",
    "saved your life",
    "prevented an adverse event",
    "the ai caught",
    "the ai decides",
    "diagnos",
    "99% accurate",
    "hipaa",
    "production-ready",
    "can't be jailbroken",
    "cannot be jailbroken",
    "real patients",
    "certified",
    "guaranteed",
    "error bound",
    "verified your identity",
    "verified the identity",
    "verifies insurance",
    "triage",
    "vital signs",
    "chatbot",
    "habria muerto",
    "salvo su vida",
    "salvo una vida",
    "diagnost",
    "garantizado",
    "pacientes reales",
    "verifique su identidad",
    "verificamos su identidad",
    "triaje",
    "signos vitales",
)


def banned_phrase(text: str, *, new_chart_created: bool) -> str | None:
    """The first banned phrase in ``text`` (folded), or None. Effect claims are allowed only when the
    turn really produced NEW_CHART_CREATED; never-say phrases are never allowed."""
    folded = fold(text)
    if not new_chart_created:
        for phrase in EFFECT_CLAIMS:
            if phrase in folded:
                return phrase
    for phrase in NEVER_SAY:
        if phrase in folded:
            return phrase
    return None
