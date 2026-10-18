import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CiteContextProvider, useCite } from "./CiteContext";

function Probe() {
  const { cite } = useCite();
  return createElement("i", { "data-cite": cite ?? "none" });
}

describe("CiteContext", () => {
  it("reads null when no provider is above: nothing lights up", () => {
    expect(renderToStaticMarkup(createElement(Probe))).toContain('data-cite="none"');
  });

  it("reads the cite a provider sets", () => {
    const html = renderToStaticMarkup(
      createElement(CiteContextProvider, { value: { cite: "dob", setCite: () => {} } }, createElement(Probe)),
    );
    expect(html).toContain('data-cite="dob"');
  });
});
