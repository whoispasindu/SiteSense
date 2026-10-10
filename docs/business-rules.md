# Business rules

The rules are what make SiteSense more than a record-keeping app. Each one lives in one place in
the code, has tests, and is listed here with its status. Rules that decide something are pure
functions in [`backend/app/rules/`](../backend/app/rules) (no database, clock or request), so the
boundaries can be tested directly; services gather the facts and apply the result.

| ID | Rule | Status | Where | Tests |
| --- | --- | --- | --- | --- |
| BR-01 | A request up to 5% over its budget line can be approved by the QS; more than 5% needs the project manager | Phase 5 | `rules/materials.py: route_approval` | `test_rules_materials.py`, TC-02 in `test_materials_api.py` |
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

## BR-01 in detail: which figures are compared

A BOQ item carries a *contract* rate (what the client pays); the budget line carries the
contractor's *cost* budget for the whole section. Two checks are made, and either one sends the
request to the project manager:

1. **Unit price against the item's budgeted rate.** The budgeted rate is the item's share of its
   section's budget line: `contract rate × section budget ÷ section BOQ value`. A price more than
   5% above it needs the PM.
2. **The budget line as a whole.** Approved, committed and spent cost in the section, plus this
   request, may not end more than 5% above the line's budget.

Routing is worked out when the request is submitted and again when the QS approves, so a request
that fitted when raised goes to the PM if commitments since then have used the headroom.

## BR-02 in detail

The allowance is `BOQ quantity × 1.03 + approved variation quantity`. "Requested" counts every
live request for the item (everything except rejected and cancelled), including this one.
Variations arrive in Phase 8; until then the variation quantity is zero, so anything above the
tolerance is blocked with a message saying a variation is needed. Two requests for the same item
at the same moment are checked one after the other (the BOQ item row is locked), so they cannot
both slip under the limit.

## Approval state machine

```
requested (QS check) --approve, within BR-01--> approved --purchase order--> ordered --deliveries--> delivered
requested --approve, above BR-01--> pm_approval --approve--> approved
requested | pm_approval --reject--> rejected
requested | pm_approval --request change--> change_requested --edit and resubmit--> requested
requested | pm_approval | change_requested --cancel (requester)--> cancelled
```

Anything else is refused with `409 invalid_transition`. Reject and request-change need a comment.
Every step is written to the request's history and the audit log, and the people concerned get an
in-app notification.
