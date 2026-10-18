import type { Locator, Page } from "@playwright/test";

/** DESIGN.md: nothing a judge must read goes below 16 px. */
export const MIN_TEXT_PX = 16;
/** The body size (DESIGN.md type table) the patient-facing kiosk lines use where they fit. */
export const BODY_TEXT_PX = 18;

/** Every visible text in the patient kiosk below `min` px, as "<size>px <text>". The band chip and
 * the constructed-scenario chip are the shared micro chips DESIGN.md keeps at 14 px on every screen. */
export function kioskTextBelow(page: Page, min = MIN_TEXT_PX): Promise<string[]> {
  return page.locator('section[aria-labelledby="kiosk-label"]').evaluate((kiosk, min) => {
    const walker = document.createTreeWalker(kiosk, NodeFilter.SHOW_TEXT);
    const small: string[] = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const el = node.parentElement;
      const text = node.textContent?.trim();
      if (!el || !text || !el.checkVisibility({ visibilityProperty: true })) continue;
      if (el.closest('[data-testid="constructed-scenario-chip"], [data-testid="band-chip"]')) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size < min) small.push(`${size}px ${text}`);
    }
    return small;
  }, min);
}

export function fontSizePx(locator: Locator): Promise<number> {
  return locator.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
}
