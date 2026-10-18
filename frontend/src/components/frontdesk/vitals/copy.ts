// Copy for the optional pulse panel. The estimate never leaves this panel, so nothing here
// promises a clinical use.
import type { KioskLanguage } from "../copy";

export const VITALS_COPY = {
  en: {
    heading: "Pulse (optional)",
    label: "Constructed, non-diagnostic",
    consent:
      "Optional: estimate your pulse with the camera while we look up your record. Nothing is saved or shared.",
    accept: "Estimate my pulse",
    decline: "No thanks",
    declined: "OK. The camera stays off.",
    pickFile: "Test clip (dev only)",
    starting: "Starting the camera...",
    hold: "Hold still, face the light.",
    remaining: (s: number) => `${s} s left`,
    stop: "Stop",
    result: (bpm: number) => `About ${bpm} beats per minute`,
    unsteady: "Couldn't get a steady reading, that's fine.",
    unavailable: "The camera isn't available. That's fine, your check-in continues.",
    preview: "Camera preview",
    footer: "Wellness estimate only. Not saved, not sent to staff, not used for check-in.",
  },
  es: {
    heading: "Pulso (opcional)",
    label: "Construido, no diagnóstico",
    consent:
      "Opcional: calcule su pulso con la cámara mientras buscamos su expediente. No se guarda ni se comparte nada.",
    accept: "Calcular mi pulso",
    decline: "No, gracias",
    declined: "De acuerdo. La cámara sigue apagada.",
    pickFile: "Video de prueba (solo desarrollo)",
    starting: "Encendiendo la cámara...",
    hold: "No se mueva y mire hacia la luz.",
    remaining: (s: number) => `Quedan ${s} s`,
    stop: "Detener",
    result: (bpm: number) => `Aproximadamente ${bpm} latidos por minuto`,
    unsteady: "No se pudo obtener una lectura estable, no pasa nada.",
    unavailable: "La cámara no está disponible. No pasa nada, su registro continúa.",
    preview: "Vista previa de la cámara",
    footer:
      "Solo una estimación de bienestar. No se guarda, no se envía al personal y no se usa para el registro.",
  },
} satisfies Record<KioskLanguage, unknown>;

export type VitalsCopy = (typeof VITALS_COPY)["en"];
