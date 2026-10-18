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
});
