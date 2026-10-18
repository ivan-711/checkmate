import { describe, expect, it } from "vitest";
import { FEATURE_LABELS } from "@/lib/display";
import { COPY, sourceSystemLabel } from "./copy";

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
  });

  it("reads source systems the way the source cards do", () => {
    expect(sourceSystemLabel("CLINIC_CSV")).toBe("Clinic CSV");
    expect(sourceSystemLabel("ER_FHIR")).toBe("ER FHIR");
  });
  it("carries the trust lines in both languages", () => {
    expect(COPY.en.promise).toBe("Nothing is linked to your chart until a staff member approves.");
    expect(COPY.es.promise).toBe(
      "No se vincula nada a su expediente hasta que un miembro del personal lo apruebe.",
    );
    expect(COPY.en.heldFinish).toBe("Held for review. No records were linked.");
    expect(COPY.es.heldFinish).toBe("En espera de revisión. No se vinculó ningún expediente.");
    expect(COPY.en.ruleResult).toBe("Rule result");
    expect(COPY.es.ruleResult).toBe("Resultado de regla");
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
