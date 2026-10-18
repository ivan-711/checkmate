import { describe, expect, it } from "vitest";
import { scenario } from "@/data/scenario";
import {
  CITE_CARD_FIELDS,
  evidenceDots,
  evidenceNote,
  FEATURE_LABELS,
  citeFieldFor,
  eventLabel,
  actorName,
  footerWithoutRule,
  differingFields,
  formatCt,
  compactLane,
  goldenValueText,
  rankContributions,
  sourceLabel,
} from "./display";

describe("rankContributions", () => {
  it("orders by absolute weight and puts missing features last as no evidence", () => {
    const ranked = rankContributions([
      { feature: "phone_match", logit: 0, value: null },
      { feature: "sex_match", logit: -1.2, value: 0 },
      { feature: "dob_exact", logit: 0.8, value: 1 },
    ]);
    expect(ranked.map((c) => [c.feature, c.missing])).toEqual([
      ["sex_match", false],
      ["dob_exact", false],
      ["phone_match", true],
    ]);
    expect(ranked[0].label).toBe("Sex");
  });

  it("keeps an unknown feature code readable", () => {
    expect(rankContributions([{ feature: "new_thing", logit: 1, value: 1 }])[0].label).toBe("new_thing");
  });
});

describe("differingFields", () => {
  it("marks fields present on both cards with different values", () => {
    const { recordA, recordB } = scenario.pair;
    expect(differingFields(recordA.normalized, recordB.normalized)).toEqual(new Set(["familyName"]));
  });

  it("does not call a missing value a difference", () => {
    const a = { recordId: "a", phoneE164: "+15555550100" };
    const b = { recordId: "b", phoneE164: null };
    expect(differingFields(a, b).size).toBe(0);
  });
});

describe("formatting", () => {
  it("formats a decision time in Central Time", () => {
    expect(formatCt("2026-10-17T19:32:08Z")).toBe("14:32:08 CT");
  });

  it("shows the registrar label without the actor prefix", () => {
    expect(actorName("registrar:Registrar B")).toBe("Registrar B");
    expect(actorName("system:scorer")).toBe("system:scorer");
  });

  it("names a source system by its card label", () => {
    const { recordA, recordB } = scenario.pair;
    expect(sourceLabel("CLINIC_CSV", [recordA, recordB])).toBe("Clinic CSV");
    expect(sourceLabel("SPECIALIST", [recordA, recordB])).toBe("SPECIALIST");
  });
});

describe("goldenValueText", () => {
  it("shows plain values as they are and a missing value as null", () => {
    expect(goldenValueText("PLACEHOLDER-GIVEN")).toBe("PLACEHOLDER-GIVEN");
    expect(goldenValueText(54311)).toBe("54311");
    expect(goldenValueText(null)).toBeNull();
    expect(goldenValueText(undefined)).toBeNull();
  });

  it("shows a coded clinical value by its display name and status, never [object Object]", () => {
    const allergy = { code: "7984", display: "Penicillin V", status: "active", resourceId: "a-1" };
    expect(goldenValueText(allergy)).toBe("Penicillin V (active)");
    expect(goldenValueText({ code: "308192", status: "active" })).toBe("308192 (active)");
    expect(goldenValueText({ code: "308192", display: "Amoxicillin 500 MG" })).toBe("Amoxicillin 500 MG");
  });

  it("falls back to key: value pairs for an object without a code, and joins lists", () => {
    expect(goldenValueText({ line: "100 Placeholder St", city: "Madison" })).toBe(
      "line: 100 Placeholder St, city: Madison",
    );
    expect(goldenValueText(["a", { display: "B" }])).toBe("a, B");
  });
});

describe("compactLane", () => {
  const ev = (day: number, isConstructed = false) => ({
    occurredAt: `2020-01-${String(day).padStart(2, "0")}`,
    isConstructed,
  });

  it("keeps the latest rows in date order and reports how many it hid", () => {
    const lane = [ev(3), ev(1), ev(5), ev(2), ev(4)];
    const { shown, hidden } = compactLane(lane, 2);
    expect(shown.map((e) => e.occurredAt)).toEqual(["2020-01-04", "2020-01-05"]);
    expect(hidden).toBe(3);
  });

  it("always keeps constructed-scenario rows, however old", () => {
    const { shown, hidden } = compactLane([ev(1, true), ev(2), ev(3), ev(4)], 2);
    expect(shown.map((e) => e.occurredAt)).toEqual(["2020-01-01", "2020-01-03", "2020-01-04"]);
    expect(hidden).toBe(1);
  });

  it("shows everything when the lane fits", () => {
    expect(compactLane([ev(2), ev(1)], 5)).toEqual({ shown: [ev(1), ev(2)], hidden: 0 });
  });
});

describe("footerWithoutRule", () => {
  it("drops the rule prefix the header already shows", () => {
    expect(footerWithoutRule("Rule BL-AMOX-01 v1. Not checked: dose.", "BL-AMOX-01", "v1")).toBe(
      "Not checked: dose.",
    );
  });

  it("leaves any other footer unchanged", () => {
    expect(footerWithoutRule("Not checked: dose.", "BL-AMOX-01", "v1")).toBe("Not checked: dose.");
    expect(footerWithoutRule("Rule BL-AMOX-02 v1. x", "BL-AMOX-01", "v1")).toBe("Rule BL-AMOX-02 v1. x");
  });
});

describe("FEATURE_LABELS", () => {
  // Every id the scorer emits: FEATURE_NAMES and the missing flags in backend/core/features.py.
  const SCORER_IDS = [
    ...["jw", "jw_folded", "dl", "dmeta", "nickname", "initial", "token_overlap"].map((f) => `given_${f}`),
    ...["jw", "jw_folded", "dl", "dmeta", "token_overlap"].map((f) => `family_${f}`),
    "dob_exact",
    "dob_day_month_swap",
    "dob_one_digit_edit",
    "dob_one_component_off",
    "dob_year_match",
    "sex_match",
    "phone_match",
    "address_jaccard",
    "zip_match",
    ...["given_name", "family_name", "dob", "sex", "phone", "address", "zip"].map((f) => `missing_${f}`),
  ];
  const FIXTURE_IDS = scenario.pair.contributions.map((c: { feature: string }) => c.feature);

  it("gives every scorer id a plain label, never the raw id", () => {
    for (const id of SCORER_IDS) {
      expect(FEATURE_LABELS[id], id).toBeTruthy();
      expect(FEATURE_LABELS[id]).not.toMatch(/_/);
    }
  });

  it("keeps labels distinct within each source, so five rows never read the same", () => {
    expect(SCORER_IDS).toHaveLength(28);
    for (const ids of [SCORER_IDS, FIXTURE_IDS]) {
      const labels = ids.map((id: string) => FEATURE_LABELS[id] ?? id);
      expect(new Set(labels).size).toBe(labels.length);
    }
  });

  it("labels only ids the scorer or the fixture can send", () => {
    const known = new Set([...SCORER_IDS, ...FIXTURE_IDS]);
    expect(Object.keys(FEATURE_LABELS).filter((id) => !known.has(id))).toEqual([]);
  });

  it("labels the folded given-name feature the evidence rail showed raw", () => {
    const [row] = rankContributions([{ feature: "given_jw_folded", logit: 1.5, value: 1 }]);
    expect(row.label).toBe("Given name, accents ignored");
  });
});

describe("citeFieldFor (evidence row to record field)", () => {
  it("maps every name feature to its name field", () => {
    expect(citeFieldFor("given_jw")).toBe("given");
    expect(citeFieldFor("given_nickname")).toBe("given");
    expect(citeFieldFor("family_jw_folded")).toBe("family");
    expect(citeFieldFor("family_dmeta")).toBe("family");
  });

  it("maps the date features to the date of birth", () => {
    for (const f of [
      "dob_exact",
      "dob_day_month_swap",
      "dob_one_digit_edit",
      "dob_one_component_off",
      "dob_year_match",
    ]) {
      expect(citeFieldFor(f), f).toBe("dob");
    }
  });

  it("maps the address and ZIP features to the address", () => {
    expect(citeFieldFor("address_jaccard")).toBe("addr");
    expect(citeFieldFor("zip_match")).toBe("addr");
  });

  it("maps the contract fixture's older ids too", () => {
    expect(citeFieldFor("given_name_jw")).toBe("given");
    expect(citeFieldFor("family_name_jw")).toBe("family");
    expect(citeFieldFor("family_metaphone")).toBe("family");
  });

  it("cites nothing for features without a field on the record, or unknown ones", () => {
    expect(citeFieldFor("sex_match")).toBeNull();
    expect(citeFieldFor("missing_phone")).toBeNull();
    expect(citeFieldFor("new_thing")).toBeNull();
  });

  it("names the card fields each cite lights up", () => {
    expect(CITE_CARD_FIELDS.given).toEqual(["givenName"]);
    expect(CITE_CARD_FIELDS.addr).toEqual(["addressLine", "zip5"]);
  });
});

describe("eventLabel", () => {
  it("shows a display label for every event type the contract lists", () => {
    // contracts/models/common.py EventType, as CLAUDE.md lists it.
    const types = [
      "RECORD_INGESTED",
      "MATCH_RUN_COMPLETED",
      "PAIR_SCORED",
      "LINK_APPROVED",
      "LINK_REJECTED",
      "LINK_REVOKED",
      "ENTITY_MERGED",
      "ENTITY_SPLIT",
      "ALERT_RAISED",
      "ALERT_RETRACTED",
      "WHATIF_APPLIED",
      "DEMO_RESET",
      "DEMO_RESTORED",
      "EXPLANATION_GENERATED",
      "EXTERNAL_CALL",
      "EVAL_RUN_STARTED",
      "EVAL_RUN_FINISHED",
      "INTAKE_STARTED",
      "AGENT_TOOL_CALLED",
      "INTAKE_HANDOFF_CREATED",
      "AGENT_TURN_DEGRADED",
    ];
    expect(eventLabel("LINK_APPROVED")).toBe("Link approved");
    expect(eventLabel("PAIR_SCORED")).toBe("Pairs scored");
    expect(eventLabel("INTAKE_HANDOFF_CREATED")).toBe("Held for registrar");
    expect(eventLabel("ALERT_RAISED")).toBe("Flag raised");
    for (const t of types) expect(eventLabel(t)).not.toMatch(/_/);
  });

  it("reads an unknown type as words rather than its code", () => {
    expect(eventLabel("SOMETHING_NEW")).toBe("Something new");
  });
});

describe("evidenceDots", () => {
  it("draws six dots, one per 0.5 log-odds, with partial fill", () => {
    expect(evidenceDots(3.0)).toEqual([1, 1, 1, 1, 1, 1]);
    expect(evidenceDots(1.47)).toEqual([1, 1, 0.94, 0, 0, 0]);
    expect(evidenceDots(0)).toEqual([0, 0, 0, 0, 0, 0]);
  });

  it("shows the weight of evidence against by magnitude and never more than six dots", () => {
    expect(evidenceDots(-1.2)).toEqual([1, 1, 0.4, 0, 0, 0]);
    expect(evidenceDots(9)).toEqual([1, 1, 1, 1, 1, 1]);
  });
});

describe("evidenceNote", () => {
  it("says what a row compared in plain words from the feature and the two values", () => {
    expect(evidenceNote("dob_exact", 1)).toBe("Exact");
    expect(evidenceNote("given_jw_folded", 1)).toBe("Same, accents ignored");
    expect(evidenceNote("family_jw_folded", 0.93)).toBe("Close, accents ignored");
    expect(evidenceNote("address_jaccard", 1)).toBe("Same street and ZIP");
    expect(evidenceNote("phone_match", null)).toBe("Not given on one side");
  });
});
