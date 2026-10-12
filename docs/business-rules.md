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
| BR-06 | Concrete pours on days with heavy rain forecast (10 mm or more) are flagged and the PM alerted | Phase 9 (the weather strip has marked heavy-rain days since Phase 4). The threshold was "over 10 mm" until the project owner set it to 10 mm or more | `rules/schedule.py: is_heavy_rain, pour_rain_days`, `services/network_service.py: check_pours` | `test_heavy_rain_is_ten_mm_or_more`, TC-12 `test_tc12_heavy_rain_on_a_pour_day_flags_the_task_and_alerts_the_pm`, `test_a_new_rain_day_alerts_again_and_done_pours_are_left_alone` |
| BR-07 | Each active site submits a daily report by 18:00; missing reports trigger reminders and count as a risk factor | Reminders: Phase 4. Risk factor: Phase 6 (`missing_reports_14`) | `services/report_service.py`, `core/scheduler.py`, `ai/risk/features.py` | `test_reminders_notifications.py`, `test_crew_and_missing_reports_over_the_last_14_days` |
| BR-08 | Claim value cannot exceed certified progress × contract value, minus previous claims and 5% retention | Phase 8 | `rules/claims.py: calculate, check`, `services/claim_service.py`; a database check makes the stored figures add up | `test_rules_cost.py` (`test_br08_*`), `test_br08_claim_is_calculated_with_retention`, `test_br08_previous_claims_are_deducted_once_approved` |
| BR-09 | Variations above the project's limit (1% of the contract value by default; Company Admin only, audited), or with any time impact, need client approval before work starts | Phase 8 | `rules/variations.py: needs_client, route`, `services/variation_service.py` | `test_rules_cost.py` (`test_br09_*`), `test_br09_limit_boundary`, TC-10 `test_tc10_client_approves_a_variation_with_time_impact` |
| BR-10 | Risk score 70+ is High (automatic PM alert), 40–69 Medium, under 40 Low | Phase 6 | `ai/risk/scoring.py: level`, `services/risk_service.py` | `test_br10_bands`, `test_br10_alerts_the_project_managers_when_a_project_enters_high`, `test_br10_does_not_repeat_while_the_project_stays_high` |
| BR-11 | A safety issue marked stop-work blocks related tasks until the PM clears it | Phase 7 (the flag, the PM alert, the banner, PM-only clearing) and Phase 9 (the stopped tasks refuse progress; the author picks them, or the whole project; the PM can change them) | `services/issue_service.py: _can_close, close_action, set_stop_scope`, `services/schedule_service.py: apply_progress`, `services/network_service.py: stopped, stopped_days` | `test_stop_work_is_cleared_only_by_the_project_manager`, `test_br11_a_stopped_task_takes_no_progress_until_the_pm_clears_it`, `test_br11_the_whole_project_stops_daily_report_progress_too`, `test_br11_the_author_chooses_the_scope_and_the_pm_can_change_it` |
| BR-12 | If a supplier's predicted on-time chance is under 50% for a critical-path item, suggest an alternative | Phase 10. Critical-path item: its BOQ section is linked to a critical task or one with 5 working days of float or fewer (`SITESENSE_BR12_FLOAT_DAYS`), or the PM marks it so; the PM can also mark it not critical | `services/supplier_service.py: estimate, outlook, critical_path`, `ai/supplier/model.py`, `features/materials/Br12.tsx` | `test_supplier_api.py` (`test_br12_marks_a_supplier_under_half`, `test_the_outlook_ranks_suppliers_and_names_critical_requests`, `test_the_pm_overrides_what_counts_as_critical`, `test_near_critical_tasks_count_too`), `materials.test.tsx` (BR-12) |
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

## BR-10: the risk score and its alert

The risk model (see the [model card](model-card-risk.md)) forecasts each open project's delay at
completion and cost overrun at completion every morning, and again after a daily report.

- **Score:** the worse of the two forecasts, from 0 to 100. A delay of 25% of the planned duration,
  or a 20% overrun, scores 100. So 10% late scores 40 and 17.5% late (or 14% over) scores 70.
- **Bands:** 70 or more is High, 40 to 69 Medium, under 40 Low. Shown in words, never by colour alone.
- **Alert:** when a project *enters* High, the project managers on its site get one notification.
  Re-scoring the same day, or staying High the next day, does not repeat it; dropping out of High
  and coming back does.
- **Never automatic:** a score changes nothing in the project by itself.

| Case | Expected | Test |
| --- | --- | --- |
| Score 69 / 70 | Medium / High | `test_br10_bands[69-medium]`, `[70-high]` |
| Score 39 / 40 | Low / Medium | `test_br10_bands[39-low]`, `[40-medium]` |
| 17.5% late, or 14% over budget | 70 | `test_risk_score[70-0-400-70]`, `[0-14-400-70]` |
| A project becomes High | One notification per site PM, none for the QS or other sites | `test_br10_alerts_the_project_managers_when_a_project_enters_high` |
| Re-scored the same day, or still High tomorrow | No new alert | `test_br10_does_not_repeat_while_the_project_stays_high` |
| Back to Low, then High again | Alerts again | `test_br10_alerts_again_after_the_project_recovers` |
| Medium | No alert | `test_medium_risk_does_not_alert` |

## Report issues: TC-06 and BR-11

After filing a report, its author asks the classifier to tag the problems (see the
[model card](model-card-report-issues.md)). Tags are suggestions; nothing happens until the author
confirms them, on the day of the report. Follow-ups must match a confirmed issue:

- **Material request:** needs a confirmed material delay. Opens a prefilled request form; closes when
  a request is raised from it, or the author dismisses it.
- **PM alert:** needs a confirmed high severity. Notifies the site's project managers at once.
- **Stop-work (BR-11):** needs a confirmed safety issue. Notifies the project managers and shows a
  banner on the project until a project manager clears it. Nobody else can clear it, including the
  author. Since Phase 9 it also stops programme tasks (see below).

Confirming re-scores the project's risk, because confirmed material, safety and design issues of the
last 14 days are risk model inputs.

| Case | Expected | Test |
| --- | --- | --- |
| TC-06: "cement not delivered again" | Material delay, high, not low-confidence; confirming re-scores risk with one material issue | `test_tc06_cement_not_delivered_again` |
| Confidence under 0.6 | Tag flagged for the author to check | `test_low_confidence_tags_are_flagged` |
| A worker's name in the problems | Stored as `[PERSON]` | `test_names_are_redacted_before_storage` |
| Someone other than the author, or the next day | 403, nothing changes | `test_only_the_author_on_the_day_checks_issues` |
| Confirming twice | 409 | `test_confirming_twice_is_refused` |
| Stop-work without a confirmed safety issue (and the other follow-ups) | 422 | `test_follow_ups_must_match_a_confirmed_issue` |
| Engineer or author clears stop-work / PM clears it | 403 / cleared, once | `test_stop_work_is_cleared_only_by_the_project_manager` |
| Material request raised from a follow-up | Follow-up closed with the request linked | `test_a_material_request_raised_from_a_follow_up_closes_it` |
| Suggested but unconfirmed issues | Not counted by the risk model | `test_only_confirmed_issues_in_the_last_14_days_count` |

## The programme: critical path, BR-06 and BR-11 (Phase 9)

**Working days.** Each project has a working week (Monday to Saturday unless set otherwise) and
skips the company's holidays, which the Company Admin keeps (2026's Poya days and public holidays
are seeded). Durations, lags, float and slip are all counted in working days. When a programme runs
into a year with no holidays entered, the schedule page and the admin's holiday list say so.

**Critical path** (`rules/schedule.py: analyse`). Tasks are linked finish-to-start, with an optional
lag. A forward pass finds each task's earliest start (the working day after its latest predecessor
finishes, plus lag, but never before its planned start). A backward pass from the last finish finds
the latest dates. Float is the working days between the earliest and latest finish. Unfinished tasks
with no float are critical: any delay to them moves handover.

**Forecast.** The same analysis runs on what is actually happening:

- finished tasks keep their actual dates;
- tasks under way finish at their own rate so far (percent per active working day). Under 10% done
  or under 5 working days in, the planned rate is used. The remaining time is capped at 10× the
  planned duration;
- tasks not started begin no earlier than today (tomorrow while stopped).

Slip is the forecast finish against the planned end, in working days. If long lags or very slow work
push the network more than 30 years out, tasks are shown on their own dates with no critical path,
and a warning says why.

**BR-06.** A task marked as a concrete pour, not finished, with a forecast day of work that has 10 mm
or more of rain forecast, is flagged on the programme. The site's project managers are alerted, once
per task and set of rain days, so a new rain day alerts again. The check runs daily at 05:45 after
the forecast refresh, when a task is marked as a pour, and from `app.cli check-pours`.

**BR-11.** A stop-work flag stops the tasks its author picks (in-progress tasks are suggested), or
the whole project for serious cases. Only a project manager changes the choice or clears the flag.
While stopped, a task refuses progress from the task list and from daily reports. Stopped working
days do not count as work, so the forecast moves a working day later for each one, and the critical
path and the risk model see the delay.

| Case | Expected | Test |
| --- | --- | --- |
| A(3) → B(2), A → C(4), B and C → D(1) from Mon 5 Jan, Mon–Fri | Finish Wed 14 Jan; floats A 0, B 2, C 0, D 0; A, C, D critical | `test_forward_and_backward_pass_on_a_known_network`, `test_the_pm_links_tasks_and_the_network_finds_the_critical_path` |
| A lag on A → B of 3 days | B and not C becomes critical | `test_a_lag_delays_the_successor_and_can_change_the_critical_path` |
| A lag on a link with float | The predecessor's float shrinks by the lag | `test_a_lag_on_a_side_link_cuts_the_predecessors_float` |
| A link that would make a loop | `422 dependency_loop` | `test_a_loop_is_refused`, `test_loops_are_found` |
| Work under way at a slower rate than planned | Forecast later than planned, slip shown | `test_the_forecast_follows_the_rate_so_far_and_shows_slip` |
| A holiday or rest day inside the work | Dates move past it | `test_the_working_week_and_holidays_shape_the_dates`, `test_a_holiday_moves_the_network` |
| TC-12: heavy rain forecast on a pour day | Task flagged, the site's PMs alerted (BR-06) | `test_tc12_heavy_rain_on_a_pour_day_flags_the_task_and_alerts_the_pm` |
| 9.9 mm / 10 mm | Not heavy / heavy | `test_heavy_rain_is_ten_mm_or_more` |
| Same rain days next morning / a new rain day / a finished pour | No alert / alert / no alert | `test_a_new_rain_day_alerts_again_and_done_pours_are_left_alone` |
| Progress on a stopped task, then the PM clears the flag | `422 stop_work`, then accepted | `test_br11_a_stopped_task_takes_no_progress_until_the_pm_clears_it` |
| Whole-project stop and a daily report with progress | `422 stop_work` | `test_br11_the_whole_project_stops_daily_report_progress_too` |
| Each stopped working day | Forecast one working day later; cleared days stop counting; two flags on a day count it once | `test_br11_each_stopped_working_day_moves_the_forecast_one_working_day`, `test_br11_a_cleared_flag_stops_counting_from_the_day_it_is_cleared`, `test_br11_two_flags_on_the_same_days_count_them_once` |
| Stop-work with no task chosen / a task from elsewhere | 422 | `test_stop_work_names_its_tasks_or_the_whole_project` |
| The engineer, or the PM, changes what a flag stops | 403 / changed, audited, risk re-scored | `test_br11_the_author_chooses_the_scope_and_the_pm_can_change_it` |

## BR-12 and the what-if planner (Phase 10)

**BR-12.** Each supplier's on-time chance comes from its record across the company: order lines
already due, on time if the whole quantity had arrived by the expected date. The record is smoothed
towards the company's rate ([model card](model-card-supplier.md)). Every estimate shows its likely
range and "based on N deliveries"; under 5 deliveries it is marked low data.

A request is a **critical-path item** when its BOQ item's section is linked to a programme task that
is critical, or has 5 working days of float or fewer. The project manager can mark a request
critical or not critical; the override is shown on the request and audited. When an order for a
critical-path item is about to go to a supplier under 50%, the purchase-order form suggests the best
alternative. The suggestion is marked tentative when it rests on few deliveries, and worded "if they
supply it". It never blocks the order.

**What-if (TC-11).** The project manager ticks recovery actions on a project's Risk tab and sees the
forecast delay, cost and score recalculated, each with its likely range
([ADR 0013](adr/0013-risk-v2-what-if-supplier-model.md)).

| Case | Expected | Test |
| --- | --- | --- |
| A supplier with 20 overdue orders | Under 50%, marked for BR-12 | `test_br12_marks_a_supplier_under_half` |
| A new supplier | The company's rate, low data, a wider range | `test_an_estimate_shows_its_range_and_the_deliveries_behind_it` |
| Early, on the day, late, overdue, not yet due | 2 of 4 on time (the last two not counted) | `test_a_suppliers_record_counts_lines_already_due` |
| A request whose section is linked to a critical task / a task with 3 days of float / with more | Critical / critical / not | `test_the_outlook_ranks_suppliers_and_names_critical_requests`, `test_near_critical_tasks_count_too` |
| The PM marks it not critical, then hands it back | Not critical despite the programme, then critical again; audited | `test_the_pm_overrides_what_counts_as_critical` |
| A critical order to a supplier under 50% | Suggestion with the alternative's chance and deliveries; tentative with little history | `materials.test.tsx` (BR-12) |
| TC-11: every action ticked | Delay, cost and score recalculated with ranges | `test_tc11_what_if_with_all_actions_selected`, `planner.test.tsx` (TC-11) |
| Any action or combination, half or full strength | Never a worse forecast or range end | `test_no_action_or_combination_ever_makes_a_forecast_worse` |
| A blank action cost | "Cost not entered", never free | `test_the_planner_shows_each_action_as_a_range_and_the_plan_with_its_costs` |

## BR-08: progress claims

The QS certifies a percentage complete for each BOQ section. The claim is calculated, never typed
in, so it cannot exceed the limit:

    certified %      = the sections' percentages weighted by their contract value
    certified value  = certified % × contract value (gross, to date)
    retention        = 5% of the certified value (held, to date)
    this claim       = certified value − retention − previous claims

A section's contract value is its BOQ amount plus approved variations in it. "Previous claims" are
the amounts of claims the PM approved (paid or not). Certified progress cannot go below the last
approved claim, one claim waits for the PM at a time, and a claim with nothing new is refused. The
PM approves or returns it with a comment; the QS records the payment date.

| Case | Expected | Test |
| --- | --- | --- |
| 40% of LKR 10 M, first claim | 4,000,000 certified, 200,000 retained, 3,800,000 claimed | `test_br08_claim_is_calculated_with_retention` |
| Then 60% | 6,000,000 − 300,000 − 3,800,000 = 1,900,000 | `test_br08_previous_claims_are_deducted_once_approved` |
| Sections 2 M at 100% and 6 M at 25% | 43.75% certified | `test_br08_sections_are_weighted_by_their_contract_value` |
| BOQ total differs from the contract value | Progress × *contract value* | `test_br08_uses_the_contract_value_when_the_boq_total_differs` |
| Rounding, any amount | Claim never above the BR-08 limit; the figures add up | `test_br08_rounding_never_lets_a_claim_exceed_the_limit` |
| Below the last approved %, or nothing new | Refused (422) | `test_br08_progress_cannot_go_back_or_claim_nothing` |
| Two claims at once | One accepted, the other 409 | `test_one_claim_waits_for_the_pm_at_a_time`; checked live against the API |
| A returned claim | Does not count as a previous claim | `test_a_returned_claim_does_not_count` |

## BR-09: variation orders and TC-10

A PM or QS raises a variation; **the QS prices every one** (the change to the contract value, and to
the section's cost budget). Then:

- any time impact, or a contract change above the project's limit (additions and omissions alike),
  goes to **the client**;
- otherwise a variation raised by the QS goes to **a project manager**;
- a variation raised by a project manager goes to the client, so **nobody approves their own**;
- once a variation has been with the client, a revision goes back to the client.

The limit is set to 1% of the contract value when a project is created. Only the Company Admin can
change it, with a reason, and every change is audited. The client sees the limit. A variation keeps
the limit it was routed with.

The PM approves, queries or rejects; the client approves or queries. A query sends it back to the
raiser or QS to revise (it is priced again) or withdraw. **On approval**, in one transaction: the
contract value changes, the section's budget line changes, the linked task and the project's planned
end move by the time impact, extra quantity on a BOQ item raises its BR-02 allowance, an audit entry
records before and after, and the project's risk is re-scored.

Once a project is past planning (or has any claim or variation), its contract value and planned end
change **only** through approved variations.

| Case | Expected | Test |
| --- | --- | --- |
| QS variation, LKR 90,000 (limit 100,000), no time | PM approves; contract, budget and BR-02 allowance change | `test_br09_a_small_qs_variation_goes_to_the_pm_and_applies` |
| Exactly the limit / 1 cent over / a large omission | PM / client / client | `test_br09_limit_boundary` |
| Any time impact | Client | `test_br09_routing` |
| Raised by a PM | Priced by the QS, then the client | `test_br09_a_pm_variation_is_priced_by_the_qs_and_goes_to_the_client` |
| **TC-10**: client approves a variation | Contract value, budget and schedule update; audit entry created | `test_tc10_client_approves_a_variation_with_time_impact` |
| Client queries, QS revises below the limit | Back to the client, not the PM | `test_the_client_queries_and_a_revision_goes_back_to_the_client` |
| Admin changes the limit | Audited with from, to and reason; applies to the next pricing | `test_only_the_admin_changes_the_limit_and_it_is_audited`, `test_a_new_limit_applies_to_the_next_pricing_only` |
| PM edits the contract value directly once under way | 422 `contract_locked` | `test_the_contract_changes_only_through_variations_once_under_way` |

## Forecast final cost and variance alerts

Per BOQ section: forecast = committed + (budget − budgeted value of the committed work) × cost trend,
where the trend is committed ÷ budgeted value of the same quantities. With nothing committed the
forecast is the budget. A section forecast more than 5% over its budget alerts the site's PM and QS
once, when it goes over (`budget_lines.over_budget_since`); coming back under clears it. Checked
every morning at 06:10, after approvals, orders, deliveries and variations, and with
`python -m app.cli check-variance`. Tests: `test_rules_cost.py`, `test_budget_shows_the_forecast_and_alerts_an_overrun_once`,
`test_a_section_still_over_the_next_day_does_not_alert_again`.

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
