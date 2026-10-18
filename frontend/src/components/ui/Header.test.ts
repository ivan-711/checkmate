import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { DeskProvider } from "@/components/desk/DeskContext";
import { DataSourceProvider } from "@/data/DataSourceProvider";
import { Header } from "./Header";

// The command bar inside the header asks the app router for the path; a test has no router.
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: () => {} }),
}));

function renderHeader(): string {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(DataSourceProvider, null, createElement(DeskProvider, null, createElement(Header))),
    ),
  );
}

/** The header's own Commands button, not the command bar it opens. */
function commandsButton(html: string): string {
  const start = html.indexOf('data-testid="header-commands"');
  expect(start, "the header renders its Commands button").toBeGreaterThan(-1);
  const open = html.lastIndexOf("<button", start);
  return html.slice(open, html.indexOf("</button>", start) + "</button>".length);
}

const visibleText = (markup: string) =>
  markup
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

describe("Header Commands button", () => {
  it("names itself with the words and the shortcut it shows, so voice control can say what it reads", () => {
    const button = commandsButton(renderHeader());
    const name = /aria-label="([^"]*)"/.exec(button)?.[1];
    expect(name).toBe("Commands ⌘K");
    expect(visibleText(button)).toBe("Commands ⌘K");
    for (const word of visibleText(button).split(" ")) expect(name).toContain(word);
  });

  it("shows the ⌘K hint as a keycap and opens the command dialog", () => {
    const button = commandsButton(renderHeader());
    expect(button).toMatch(/<kbd aria-hidden="true"[^>]*>⌘K<\/kbd>/);
    expect(button).toContain('aria-haspopup="dialog"');
  });
});
