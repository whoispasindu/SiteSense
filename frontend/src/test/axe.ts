import axe from "axe-core";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

/**
 * Phase 13: an automated accessibility check (axe-core: WCAG 2.2 A and AA rules, plus best practices)
 * of whatever is on screen. Colour contrast is off here because jsdom has no layout or paint;
 * `contrast.test.ts` checks the design tokens instead.
 */
export async function axeViolations(root: Element = document.body): Promise<string[]> {
  // "Everything inside a landmark" is a page-level rule: it does not apply to a component on its own.
  const isPage = root.querySelector("main, [role='main']") !== null;
  const result = await axe.run(root, {
    runOnly: { type: "tag", values: TAGS },
    rules: { "color-contrast": { enabled: false }, region: { enabled: isPage } },
    resultTypes: ["violations"],
  });
  return result.violations.map((violation) => {
    const where = violation.nodes
      .slice(0, 3)
      .map((node) => node.target.join(" "))
      .join(" | ");
    return `${violation.id} (${violation.impact ?? "unknown"}): ${violation.help} -> ${where}`;
  });
}
