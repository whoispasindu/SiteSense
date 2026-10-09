# ADR 0006: Clean "site office" UI with light and dark themes

- Status: accepted
- Date: 2026-10-09
- Supersedes: [ADR 0004](0004-visual-language.md)

## Context

The first visual language (ADR 0004) was distinctive but hard to use day to day. Users found it
hard to read and not professional enough: widened display type, small monospaced labels in
capitals, drafting-grid backgrounds, sheet codes and hard offset shadows competed with the
content. There was no dark mode, and screens had few charts for a product about progress and
money.

## Decision

Keep the identity, drop the costume.

- **Kept:** asphalt navigation, hi-vis yellow for the primary action and the "actual" line in
  charts, signal colours that always carry a text label, the hazard band at most once per view,
  and the construction vocabulary in copy ("Off the drawings", "Authorised personnel only").
- **Type:** IBM Plex Sans (variable) for all text, at a 15 px base, sentence case, normal
  tracking. Numbers use tabular figures in the same face. IBM Plex Mono only for identifiers
  (BOQ item codes, task codes, site codes, temporary passwords) where telling 0/O and 1/l apart
  matters.
- **Surfaces:** flat, warm off-white paper (`#f5f5f2`) with white cards, 10 px radius and soft
  shadows. No grid backgrounds, no sheet codes, no offset shadows.
- **Themes:** light, dark and "system". The choice is a per-browser convenience kept in local
  storage and applied before first paint (`public/theme-init.js`, allowed by the CSP as a
  same-origin script). Every colour is a token on `:root` with a dark override under
  `[data-theme="dark"]`, mapped into Tailwind with `@theme inline`, so components never pick
  colours per theme.
- **Charts:** Recharts with theme tokens. Planned is a muted dashed line or bar, actual is the
  accent (yellow) line, today is the survey blue. Every chart has a text alternative: an
  `aria-label` summary and, where useful, the numbers as a table.
- **Dashboard:** a portfolio view (KPIs, schedule health, contract value chart) for project
  roles; system status and admin shortcuts for the company admin. The build-programme panel left
  the dashboard; the roadmap stays in the README.

## Consequences

- Text is easier to read, and both themes meet WCAG 2.1 AA contrast for body text. Signal colours
  are lighter in the dark theme so they keep their contrast against dark tints.
- New components use the tokens in `frontend/src/index.css` and the shared pieces (`Sheet`,
  `SectionHeading`, `KpiTile`, `StatusBadge`, `Button`, `Icon`) instead of ad-hoc styles.
- Status is never shown by colour alone. For example, the programme timeline marks the shortfall
  against today's plan with a red segment *and* the task list states "Behind".
