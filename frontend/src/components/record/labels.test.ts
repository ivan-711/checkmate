import { describe, expect, it } from "vitest";
import { scenario } from "@/data/scenario";
import { holdsLine, phoneLabel, recordIdLabel, sexLabel, sourceFormat, sourceName } from "./labels";

const [er, cl] = scenario.session.sources;

describe("sourceName", () => {
  it("names the two demo sources in plain words", () => {
    expect(sourceName("ER_FHIR", er.displayLabel)).toBe("Emergency room");
    expect(sourceName("CLINIC_CSV", cl.displayLabel)).toBe("Clinic");
  });

  it("names the kiosk's intake record in plain words, never its code", () => {
    // The attached check-in joins the record as a third source; the Desk holds no card for it.
    expect(sourceName("FRONTDESK_INTAKE", "FRONTDESK_INTAKE")).toBe("Kiosk check-in");
  });

  it("falls back to the API's own label for any other source", () => {
    expect(sourceName("KIOSK", "Kiosk check-in")).toBe("Kiosk check-in");
  });
});

describe("recordIdLabel", () => {
  it("shortens a kiosk intake id to its first 8 characters, without the intake: prefix", () => {
    expect(recordIdLabel("FRONTDESK_INTAKE", "intake:0226ab4e-766e-49ea-9cb0-1d8ffbcc3758")).toBe("0226ab4e");
    expect(recordIdLabel("FRONTDESK_INTAKE", "0226ab4e-766e-49ea-9cb0-1d8ffbcc3758")).toBe("0226ab4e");
  });

  it("leaves every other source's record id whole", () => {
    expect(recordIdLabel("ER_FHIR", "ER-5F3685342A")).toBe("ER-5F3685342A");
  });
});

describe("sourceFormat", () => {
  it("reads the record kind as a format", () => {
    expect(sourceFormat("FHIR_PATIENT")).toBe("FHIR R4");
    expect(sourceFormat("CSV_ROW")).toBe("CSV export");
    expect(sourceFormat("INTAKE_UTTERANCE")).toBe("INTAKE_UTTERANCE");
  });
});

describe("sexLabel", () => {
  it("reads coded sex values as words and leaves anything else alone", () => {
    expect(sexLabel("FEMALE")).toBe("Female");
    expect(sexLabel("female")).toBe("Female");
    expect(sexLabel("F")).toBe("Female");
    expect(sexLabel("M")).toBe("Male");
    expect(sexLabel("unknown")).toBe("unknown");
  });
});

describe("phoneLabel", () => {
  it("groups a North American E.164 number and leaves others alone", () => {
    expect(phoneLabel("+15555550100")).toBe("+1 555 555 0100");
    expect(phoneLabel("+34600000000")).toBe("+34600000000");
  });
});

describe("holdsLine", () => {
  it("counts the record's allergies and active orders, singular and plural", () => {
    expect(holdsLine({ allergies: 1, orders: 4 })).toBe("1 allergy · 4 active orders");
    expect(holdsLine({ allergies: 2, orders: 1 })).toBe("2 allergies · 1 active order");
    expect(holdsLine({ allergies: 0, orders: 3 })).toBe("3 active orders");
  });

  it("is null when the record holds neither", () => {
    expect(holdsLine({ allergies: 0, orders: 0 })).toBeNull();
  });
});
