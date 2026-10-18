import type { Locator, Page } from "@playwright/test";

/** The redesign's floor (BUILD-SPEC L2 row): nothing on the patient kiosk goes below 18 px. */
export const MIN_TEXT_PX = 18;
/** The body size (DESIGN.md type table) the patient-facing kiosk lines use where they fit. */
export const BODY_TEXT_PX = 18;

/** Every visible text in the patient kiosk below `min` px, as "<size>px <text>". No exemptions:
 * the band chip and the constructed-scenario chip are no longer on the kiosk. */
export function kioskTextBelow(page: Page, min = MIN_TEXT_PX): Promise<string[]> {
  return page.getByTestId("kiosk").evaluate((kiosk, min) => {
    const walker = document.createTreeWalker(kiosk, NodeFilter.SHOW_TEXT);
    const small: string[] = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const el = node.parentElement;
      const text = node.textContent?.trim();
      if (!el || !text || !el.checkVisibility({ visibilityProperty: true })) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size < min) small.push(`${size}px ${text}`);
    }
    return small;
  }, min);
}

export function fontSizePx(locator: Locator): Promise<number> {
  return locator.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
}
