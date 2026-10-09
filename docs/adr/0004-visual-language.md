# ADR 0004: Visual language ("site office")

- Status: accepted
- Date: 2026-10-09

## Context

Generic dashboard templates (purple gradients, glass cards, emoji icons) make products feel
interchangeable and say nothing about the domain. SiteSense users are contractors who read
drawings, programmes and BOQs every day.

## Decision

Borrow from construction documents:

- **Surfaces:** warm drafting-paper backgrounds with a faint grid. Panels are "sheets" with a
  sheet code in the corner, like drawing sheets.
- **Colour:** asphalt chrome, ink text, and hi-vis yellow reserved for the one primary action on
  a screen, as the product guide requires. Risk and status colours always carry a text label.
- **Type:** Archivo (variable width) for UI, widened for signage-style labels. IBM Plex Mono
  with tabular figures for every number, so columns of figures align.
- **Motifs:** dimension-line section headings, a programme (Gantt) chart and a title block. The
  hazard-stripe band appears at most once per view.
- **Accessibility:** WCAG 2.1 AA contrast (every signal colour is checked against its tint),
  44 px touch targets, visible focus, a skip link, and reduced-motion support.

## Consequences

A distinctive look tied to the domain. New components must use the tokens in
`frontend/src/index.css` rather than ad-hoc colours.
