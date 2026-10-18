// UX spec 10.9, the FrontDesk copy deck. Strings with braces are functions filled from the API.
import type { Band } from "@/api/types";
import { FAMILY_FEATURES, FEATURE_LABELS, GIVEN_FEATURES, type NameFeature } from "@/lib/display";

export type KioskLanguage = "en" | "es";

const BAND_LABEL: Record<KioskLanguage, Record<Band, string>> = {
  en: { AUTO_LINK: "AUTO-LINK", REVIEW: "REVIEW", KEEP_SEPARATE: "KEEP SEPARATE" },
  es: { AUTO_LINK: "VINCULACIÓN AUTOMÁTICA", REVIEW: "REVISIÓN", KEEP_SEPARATE: "MANTENER SEPARADOS" },
} as const;

// The registrar rail's evidence labels (lib/display FEATURE_LABELS), in Spanish. The gate card
// lists the rail's rows one for one, so both panes name the same evidence the same way.
const NAME_PART_ES: Record<NameFeature, string> = {
  jw: ", ortografía",
  jw_folded: ", sin contar acentos",
  dl: ", admite erratas",
  dmeta: ", pronunciación",
  nickname: ", diminutivo",
  initial: ", inicial",
  token_overlap: ", partes",
};

function nameLabelsEs(prefix: "given" | "family", name: string, features: readonly NameFeature[]) {
  return Object.fromEntries(features.map((f) => [`${prefix}_${f}`, `${name}${NAME_PART_ES[f]}`]));
}

const FEATURE_LABELS_ES: Record<string, string> = {
  ...nameLabelsEs("given", "Nombre", GIVEN_FEATURES),
  ...nameLabelsEs("family", "Apellido", FAMILY_FEATURES),
  dob_exact: "Fecha de nacimiento",
  dob_day_month_swap: "Día y mes invertidos",
  dob_one_digit_edit: "Fecha de nacimiento, un dígito distinto",
  dob_one_component_off: "Fecha de nacimiento, una parte distinta",
  dob_year_match: "Año de nacimiento",
  sex_match: "Sexo",
  phone_match: "Teléfono",
  address_jaccard: "Dirección",
  zip_match: "Código postal",
  missing_given_name: "Falta el nombre",
  missing_family_name: "Falta el apellido",
  missing_dob: "Falta la fecha de nacimiento",
  missing_sex: "Falta el sexo",
  missing_phone: "Falta el teléfono",
  missing_address: "Falta la dirección",
  missing_zip: "Falta el código postal",
  given_name_jw: "Nombre",
  family_name_jw: "Apellido",
  family_metaphone: "Apellido, pronunciación",
};

export const COPY = {
  en: {
    title: "Welcome. Let's get you checked in.",
    sub: "Type your full name and date of birth. You can write in English or Spanish.",
    disclosure:
      "FrontDesk uses Gemini to read your check-in. A registrar confirms any match to an existing chart.",
    transcript: "TRANSCRIPT",
    agentMode: (mode: string) => `Agent: ${mode}`,
    region: "Check-in conversation",
    empty: "Your conversation will appear here.",
    language: "Language",
    pane: "Patient kiosk",
    switched: "Language set to English",
    startOver: "Start over",
    speaker: "FrontDesk",
    automatic: "automatic message",
    placeholder: "Type your name and date of birth",
    counter: (n: number) => `${n} of 280`,
    helper: "This demo uses synthetic patients. Please don't type your own details.",
    promise: "Nothing is linked to your chart until a staff member approves.",
    heldFinish: "Held for review. No records were linked.",
    verified: "Verified",
    stepsLabel: "What FrontDesk did",
    stepRead: "Read your check-in",
    step: {
      search_patients: "Searched for an existing chart",
      propose_new_chart: "Asked to create a new chart",
      attach_history: "Attached history from the linked chart",
    } as Record<string, string>,
    stepOther: (tool: string) => `Called ${tool}`,
    gateName: "Identity gate",
    factLabel: { HELD: "HELD", PASSED: "PASSED" },
    wait: "Wait for FrontDesk to finish",
    send: "Send",
    reading: "Reading your message",
    suggestLabel: "Try this check-in",
    suggestUse: "Use this",
    constructed: "constructed scenario",
    constructedKiosk:
      "This check-in matches a synthetic patient built for the demo. All records are synthetic.",
    agentDown: "FrontDesk could not reach the agent service. Your message was not sent.",
    startFailed: "FrontDesk could not reach the agent service.",
    tryAgain: "Try again",
    approved: "Your chart is confirmed. Please wait to be called.",
    rejected: "A registrar is creating a new chart for you. Please wait to be called.",
    handoff:
      "I found a chart that may already be yours. A registrar will confirm it with you. Please have a seat.",
    tool: {
      search_patients: (k: number) => `Search existing charts · ${k} ${k === 1 ? "candidate" : "candidates"}`,
      propose_new_chart: () => "Create a new chart",
      attach_history: () => "Attach history from linked chart",
    },
    allowed: "Allowed",
    denied: "Denied by identity gate",
    detailDecision: "Gate decision",
    detailLatency: "Latency",
    gateTitle: "Blocked by identity gate",
    gateDenied: "propose_new_chart was denied.",
    gateReason: (score: string, band: string) => `Reason: an existing chart scored ${score} (${band}).`,
    // Around the policy id, which the card keeps on one line.
    gatePolicy: ["Policy ", ": no new chart when a match scores REVIEW or higher."],
    gateCandidate: "Possible existing chart",
    gateChart: (last2: string, source: string) => `Chart ••••${last2} · ${source}`,
    gateHidden: "Values hidden on this screen. A registrar reviews them.",
    gateHandoff: "Sent to a registrar",
    gateAnnounce: (score: string, band: string) =>
      `New chart request denied by the identity gate. An existing chart scored ${score}, ${band} band. Sent to a registrar.`,
    noEvidence: "no evidence",
    band: BAND_LABEL.en,
    feature: FEATURE_LABELS,
  },
  es: {
    title: "Le damos la bienvenida. Registremos su llegada.",
    sub: "Escriba su nombre completo y su fecha de nacimiento. Puede escribir en español o en inglés.",
    disclosure:
      "FrontDesk usa Gemini para leer su registro. El personal de admisión confirma cualquier coincidencia con un expediente existente.",
    transcript: "CONVERSACIÓN",
    agentMode: (mode: string) => `Agente: ${mode}`,
    region: "Conversación de registro",
    empty: "Su conversación aparecerá aquí.",
    language: "Idioma",
    pane: "QUIOSCO DE PACIENTES",
    switched: "Idioma cambiado a español",
    startOver: "Empezar de nuevo",
    speaker: "FrontDesk",
    automatic: "mensaje automático",
    placeholder: "Escriba su nombre y fecha de nacimiento",
    counter: (n: number) => `${n} de 280`,
    helper: "Esta demostración usa pacientes sintéticos. Por favor, no escriba sus datos personales.",
    promise: "No se vincula nada a su expediente hasta que un miembro del personal lo apruebe.",
    heldFinish: "En espera de revisión. No se vinculó ningún expediente.",
    verified: "Verificado",
    stepsLabel: "Lo que hizo FrontDesk",
    stepRead: "Se leyó su registro",
    step: {
      search_patients: "Se buscó un expediente existente",
      propose_new_chart: "Se pidió crear un expediente nuevo",
      attach_history: "Se adjuntó el historial del expediente vinculado",
    } as Record<string, string>,
    stepOther: (tool: string) => `Se llamó a ${tool}`,
    gateName: "Control de identidad",
    factLabel: { HELD: "EN ESPERA", PASSED: "PERMITIDO" },
    wait: "Espere a que FrontDesk termine",
    send: "Enviar",
    reading: "Leyendo su mensaje",
    suggestLabel: "Pruebe este registro",
    suggestUse: "Usar este",
    constructed: "escenario construido",
    constructedKiosk:
      "Este registro corresponde a un paciente sintético creado para la demostración. Todos los registros son sintéticos.",
    agentDown: "FrontDesk no pudo conectar con el servicio del agente. Su mensaje no se envió.",
    startFailed: "FrontDesk no pudo conectar con el servicio del agente.",
    tryAgain: "Intentar de nuevo",
    approved: "Su expediente está confirmado. Espere a que lo llamen.",
    rejected: "El personal de admisión está creando un expediente nuevo para usted. Espere a que lo llamen.",
    handoff:
      "Encontré un expediente que podría ser suyo. El personal de admisión lo confirmará con usted. Por favor, tome asiento.",
    tool: {
      search_patients: (k: number) =>
        `Buscar expedientes existentes · ${k} ${k === 1 ? "candidato" : "candidatos"}`,
      propose_new_chart: () => "Crear un expediente nuevo",
      attach_history: () => "Adjuntar historial del expediente vinculado",
    },
    allowed: "Permitido",
    denied: "Denegado por el control de identidad",
    detailDecision: "Decisión del control",
    detailLatency: "Latencia",
    gateTitle: "Bloqueado por el control de identidad",
    gateDenied: "Se denegó propose_new_chart.",
    gateReason: (score: string, band: string) => `Motivo: un expediente existente obtuvo ${score} (${band}).`,
    gatePolicy: [
      "Política ",
      ": no se crea un expediente nuevo cuando una coincidencia llega a REVISIÓN o más.",
    ],
    gateCandidate: "Posible expediente existente",
    gateChart: (last2: string, source: string) => `Expediente ••••${last2} · ${source}`,
    gateHidden: "Los datos están ocultos en esta pantalla. El personal de admisión los revisa.",
    gateHandoff: "Enviado al personal de admisión",
    gateAnnounce: (score: string, band: string) =>
      `El control de identidad denegó un expediente nuevo. Un expediente existente obtuvo ${score}, franja ${band}. Enviado al personal de admisión.`,
    noEvidence: "sin evidencia",
    band: BAND_LABEL.es,
    feature: FEATURE_LABELS_ES,
  },
};

export type KioskCopy = (typeof COPY)["en"];

/** "CLINIC_CSV" reads "Clinic CSV": short all-caps words are acronyms and stay as they are. */
export function sourceSystemLabel(sourceSystem: string): string {
  return sourceSystem
    .split("_")
    .map((w) => (w.length <= 4 ? w : w[0] + w.slice(1).toLowerCase()))
    .join(" ");
}
