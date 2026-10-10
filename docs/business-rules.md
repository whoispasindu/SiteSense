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
| BR-13 | If the section's committed cost plus this request exceeds its budget line, the project manager approves | Phase 5 (added at the project owner's request: the section check that was part of BR-01) | `rules/materials.py: check_section_budget` | `test_rules_materials.py` (`test_br13_*`), `test_qs_approval_rechecks_routing_with_current_figures` |

## BR-01 and BR-13: who approves

Every request is checked by both rules. If either fires, the project manager approves after the QS
check; if neither does, the QS approves. The rules that fired are returned as `routed_by`, and the
request page names them ("Sent to the project manager by BR-13").

**BR-01: unit price against the item's budgeted rate.** A BOQ item carries a *contract* rate (what
the client pays); its section's budget line carries the contractor's *cost* budget. The item's
budgeted rate is its share of that line: `contract rate × section budget ÷ section BOQ value`. A
unit price more than 5% above it fires BR-01. Exactly 5% does not. Nothing else is compared here.

**BR-13: the section's budget line as a whole.** BR-13 fires when the section's committed cost plus
this request is more than the line's budget, with no tolerance. "Committed cost" means everything
already committed against the line: approved requests not yet ordered, open purchase orders, and
deliveries. Delivered cost counts because it was committed before it arrived; otherwise the check
would loosen as goods are delivered. Exactly reaching the budget line does not fire it.

Both rules are worked out when the request is submitted and again when the QS approves. A request
that fitted when raised therefore goes to the PM if commitments since then have used up the line.

**Who prices a request.** Site engineers do not see rates (see
[roles-and-access.md](roles-and-access.md)), so they raise requests with a quantity only. Such a
request starts at the item's budgeted rate (BR-01 passes) and the QS sets the expected price at the
QS check. Both rules are then evaluated again with that price.

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
```

Anything else is refused with `409 invalid_transition`. Reject and request-change need a comment.
Every step is written to the request's history and the audit log, and the people concerned get an
in-app notification.
