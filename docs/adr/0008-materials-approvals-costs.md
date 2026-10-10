# ADR 0008: Material requests, approvals and cost control

- Status: accepted
- Date: 2026-10-10

## Context

Phase 5 is the procurement workflow (Workflow B). A request is raised against a BOQ item, checked
by the QS, approved by the QS or project manager under BR-01, ordered and delivered, and the
budget must show committed and spent cost "by themselves". The rules (BR-01, BR-02, BR-04, BR-05)
must be easy to test and to explain to users.

## Decisions

**Rules as pure functions.** `app/rules/materials.py` holds the rules and the state machine as
functions over plain values. Services collect the facts (BOQ quantity, budget line, costs so far)
and apply the results. Every boundary is unit-tested without a database, and the API returns the
rule results with their figures, so the screen can show exactly why a request goes to the PM.
[docs/business-rules.md](../business-rules.md) records which figures each rule compares.

**Costs are derived, never stored.**
- Approved cost comes from approved requests (at the request price).
- Committed cost comes from purchase-order lines not yet delivered (at the order price).
- Spent cost comes from deliveries (at the order price).
- There are no running totals that could drift from the documents. One query per project
  computes them (`section_costs`).

**Order price capped at the approved price.** Procurement may negotiate a lower price on the
purchase order, but not a higher one. A higher price would need a fresh approval, so BR-01 cannot
be bypassed at the ordering stage.

**One purchase order covers one project; a request is ordered at most once.** Enforced by a unique
`request_id` on order lines (plus a row lock), so committed cost is never double-counted.

**Concurrency.**
- Creating a request locks the BOQ item row, so the BR-02 quantity check is serialised per item.
- Decisions lock the request row, so two approvers cannot both act on it.
- Ordering locks the requests, and recording a delivery locks the order.
- A parallel test against the running API confirmed that only one of two simultaneous
  over-allowance requests is accepted.

**Document numbers.** `MR-0001` and `PO-0001` come from a `document_counters` row taken under a
lock: gap-free and readable on site and on paper.

**The BOQ is frozen once requests exist.** Re-importing would delete the items that requests point
at. The import is refused (on the dry run too), and the foreign key is `RESTRICT` as a backstop.
Changes then go through variations (Phase 8).

**Who acts.**
- Site engineers, QS and PMs raise requests.
- The QS checks every request first; the PM approves only what BR-01 routes to them. The PM
  cannot skip the QS check.
- Procurement works company-wide: it orders, receives deliveries and keeps the supplier list.
- Budget figures (`cost:read`) are for the PM and QS only, never clients (TC-07).

## Consequences

- Routing is re-evaluated when the QS approves, so the final approver always reflects current
  commitments, even if the request fitted when it was raised.
- Supplier on-time prediction (BR-12) and supplier ratings arrive in Phase 10. The supplier table
  is ready for them.
