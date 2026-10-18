import { describe, expect, it } from "vitest";
import { FEATURE_LABELS } from "@/lib/display";
import { COPY, kioskSourceLabel, sourceSystemLabel } from "./copy";

/** Every string the deck holds, functions called with sample values, so a scan covers them all. */
function strings(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (typeof value === "function") return strings(value("1.00", "x", 2));
  if (Array.isArray(value)) return value.flatMap(strings);
  if (value && typeof value === "object") return Object.values(value).flatMap(strings);
  return [];
}

describe("FrontDesk copy", () => {
  it("names every feature the registrar rail names, with the rail's words in English", () => {
    expect(COPY.en.feature).toBe(FEATURE_LABELS);
    expect(Object.keys(COPY.es.feature).sort()).toEqual(Object.keys(FEATURE_LABELS).sort());
    expect(COPY.es.feature.given_jw_folded).toBe("Nombre, sin contar acentos");
    expect(COPY.es.feature.family_dmeta).toBe("Apellido, pronunciación");
    expect(COPY.es.feature).not.toHaveProperty("family_nickname"); // given names only, as in the rail
  });

  it("has the same keys in English and Spanish", () => {
    expect(Object.keys(COPY.es).sort()).toEqual(Object.keys(COPY.en).sort());
    expect(COPY.es.feature.dob_exact).toBe("Fecha de nacimiento");
    expect(COPY.es.band.REVIEW).toBe("REVISIÓN");
    expect(COPY.es.band.AUTO_LINK).toBe("VÍNCULO AUTOMÁTICO");
  });

  it("reads source systems the way the source cards do, and in plain words on the kiosk", () => {
    expect(sourceSystemLabel("CLINIC_CSV")).toBe("Clinic CSV");
    expect(sourceSystemLabel("ER_FHIR")).toBe("ER FHIR");
    expect(kioskSourceLabel("ER_FHIR", COPY.en)).toBe("Emergency room");
    expect(kioskSourceLabel("ER_FHIR", COPY.es)).toBe("Urgencias");
    expect(kioskSourceLabel("CLINIC_CSV", COPY.es)).toBe("Clínica");
    expect(kioskSourceLabel("FRONTDESK_INTAKE", COPY.en)).toBe("Kiosk check-in");
    expect(kioskSourceLabel("SOMETHING_ELSE", COPY.en)).toBe("Another record");
  });

  it("carries the promise, the gate card and the done state in both languages", () => {
    expect(COPY.en.promise).toEqual(["FrontDesk gets it ready.", "A registrar confirms."]);
    expect(COPY.es.promise).toEqual(["FrontDesk lo prepara.", "Admisión lo confirma."]);
    expect(COPY.en.gateTitle).toBe("A chart may already be yours");
    expect(COPY.es.gateTitle).toBe("Puede que ya tenga un expediente");
    expect(COPY.en.gateHeld).toBe("Held for a registrar. Please have a seat; they’ll confirm it with you.");
    expect(COPY.es.gateHeld).toBe("En espera de admisión. Tome asiento; confirmarán sus datos con usted.");
    expect(COPY.en.doneTitle("Sofia")).toBe("You’re checked in, Sofia.");
    expect(COPY.en.doneTitle(null)).toBe("You’re checked in.");
    expect(COPY.es.doneTitle("Sofia")).toBe("Su llegada está registrada, Sofia.");
    expect(COPY.es.doneTitle(null)).toBe("Su llegada está registrada.");
  });

  it("puts no machine name in front of the patient: no snake_case ids, policy ids or mode codes", () => {
    for (const lang of ["en", "es"] as const) {
      const { feature: _feature, band: _band, ...deck } = COPY[lang];
      for (const text of strings(deck)) {
        expect(text, text).not.toMatch(/\b[a-z]+_[a-z_]+\b|frontdesk-gate|\bREPLAY\b|\bLIVE\b|\bLOCAL\b/);
        expect(text, text).not.toMatch(/—|!/); // UX §5: no em dashes, no exclamation points
      }
    }
  });

  it("says every gate reason in plain words in both languages, with a neutral fallback", () => {
    const reasons = [
      "UNKNOWN_TOOL",
      "SESSION_CLOSED",
      "INVALID_ARGUMENTS",
      "UNGROUNDED_FIELD",
      "LOOP_GUARD",
      "INCOMPLETE_DEMOGRAPHICS",
      "INTAKE_ALREADY_RECORDED",
      "ALREADY_LINKED",
      "CANDIDATE_IN_REVIEW_OR_HIGHER",
      "NO_INTAKE_RECORD",
    ];
    for (const lang of ["en", "es"] as const) {
      expect(Object.keys(COPY[lang].reason).sort()).toEqual([...reasons].sort());
      for (const text of Object.values(COPY[lang].reason)) expect(text).not.toMatch(/[A-Z]{2,}_/);
      expect(COPY[lang].reasonFallback).toBeTruthy();
    }
    expect(COPY.en.reason.CANDIDATE_IN_REVIEW_OR_HIGHER).toBe("An existing chart may be yours");
    expect(COPY.es.reason.CANDIDATE_IN_REVIEW_OR_HIGHER).toBe("Un expediente existente podría ser suyo");
  });
});
