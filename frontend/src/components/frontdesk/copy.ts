// UX spec 10.9, the FrontDesk copy deck. Strings with braces are functions filled from the API.
import type { Band } from "@/api/types";

export type KioskLanguage = "en" | "es";

const BAND_LABEL: Record<KioskLanguage, Record<Band, string>> = {
  en: { AUTO_LINK: "AUTO-LINK", REVIEW: "REVIEW", KEEP_SEPARATE: "KEEP SEPARATE" },
  es: { AUTO_LINK: "VINCULACIÓN AUTOMÁTICA", REVIEW: "REVISIÓN", KEEP_SEPARATE: "MANTENER SEPARADOS" },
} as const;

export const COPY = {
  en: {
    title: "Welcome. Let's get you checked in.",
    sub: "Type your full name and date of birth. You can write in English or Spanish.",
    disclosure:
      "FrontDesk uses Gemini to read your check-in. A registrar confirms any match to an existing chart.",
    transcript: "TRANSCRIPT",
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
    recorded: "recorded",
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
    field: { name: "Name", dob: "Date of birth", sex: "Sex", address: "Address", phone: "Phone" },
  },
  es: {
    title: "Le damos la bienvenida. Registremos su llegada.",
    sub: "Escriba su nombre completo y su fecha de nacimiento. Puede escribir en español o en inglés.",
    disclosure:
      "FrontDesk usa Gemini para leer su registro. El personal de admisión confirma cualquier coincidencia con un expediente existente.",
    transcript: "CONVERSACIÓN",
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
    recorded: "grabado",
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
    field: {
      name: "Nombre",
      dob: "Fecha de nacimiento",
      sex: "Sexo",
      address: "Dirección",
      phone: "Teléfono",
    },
  },
};

export type KioskCopy = (typeof COPY)["en"];

export type KioskField = keyof KioskCopy["field"];

// Scorer feature ids by prefix, mapped to the five fields the kiosk names (UX 10.9 ev.feature.*).
const FIELD_PATTERNS: [RegExp, KioskField][] = [
  [/^(missing_)?(given|family)/, "name"],
  [/^(missing_)?(dob|birth)/, "dob"],
  [/^(missing_)?sex/, "sex"],
  [/^(missing_)?(address|zip)/, "address"],
  [/^(missing_)?phone/, "phone"],
];

/** The kiosk field a scorer feature belongs to; null for an id it does not know. */
export function kioskField(feature: string): KioskField | null {
  return FIELD_PATTERNS.find(([re]) => re.test(feature))?.[1] ?? null;
}

/** "CLINIC_CSV" reads "Clinic CSV": short all-caps words are acronyms and stay as they are. */
export function sourceSystemLabel(sourceSystem: string): string {
  return sourceSystem
    .split("_")
    .map((w) => (w.length <= 4 ? w : w[0] + w.slice(1).toLowerCase()))
    .join(" ");
}
