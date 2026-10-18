import { describe, expect, it } from "vitest";
import type { NormalizedRecord } from "@/api/types";
import { scenario } from "@/data/scenario";
import { citedFields, fieldMark, fieldText, nameDiff } from "./cite";

const [er, cl] = scenario.session.sources;

describe("citedFields", () => {
  it("lists the fields the top evidence rows cite, strongest first, each once", () => {
    // Top 5 by weight: given 0.9, dob 0.8, address 0.7, family 0.6, family sound 0.5.
    expect(citedFields(scenario.pair.contributions)).toEqual(["given", "dob", "addr", "family"]);
  });

  it("skips features with no evidence and features that cite no field", () => {
    expect(
      citedFields([
        { feature: "dob_exact", logit: 0, value: null },
        { feature: "sex_match", logit: 0.9, value: 1 },
        { feature: "zip_match", logit: 0.3, value: 1 },
      ]),
    ).toEqual(["addr"]);
  });

  it("looks only at the rows the rail shows", () => {
    const rows = [
      { feature: "sex_match", logit: 0.9, value: 1 },
      { feature: "phone_match", logit: 0.8, value: 1 },
      { feature: "given_name_jw", logit: 0.7, value: 1 },
      { feature: "family_name_jw", logit: 0.6, value: 1 },
      { feature: "dob_exact", logit: 0.5, value: 1 },
      { feature: "address_jaccard", logit: 0.4, value: 1 },
    ];
    expect(citedFields(rows, 5)).toEqual(["given", "family", "dob"]);
  });
});

describe("fieldText", () => {
  it("reads each cited field from the normalized record, the address with its ZIP", () => {
    expect(fieldText("given", er.normalized)).toBe("PLACEHOLDER-GIVEN");
    expect(fieldText("family", cl.normalized)).toBe("PLACEHOLDER FAMILY");
    expect(fieldText("dob", er.normalized)).toBe("1985-07-03");
    expect(fieldText("addr", er.normalized)).toBe("100 Placeholder St, 54311");
  });

  it("is null when the record has no value", () => {
    const none: NormalizedRecord = { recordId: "x" };
    expect(fieldText("given", none)).toBeNull();
    expect(fieldText("addr", { recordId: "x", zip5: "54311" })).toBe("54311");
  });
});

describe("fieldMark", () => {
  it("is = when both records agree and ≈ when they differ", () => {
    expect(fieldMark("given", er.normalized, cl.normalized)).toBe("=");
    expect(fieldMark("family", er.normalized, cl.normalized)).toBe("≈");
    expect(fieldMark("dob", er.normalized, cl.normalized)).toBe("=");
  });

  it("is null when either side has no value: no thread to draw", () => {
    expect(fieldMark("given", er.normalized, { recordId: "x" })).toBeNull();
  });
});

describe("nameDiff", () => {
  it("finds the one run of characters one spelling has and the other lacks", () => {
    expect(nameDiff("Mesa-López", "MesaLópez")).toEqual({ side: "a", start: 4, end: 5 });
    expect(nameDiff("MesaLópez", "Mesa-López")).toEqual({ side: "b", start: 4, end: 5 });
    expect(nameDiff("Mesa López", "MesaLópez")).toEqual({ side: "a", start: 4, end: 5 });
    expect(nameDiff("De la Cruz", "Delacruz")).toBeNull(); // two runs and a case change: not one insertion
  });

  it("is null for equal names and for substitutions", () => {
    expect(nameDiff("Lopez", "Lopez")).toBeNull();
    expect(nameDiff("Lopez", "López")).toBeNull();
    expect(nameDiff("", "Lopez")).toBeNull();
  });
});
