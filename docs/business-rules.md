# Business rules

The rules are what make SiteSense more than a record-keeping app. Each one lives in one place in
the code, has tests, and is listed here with its status. Rules that decide something are pure
functions in [`backend/app/rules/`](../backend/app/rules) (no database, clock or request), so the
boundaries can be tested directly; services gather the facts and apply the result.

| ID | Rule | Status | Where | Tests |
| --- | --- | --- | --- | --- |
| BR-01 | A unit price up to 5% above the BOQ item's budgeted rate can be approved by the QS; more than 5% needs the project manager | Phase 5 | `rules/materials.py: check_price` | `test_rules_materials.py` (`test_br01_*`), TC-02 `test_request_six_percent_over_budget_goes_to_the_pm` |
| BR-02 | Quantity above the BOQ allowance plus 3% tolerance is blocked unless an approved variation exists | Phase 5 | `rules/materials.py: check_quantity` | `test_rules_materials.py`, `test_quantity_above_the_boq_allowance_is_blocked` |
| BR-03 | Site engineers (and other site-scoped roles) only work on the sites they are assigned to | Phase 1 onward | `core/scoping.py`, every service | `test_site_scoping.py`, role matrix, "invisible" tests per module |
| BR-04 | A requester cannot approve their own request (segregation of duties) | Phase 5 | `rules/materials.py: check_not_own_request` | TC-05 `test_requester_cannot_approve_their_own_request` |
| BR-05 | No purchase order until the approval chain is complete | Phase 5 | `rules/materials.py: check_can_order` | `test_unapproved_requests_cannot_be_ordered` |
| BR-06 | Concrete pours on days with heavy rain forecast (over 10 mm) are flagged and the PM alerted | Partly: the weather strip flags heavy-rain days (Phase 4); pour flagging comes with the advanced schedule (Phase 9) | `api/v1/reports.py` (threshold) | `reports.test.tsx` |
| BR-07 | Each active site submits a daily report by 18:00; missing reports trigger reminders and count as a risk factor | Reminders: Phase 4. Risk factor: Phase 6 | `services/report_service.py`, `core/scheduler.py` | `test_reminders_notifications.py` |
| BR-08 | Claim value cannot exceed certified progress × contract value, minus previous claims and 5% retention | Phase 8 | | |
| BR-09 | Variations above a threshold, or with any time impact, need client approval before work starts | Phase 8 | | |
| BR-10 | Risk score 70+ is High (automatic PM alert), 40–69 Medium, under 40 Low | Phase 6 | | |
| BR-11 | A safety issue marked stop-work blocks related tasks until the PM clears it | Phase 7/9 | | |
| BR-12 | If a supplier's predicted on-time chance is under 50% for a critical-path item, suggest an alternative | Phase 10 | | |
| BR-13 | If the section's committed cost plus this request exceeds its budget line, the project manager approves. Checked at approval and again at purchase-order issue | Phase 5 (added at the project owner's request: the section check that was part of BR-01) | `rules/materials.py: check_section_budget`, `services/procurement_service.py: create_order` | `test_rules_materials.py` (`test_br13_*`), `test_qs_approval_rechecks_routing_with_current_figures`, `test_two_requests_that_fit_alone_exceed_the_line_together_at_approval`, `test_two_lines_that_fit_alone_exceed_the_line_together_at_po_issue` |
| BR-14 | A purchase-order unit price more than 5% above the approved price sends the request back for project manager approval | Phase 5 (added at the project owner's request) | `rules/materials.py: check_order_price`, `services/procurement_service.py: create_order` | `test_rules_materials.py` (`test_br14_*`), `test_order_price_more_than_five_percent_above_approval_goes_back_to_the_pm` |

## BR-01 and BR-13: who approves

Every request is checked by both rules. If either fires, the project manager approves after the QS
check; if neither does, the QS approves. The rules that fired are returned as `routed_by`, and the
request page names them ("Sent to the project manager by BR-13").

**BR-01: unit price against the item's budgeted rate.** A BOQ item carries a *contract* rate (what
the client pays); its section's budget line carries the contractor's *cost* budget. The item's
budgeted rate is its share of that line: `contract rate × section budget ÷ section BOQ value`. A
unit price more than 5% above it fires BR-01. Exactly 5% does not. Nothing else is compared here.

**BR-13: the section's budget line as a whole.** BR-13 fires when the section's committed cost plus
this request is more than the line's budget, with no tolerance. Exactly reaching the budget line
does not fire it.

**Committed cost** is cumulative. Every approved, ordered or delivered request on the line is
counted once, at its latest value:

- delivered in full: the delivered amount;
- otherwise on a purchase order: the order amount;
- otherwise approved: the approved amount (quantity × approved price).

Pending requests (at the QS check or PM approval, or with a change requested) are not committed.
Rejected and cancelled requests never are. Delivered cost stays committed, so the check does not
loosen as goods arrive. The budget screen shows the same figure as **Committed**, next to its parts:
**Spent** (delivered), **On order** (ordered, not yet delivered) and **Approved** (not yet ordered).
Committed = spent + on order + approved, and **Left** = budget − committed.

**When BR-01 and BR-13 are worked out.** When the request is submitted, again when the QS approves
(with the QS's price and today's commitments), and BR-13 once more at purchase-order issue (see
BR-14 below). A request that fitted when raised therefore goes to the PM if commitments since then
have used up the line.

**Price pending.** Site engineers do not see rates (see [roles-and-access.md](roles-and-access.md)),
so they raise requests with a quantity only, and a price sent by an engineer is refused
(`422 price_not_allowed`). Their requests start with no price: BR-01 and BR-13 report `pending`,
and the budget does not count them. The QS must enter the quoted unit price before approving
(`422 price_required` otherwise); the approve dialog shows the item's budgeted rate beside the
field as reference. Both rules are then evaluated with that price.

## BR-14 and BR-13 at purchase-order issue

Procurement may order at a different price from the approved one. Each line is checked again when
the order is issued:

- **BR-14:** an order unit price more than 5% above the approved price (exactly 5% passes).
- **BR-13:** the section's committed cost plus the line at its order price exceeding the budget
  line. Lines are taken in order and each accepted line is added to the section's committed cost
  before the next is checked, so two lines that fit alone but not together cannot both get through.
  A request the PM has already approved is not sent back for BR-13 again unless its order amount is
  higher than the amount the PM approved.

A line that fails either rule is not ordered. The request goes back to **PM approval** at the
quoted price, with a `return_for_approval` step in its history, an audit entry and a notification
to the site's project managers. The other lines are still ordered. If no line is left, no purchase
order is created (`200` with `order: null`); otherwise `201`. The response lists the returned lines
with the rule messages for procurement. The history step gives the reason in words without prices,
because site engineers can read the history.

### Test cases

| Case | Expected | Test |
| --- | --- | --- |
| Price 5.00% over the budgeted rate | QS approves | `test_br01_fires_only_above_five_percent_over_the_budgeted_rate[105-pass]` |
| Price 5.01% over | BR-01 fires, PM approves | `[105.01-warn]` |
| QS prices a request 6% over (TC-02) | PM approval, `routed_by = ["BR-01"]` | `test_request_six_percent_over_budget_goes_to_the_pm` |
| Price on budget, section line exactly reached | QS approves | `test_br13_fires_when_committed_cost_plus_the_request_exceeds_the_budget_line[99000-1000-pass]` |
| Price on budget, line exceeded by one cent | BR-13 fires | `[99000-1000.01-warn]` |
| Section already over before the request | BR-13 fires | `[150000-1-warn]` |
| Price on budget but the line filled since submission | PM approval, `routed_by = ["BR-13"]` | `test_qs_approval_rechecks_routing_with_current_figures` |
| Both rules fire | `routed_by = ["BR-01", "BR-13"]` | `test_both_rules_can_fire` |
| Engineer's request, no price yet | BR-01 and BR-13 `pending`; the QS cannot approve without a price | `test_without_a_price_br01_and_br13_are_pending`, `test_qs_cannot_approve_until_the_price_is_entered` |
| Two requests fit alone, not together, at approval | The second goes to the PM, `routed_by = ["BR-13"]` | `test_two_requests_that_fit_alone_exceed_the_line_together_at_approval` |
| Committed counted once at its latest value | Approved → order → delivered amount, never twice | `test_latest_value_counts_each_request_once`, `test_full_flow_from_site_to_delivery_updates_the_budget` |
| Order price 5.00% over the approved price | Ordered | `test_order_price_up_to_five_percent_above_approval_is_accepted` |
| Order price 5.01% over (BR-14) | Sent back for PM approval, nothing ordered | `test_order_price_more_than_five_percent_above_approval_goes_back_to_the_pm` |
| Two lines fit alone, not together, at PO issue | First ordered, second sent back (BR-13) | `test_two_lines_that_fit_alone_exceed_the_line_together_at_po_issue`, `test_two_requests_ordered_on_separate_orders_are_checked_together` |
| PM already approved the excess | Ordered at the approved price without going back | `test_pm_approved_requests_are_not_returned_for_the_same_excess` |

## BR-02 in detail

The allowance is `BOQ quantity × 1.03 + approved variation quantity`. "Requested" counts every
live request for the item (everything except rejected and cancelled), including this one.
Variations arrive in Phase 8; until then the variation quantity is zero, so anything above the
tolerance is blocked with a message saying a variation is needed. Two requests for the same item
at the same moment are checked one after the other (the BOQ item row is locked), so they cannot
both slip under the limit.

## Approval state machine

```
requested (QS check) --approve, neither BR-01 nor BR-13 fires--> approved --purchase order--> ordered --deliveries--> delivered
requested --approve, BR-01 or BR-13 fires--> pm_approval --approve--> approved
requested | pm_approval --reject--> rejected
requested | pm_approval --request change--> change_requested --edit and resubmit--> requested
requested | pm_approval | change_requested --cancel (requester)--> cancelled
approved --purchase order, line fails BR-14 or BR-13--> pm_approval (at the quoted price)
```

Anything else is refused with `409 invalid_transition`. Reject and request-change need a comment.
Every step is written to the request's history and the audit log, and the people concerned get an
in-app notification.
