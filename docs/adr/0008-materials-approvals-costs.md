# ADR 0008: Material requests, approvals and cost control

- Status: accepted (amended 2026-10-10: BR-01 split into BR-01 and BR-13; cost visibility; price
  pending, cumulative committed cost and BR-14)
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

**BR-01 and BR-13 are separate rules.** BR-01 compares only the unit price with the BOQ item's
budgeted rate (more than 5% above: the PM approves). BR-13 compares the section's committed cost
plus the request with the budget line (any excess: the PM approves). The response lists the rules
that fired (`routed_by`), so the request page can say why a request went to the PM. This was split
at the project owner's request; it was first built as one rule with both checks.

**Rates and amounts only for PM, QS and procurement.** A `rates:read` permission and role-specific
response schemas: every response that carries money has a cost-free base schema, and
`app/services/visibility.py` returns that base version to site engineers. Engineers therefore
cannot set prices either.

**Price pending until the QS check.** An engineer's request is stored with `unit_price` NULL
(migration 0007), not the budgeted rate. A budgeted rate would make BR-01 pass by construction and
put an invented figure into the budget. The QS must enter the quoted price to approve, with the
budgeted rate shown as reference, which matches Workflow B ("QS check: price against the budget
line"). Pending requests are not committed.

**Costs are derived, never stored.** One query per project (`section_costs`) reads every approved,
ordered or delivered request with its order line and deliveries:
- Approved: approved requests not yet ordered (at the approved price).
- On order: ordered, not yet delivered (at the order price).
- Spent: deliveries (at the order price).
- Committed: each request once, at its latest value (delivered, else order, else approved), which
  equals approved + on order + spent. This is the figure BR-13 checks and the budget shows.
- There are no running totals that could drift from the documents.

**Price changes at ordering go back to the PM (BR-14), and BR-13 is checked again.** This replaces
the first version, which refused any order price above the approved one. Quotes move, so up to 5%
above is accepted; beyond that, or if the order price pushes the section over its line, the request
returns to PM approval at the quoted price instead of failing the whole order. The other lines are
still ordered. Lines are checked in order against a running committed total, so lines on the same
order (or on separate orders) cannot each fit alone and together exceed the line. The history
reason carries no amounts because engineers can read it; procurement gets the full messages in the
response.

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
