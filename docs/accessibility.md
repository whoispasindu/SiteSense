# Accessibility

Phase 13. SiteSense aims at WCAG 2.2 level AA. Site engineers fill in reports on phones in
sunlight, and anyone may use a keyboard or a screen reader, so this is checked automatically on
every change and by hand once per phase.

## Checks that run on every change (CI)

**axe on every tested screen.** After each of the 393 frontend tests, axe-core 4.13 checks whatever
the test left on screen against the WCAG 2.0, 2.1 and 2.2 A and AA rules and axe's best practices.
Any finding fails that test (`src/test/setup.ts`, `src/test/axe.ts`). This covers every page, dialog,
form state, error and empty state the tests reach, for every role. The one rule left out is colour
contrast, because jsdom has no layout or paint; the next check covers it. "Everything inside a
landmark" applies only to whole pages, not to a component tested on its own.

**Colour contrast of the design tokens.** `src/test/contrast.test.ts` reads both themes from
`src/index.css` and checks every pair the interface uses (72 checks):

- **4.5:1 for text:**
  - body, secondary and faint text on the page, cards and sunk panels;
  - navigation text;
  - risk labels on cards and on their own tinted badges (tints blended onto the card first);
  - links;
  - the dark text on hi-vis primary buttons.
- **3:1 for marks people need to see (WCAG 1.4.11):** form field borders, focus rings (blue on
  paper, hi-vis on the dark navigation) and status marks.

Colour is never the only signal: risk levels, statuses and form errors always carry words too.

**Lint.** `eslint-plugin-jsx-a11y` (strict rules) runs in CI with zero warnings allowed.

## Fixed in Phase 13

| Finding | Where | Fix |
| --- | --- | --- |
| Form field borders at about 1.6:1, below the 3:1 for a control's edge (WCAG 1.4.11) | every input, select and text area, light and dark | A field border colour of its own (`field-line`, 3.6:1 light, 3.5:1 dark); dividers stay light |
| Error pages had no main landmark | the crash and not-found pages shown outside the app layout | They bring their own `main` |
| Two unnamed complementary landmarks on some pages | the sidebar beside a page's own side panel | The sidebar is named "Sidebar" |
| Demo banner outside any landmark | every page in demo mode | A named landmark, "Demo notice" |
| `aria-label` on a plain `div` | the briefing's loading placeholder | It is a `status` |
| Photo alt text repeated the caption shown beside it | report photos | The caption is the description; the image is not announced twice |

## Keyboard pass (16 October 2026)

Done in the browser on the demo data, as a project manager, in the dark theme, at desktop and
phone widths (the contrast test covers both themes):

- **Signing in:** the first Tab reaches the email field, the next the password; Enter signs in.
- **Skip link:** the first Tab on the dashboard shows "Skip to content" (every signed-in page
  shares that layout); Enter moves focus into the page.
- **Focus is always visible:** every focusable control on the dashboard, project list, project
  overview, risk, schedule and reports pages (21 to 57 per page) shows a focus ring or a highlighted
  border.
- **Dialogs** (the project form, and the navigation at phone width): opening moves focus inside,
  25 Tabs stay inside, and Escape closes and returns focus to the button that opened it. Dialogs
  are native `<dialog>` elements throughout.
- **What-if planner:** recovery actions tick with Space, focus stays put, and the new forecast is
  announced through a live region.

No keyboard trap was found.

## Known limits

- Automated checks find a large share of problems, not all. A screen-reader session (NVDA on
  Windows, TalkBack on Android) on the daily report and the client portal belongs in Phase 14's user
  acceptance tests.
- Charts have text alternatives: the S-curve and the risk trend have a summary label and a table
  of their figures for screen readers, and the cost ruler is a labelled list with the amounts in
  words. The drawings themselves are not navigable by keyboard.
