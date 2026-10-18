import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { scenario } from "@/data/scenario";
import { CiteContextProvider } from "./CiteContext";
import { Organism, type OrganismProps } from "./Organism";

const cards = scenario.session.sources;
const entity = scenario.entityIfApproved;
const alert = scenario.alertIfApproved;

const base: OrganismProps = { cards, stage: "idle", entity: null, flag: { kind: "idle" }, threads: [] };
const render = (props: Partial<OrganismProps> = {}) =>
  renderToStaticMarkup(createElement(Organism, { ...base, ...props }));

describe("Organism", () => {
  it("before any link: two fragments in source order, no record, no notice, no threads", () => {
    const html = render();
    const cardsHtml = html.match(/data-testid="source-card"/g);
    expect(cardsHtml).toHaveLength(2);
    expect(html.indexOf('data-source-system="ER_FHIR"')).toBeLessThan(html.indexOf('data-source-system="CLINIC_CSV"'));
    expect(html).not.toContain('data-testid="golden-record"');
    expect(html).not.toContain('data-testid="flag-card"');
    expect(html).not.toContain("org-node");
  });

  it("in review: one thread and one node per cited field, marked = or ≈ from the records", () => {
    const html = render({ stage: "review", threads: ["given", "dob", "addr", "family"] });
    expect(html.match(/class="org-node"/g)).toHaveLength(4);
    expect(html).toMatch(/org-node" data-k="given"[^>]*>=</);
    expect(html).toMatch(/org-node" data-k="family"[^>]*>≈</);
    expect(html).toMatch(/org-node" data-k="dob"[^>]*>=</);
    expect(html.match(/<line[^>]*data-k="/g)).toHaveLength(4);
  });

  it("marks the fragments' spelling difference only on the family name they disagree on", () => {
    const html = render({ stage: "review", threads: ["family"] });
    // PLACEHOLDER-FAMILY vs PLACEHOLDER FAMILY: a hyphen in ER, a space in Clinic: a substitution, no marks.
    expect(html).not.toContain("org-d");
    expect(html).not.toContain("org-gap");
  });

  it("linked: the joined record with its notice and tabs, and no fragment in the DOM", () => {
    const html = render({ stage: "linked", entity, flag: { kind: "raised", alert } });
    expect(html).not.toContain('data-testid="source-card"');
    expect(html).toContain('data-testid="golden-record"');
    expect(html).toContain('data-testid="flag-card"');
    expect(html.match(/data-testid="crosswalk-chip"/g)).toHaveLength(2);
    expect(html).not.toContain('role="alert"');
  });

  it("is the candidate pair once a pair exists, and never before", () => {
    expect(render({ isPair: true })).toContain('data-testid="candidate-pair"');
    expect(render()).not.toContain('data-testid="candidate-pair"');
  });

  it("lights the field the evidence rail cites", () => {
    const html = renderToStaticMarkup(
      createElement(
        CiteContextProvider,
        { value: { cite: "family", setCite: () => {} } },
        createElement(Organism, { ...base, stage: "review", threads: ["family"] }),
      ),
    );
    expect(html).toMatch(/class="organism[^"]*"[^>]*data-cite="family"/);
    expect(render()).not.toContain("data-cite=");
  });
});
