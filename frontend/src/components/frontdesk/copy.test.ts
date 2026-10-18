import { describe, expect, it } from "vitest";
import { COPY, kioskField, sourceSystemLabel } from "./copy";

describe("FrontDesk copy", () => {
  it("maps scorer features to the five fields the kiosk names", () => {
    expect(kioskField("given_jw_folded")).toBe("name");
    expect(kioskField("family_metaphone")).toBe("name");
    expect(kioskField("dob_day_month_swap")).toBe("dob");
    expect(kioskField("missing_phone")).toBe("phone");
    expect(kioskField("zip_match")).toBe("address");
    expect(kioskField("sex_match")).toBe("sex");
    expect(kioskField("something_new")).toBeNull();
  });

  it("has the same keys in English and Spanish", () => {
    expect(Object.keys(COPY.es).sort()).toEqual(Object.keys(COPY.en).sort());
    expect(COPY.es.field.dob).toBe("Fecha de nacimiento");
    expect(COPY.es.band.REVIEW).toBe("REVISIÓN");
  });

  it("reads source systems the way the source cards do", () => {
    expect(sourceSystemLabel("CLINIC_CSV")).toBe("Clinic CSV");
    expect(sourceSystemLabel("ER_FHIR")).toBe("ER FHIR");
  });
});
