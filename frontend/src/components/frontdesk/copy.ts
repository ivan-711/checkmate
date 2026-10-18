// The FrontDesk copy deck (UX spec 10.9, redesigned with critiques/copy.md). Strings with
// parameters are functions filled from the API. Nothing here names a tool, a policy id, a source
// system code. The patient reads plain words; the kiosk's explicit agent mode remains visible.
import type { Band, PolicyReason } from "@/api/types";
import { FAMILY_FEATURES, FEATURE_LABELS, GIVEN_FEATURES, type NameFeature } from "@/lib/display";

export type KioskLanguage = "en" | "es";

const BAND_LABEL: Record<KioskLanguage, Record<Band, string>> = {
  en: { AUTO_LINK: "AUTO-LINK", REVIEW: "REVIEW", KEEP_SEPARATE: "KEEP SEPARATE" },
  es: { AUTO_LINK: "VÍNCULO AUTOMÁTICO", REVIEW: "REVISIÓN", KEEP_SEPARATE: "MANTENER SEPARADOS" },
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
  token_overlap: ", palabras en común",
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

/** The kiosk's names for the systems a chart can come from, keyed on the stored value (the
 * staff screens keep `sourceSystemLabel`, which the e2e tests read). */
const KIOSK_SOURCE: Record<KioskLanguage, Record<string, string>> = {
  en: { ER_FHIR: "Emergency room", CLINIC_CSV: "Clinic", FRONTDESK_INTAKE: "Kiosk check-in" },
  es: { ER_FHIR: "Urgencias", CLINIC_CSV: "Clínica", FRONTDESK_INTAKE: "Registro en el quiosco" },
};

export const COPY = {
  en: {
    pane: "Patient kiosk",
    language: "Language",
    switched: "Language set to English",
    region: "Check-in conversation",
    title: "Welcome. Let’s get you checked in.",
    sub: "Type your full name and date of birth, in English or Spanish.",
    demoLabel: "Demo line",
    newPatientLabel: "New patient",
    suggestUse: "Use this",
    constructed: "constructed scenario",
    constructedKiosk:
      "This check-in matches a synthetic patient built for the demo. All records are synthetic.",
    you: "You",
    placeholder: "Your name and date of birth",
    reply: "Type a reply",
    send: "Send",
    counter: (n: number) => `${n} of 280`,
    promise: ["FrontDesk gets it ready.", "A registrar confirms."],
    foot: "This demo uses synthetic patients. Please don’t type your own details.",
    wait: "Wait for FrontDesk to finish",
    reading: "Reading your message",
    startOver: "Start over",
    working: "Working on it",
    ready: "Ready",
    stepsLabel: "What FrontDesk did",
    stepRead: "Read your check-in",
    step: {
      search_patients: (k: number) =>
        k === 0
          ? "Searched for an existing chart"
          : k === 1
            ? "Found a chart that may be yours"
            : "Found charts that may be yours",
      propose_new_chart: () => "Asked to open a new chart",
      attach_history: () => "Attached history from the linked chart",
    } as Record<string, (k: number) => string>,
    stepOther: "Tried another step",
    gateStep: {
      HELD: "Checked with the identity gate: held",
      PASSED: "Checked with the identity gate: allowed",
    },
    // The gate's reason codes in words a patient can read; the code itself is for staff screens.
    reason: {
      CANDIDATE_IN_REVIEW_OR_HIGHER: "An existing chart may be yours",
      INCOMPLETE_DEMOGRAPHICS: "More details are needed first",
      UNGROUNDED_FIELD: "A detail was not in what you typed",
      INVALID_ARGUMENTS: "The request was incomplete",
      UNKNOWN_TOOL: "That action is not available here",
      LOOP_GUARD: "Too many repeated steps",
      SESSION_CLOSED: "This check-in is already closed",
      INTAKE_ALREADY_RECORDED: "Your check-in is already recorded",
      ALREADY_LINKED: "Your chart is already linked",
      NO_INTAKE_RECORD: "There is no check-in record yet",
    } satisfies Record<PolicyReason, string> as Record<string, string>,
    reasonFallback: "A staff member will review this",
    // The expanded detail of a step: the ids live here, never in a headline.
    detailTool: "Tool",
    detailDecision: "Gate decision",
    detailLatency: "Latency",
    details: "Details",
    gateLabel: "Identity gate · denied",
    ruleResult: "Rule result",
    gateTitle: "A chart may already be yours",
    gateBody: (score: string) => [
      "FrontDesk asked to open a new chart. The gate denied it because an existing chart matches ",
      score,
      ".",
    ],
    gateHeld: "Held for a registrar. Please have a seat; they’ll confirm it with you.",
    gateReview: "A registrar is looking at it now. Please stay close.",
    gateCandidate: "Possible existing chart",
    gateChart: (last2: string, source: string) => `Chart ••••${last2} · ${source}`,
    gateAutoLinkOff: "Auto-link is off here. A staff member decides.",
    gateHidden: "Values hidden on this screen. A registrar reviews them.",
    gateAnnounce: (score: string, band: string) =>
      `New chart request denied by the identity gate. An existing chart scored ${score}, ${band} band. Sent to a registrar.`,
    noEvidence: "no evidence",
    speaker: "FrontDesk",
    aiAgent: "AI agent",
    automatic: "automatic message",
    agentDown: "FrontDesk could not reach the agent service. Your message was not sent.",
    startFailed: "FrontDesk could not reach the agent service.",
    tryAgain: "Try again",
    doneTitle: (name: string | null) => (name ? `You’re checked in, ${name}.` : "You’re checked in."),
    doneSub:
      "A registrar linked your check-in to your chart. Please have a seat; someone will call your name.",
    doneSteps: [
      "Read your check-in",
      "Held for a registrar, not a new chart",
      "A registrar confirmed your chart",
    ],
    rejectedTitle: (name: string | null) => (name ? `Thank you, ${name}.` : "Thank you."),
    rejected: "A registrar is creating a new chart for you. Please wait to be called.",
    band: BAND_LABEL.en,
    source: KIOSK_SOURCE.en,
    sourceOther: "Another record",
    feature: FEATURE_LABELS,
  },
  es: {
    pane: "Quiosco de pacientes",
    language: "Idioma",
    switched: "Idioma cambiado a español",
    region: "Conversación de registro",
    title: "Le damos la bienvenida. Registremos su llegada.",
    sub: "Escriba su nombre completo y su fecha de nacimiento, en español o en inglés.",
    demoLabel: "Mensaje de demostración",
    newPatientLabel: "Paciente nuevo",
    suggestUse: "Usar este",
    constructed: "caso de demostración",
    constructedKiosk:
      "Este registro corresponde a un paciente sintético creado para la demostración. Todos los registros son sintéticos.",
    you: "Usted",
    placeholder: "Su nombre y fecha de nacimiento",
    reply: "Escriba una respuesta",
    send: "Enviar",
    counter: (n: number) => `${n} de 280`,
    promise: ["FrontDesk lo prepara.", "Admisión lo confirma."],
    foot: "Esta demostración usa pacientes sintéticos. No escriba sus propios datos.",
    wait: "Espere a que FrontDesk termine",
    reading: "Leyendo su mensaje",
    startOver: "Empezar de nuevo",
    working: "Trabajando en ello",
    ready: "Listo",
    stepsLabel: "Lo que hizo FrontDesk",
    stepRead: "Leyó su mensaje",
    step: {
      search_patients: (k: number) =>
        k === 0
          ? "Buscó un expediente existente"
          : k === 1
            ? "Encontró un expediente que podría ser suyo"
            : "Encontró expedientes que podrían ser suyos",
      propose_new_chart: () => "Pidió abrir un expediente nuevo",
      attach_history: () => "Adjuntó el historial del expediente vinculado",
    } as Record<string, (k: number) => string>,
    stepOther: "Intentó otro paso",
    gateStep: {
      HELD: "Consultó el control de identidad: en espera",
      PASSED: "Consultó el control de identidad: permitido",
    },
    reason: {
      CANDIDATE_IN_REVIEW_OR_HIGHER: "Un expediente existente podría ser suyo",
      INCOMPLETE_DEMOGRAPHICS: "Primero se necesitan más datos",
      UNGROUNDED_FIELD: "Un dato no estaba en lo que escribió",
      INVALID_ARGUMENTS: "La solicitud estaba incompleta",
      UNKNOWN_TOOL: "Esa acción no está disponible aquí",
      LOOP_GUARD: "Demasiados pasos repetidos",
      SESSION_CLOSED: "Este registro ya está cerrado",
      INTAKE_ALREADY_RECORDED: "Su registro ya quedó guardado",
      ALREADY_LINKED: "Su expediente ya está vinculado",
      NO_INTAKE_RECORD: "Todavía no hay un registro de llegada",
    } satisfies Record<PolicyReason, string> as Record<string, string>,
    reasonFallback: "Un miembro del personal lo revisará",
    detailTool: "Herramienta",
    detailDecision: "Decisión del control",
    detailLatency: "Latencia",
    details: "Detalles",
    gateLabel: "Control de identidad · denegado",
    ruleResult: "Resultado de regla",
    gateTitle: "Puede que ya tenga un expediente",
    gateBody: (score: string) => [
      "FrontDesk pidió abrir un expediente nuevo. El control lo denegó porque un expediente existente coincide en ",
      score,
      ".",
    ],
    gateHeld: "En espera de admisión. Tome asiento; confirmarán sus datos con usted.",
    gateReview: "Admisión lo está revisando ahora. Por favor, quédese cerca.",
    gateCandidate: "Posible expediente existente",
    gateChart: (last2: string, source: string) => `Expediente ••••${last2} · ${source}`,
    gateAutoLinkOff: "El vínculo automático está desactivado. Decide un miembro del personal.",
    gateHidden: "Los datos están ocultos en esta pantalla. El personal de admisión los revisa.",
    gateAnnounce: (score: string, band: string) =>
      `El control de identidad denegó un expediente nuevo. Un expediente existente obtuvo ${score}, franja ${band}. Enviado al personal de admisión.`,
    noEvidence: "sin evidencia",
    speaker: "FrontDesk",
    aiAgent: "agente de IA",
    automatic: "mensaje automático",
    agentDown: "FrontDesk no pudo conectar con el servicio del agente. Su mensaje no se envió.",
    startFailed: "FrontDesk no pudo conectar con el servicio del agente.",
    tryAgain: "Intentar de nuevo",
    doneTitle: (name: string | null) =>
      name ? `Su llegada está registrada, ${name}.` : "Su llegada está registrada.",
    doneSub: "Admisión vinculó su registro a su expediente. Tome asiento; le llamarán por su nombre.",
    doneSteps: [
      "Leyó su mensaje",
      "En espera de admisión, sin expediente nuevo",
      "Admisión confirmó su expediente",
    ],
    rejectedTitle: (name: string | null) => (name ? `Gracias, ${name}.` : "Gracias."),
    rejected: "El personal de admisión está creando un expediente nuevo para usted. Espere a que le llamen.",
    band: BAND_LABEL.es,
    source: KIOSK_SOURCE.es,
    sourceOther: "Otro registro",
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

/** The patient's name for a chart's source: a place, never a system code. */
export function kioskSourceLabel(sourceSystem: string, t: KioskCopy): string {
  return t.source[sourceSystem] ?? t.sourceOther;
}
