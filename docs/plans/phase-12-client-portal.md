# Phase 12 plan: client portal

Status: planned (weeks 22 to 23). Builds on Phases 3, 4 and 8. This page collects what is already
decided, so Phase 12 starts from it.

## From the build guide

- **Goal:** clients see honest progress without seeing the contractor's internal costs.
- **Backend:** client-only endpoints with separate response schemas, so internal cost fields can never
  leak; variation approval and progress claim views.
- **Frontend:** client top navigation with progress, revised handover date and reason, milestones,
  approved photos, variations and payments.
- **Endpoints:** `GET /client/projects/{id}`, `GET /client/projects/{id}/claims`,
  `POST /variations/{id}/client-decision` (the last exists since Phase 8).
- **Tests:** TC-07; a schema test confirming no cost fields appear in any client response.
- **Done when:** a client account can follow progress and approve a variation, and cannot reach any
  internal data.

## Already in place (Phase 8)

- `GET /client/variations` and `GET /client/variations/{id}` list the variations *sent to the client*
  (any time impact, above the project's limit, or raised by a PM), with approve and query
  (`POST /variations/{id}/client-decision`, TC-10).
- `ClientVariationOut` carries no budget change, section budget or internal comment; internal people
  appear as "Contractor". The project's BR-09 limit is shown.
- Clients reach only projects on their sites (404 otherwise).

## Decided by the project owner (2026-10-11)

**Variations the PM approved under the limit are listed too.** Today the client sees only variations
sent to them. In the portal:

- Every **approved** variation of the client's project is listed, including those a PM approved under
  the client's approval limit (BR-09).
- Those are labelled **"Approved by contractor, under your approval limit"**.
- Each shows the **description**, the **price change** (the contract change) and the **date** it was
  approved.
- **No decision buttons** on them, and **no internal costs** (no budget change, no section budget, no
  internal comments, no QS or PM notes).
- The **contract value shown to the client includes them**: the original contract plus every approved
  variation, whoever approved it.

Implementation notes:

- Extend `client_list`/`client_get` in `app/services/variation_service.py` to include
  `status = approved` variations whose `approver = "pm"` (never sent to the client), alongside those
  with `sent_to_client_at` set. Variations still in progress internally (to price, waiting for the
  PM, queried by the PM, rejected or withdrawn before reaching the client) stay hidden.
- Add a field to `ClientVariationOut`, e.g. `approved_by: "client" | "contractor" | null` and
  `approved_on: date | null`, and keep `can_decide` false for contractor-approved ones.
- `GET /client/projects/{id}` returns the contract value from `projects.contract_value`, which
  already includes every approved variation.
- Tests: a PM-approved variation under the limit appears for the client with the label, date and
  price change, has no decision, and the response contains none of the internal fields (extend the
  "no cost fields in any client response" schema test to this view).

## Still to plan

- Revised handover date and its reason (from approved variations' time impact and, after Phase 9,
  the forecast end).
- Milestones and approved photos (which photos a client may see, and who approves them).
- Claims and payments view: approved and paid claims only, no retention internals beyond the amount
  held.
