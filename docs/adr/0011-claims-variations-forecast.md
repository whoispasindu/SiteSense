# ADR 0011: Progress claims, variation orders and the cost forecast

- Status: accepted
- Date: 2026-10-11

## Context

Phase 8 completes the money side of a project. The build guide asks for:

- a forecast final cost per BOQ section ("committed cost plus the remaining work at the current
  cost trend") and variance alerts;
- progress claims with the BR-08 retention calculation;
- variation orders with BR-09 client approval routing that, on approval, update the contract value,
  budget lines and tasks (TC-10).

BR-09's threshold is written "LKR [X]". The project owner decided:

- the default is 1% of the contract value, per project;
- only the Company Admin can change it, every change is audited, and the client sees the limit;
- any time impact always goes to the client;
- the QS prices every variation before it goes to the PM or the client;
- a PM never approves their own variation.

## Decisions

**The claim is calculated, never typed in.** The QS enters only a certified percentage per BOQ
section. `app/rules/claims.py` turns that into the claim:

- certified progress is the sections' percentages weighted by their contract value;
- the certified value is that percentage of the **contract value**, as BR-08 says (the BOQ only
  gives the weights);
- 5% of it is retained, and previous approved claims are deducted.

Because the amount is computed, BR-08's ceiling cannot be exceeded. A database check also makes the
stored figures add up (amount + retention + previous claims = certified value), whatever wrote them.

**One claim waits for the PM at a time.** A partial unique index, plus a project row lock when a
claim is made, mean "previous claims" cannot change between making and approving a claim. Two
simultaneous submissions give 201 and 409. Certified progress cannot go below the last approved
claim, and a claim with nothing new is refused. Retention is 5% of certified work to date. Releasing
it at practical completion comes with the close-out work later.

**Segregation of duties comes from the roles.** Only a QS submits claims and records payment; only
a PM approves.

**Every variation is priced by the QS.** A variation has two prices:

- the **contract change**, which the client pays (negative for an omission);
- the **budget change**, the contractor's cost, which goes to the section's budget line.

A PM can raise a variation but not price it. A QS can price one while raising it.

**BR-09 routing** (`app/rules/variations.py`). These go to the client:

- any time impact;
- a contract change whose absolute value is above the project's limit, so omissions count too;
- a variation raised by a PM, so no PM approves their own and single-PM sites never get stuck.

Everything else goes to a PM. Once a variation has been with the client, a revision goes back to the
client rather than quietly to the PM. Each variation keeps the limit it was routed with
(`limit_applied`), so changing a project's limit never re-routes work already sent.

**The limit is the Company Admin's.** `projects.variation_limit` is set to 1% of the contract value
when a project is created (a column default, so every creation path gets it); migration 0010
backfilled existing projects. Changing it needs `variation_limits:manage`, which only the Company
Admin holds. A reason is required, and the audit entry records from, to and reason.

**Approval changes the contract in one transaction.** It locks the variation, the project and the
budget line, then:

- adds the contract change to the contract value;
- adds the budget change to the budget line;
- moves the linked task and the project's planned end by the time impact;
- raises the item's BR-02 allowance by any extra quantity (counted from approved variations, so the
  BOQ itself stays as imported);
- records the before and after values in an audit entry (TC-10).

After the commit, the project's risk is re-scored and its cost variance checked. If the contract or
budget changed since pricing so that a value would go below zero, approval is refused and the QS
prices it again.

**The contract changes only through variations once work starts.** Before Phase 8 a PM could edit
the contract value and planned end at any time. That now bypassed the QS's price, BR-09 and the
client. These two fields can be edited directly only while a project is in planning with no claim or
variation; after that, approved variations are the only way.

**The client's view is a separate schema.** `ClientVariationOut` has no budget change, no section
budget and no internal comments. Internal actors appear as "Contractor", and the client sees only
their own comments. The client sees a variation only once it has been sent to them, and only on
their sites (404 otherwise). The full client portal is Phase 12.

**Forecast final cost** (`app/rules/cost.py`). Per section:

    forecast = committed + (budget − budgeted value of the committed work) × trend
    trend    = committed ÷ budgeted value of the committed work

With nothing committed the forecast is the budget. The trend uses the same "committed against the
budgeted value of the same quantities" as the risk model's cost feature (ADR 0009), now per section.
Early on the trend rests on little. The screen shows how much of the budget it is based on, rather
than capping or smoothing it.

**Variance alerts work like the BR-10 alert: on entry only.** A section forecast more than 5% over
its budget (the same 5% as BR-01 and BR-14) notifies the site's PM and QS once.
`budget_lines.over_budget_since` remembers the overrun, and coming back under clears it. The check
runs daily at 06:10 (after risk scoring), after approvals, orders, deliveries and approved
variations (best effort, never failing the event), and from the CLI.

**Margins include approved variations.** Project and section totals carry the approved variations'
contract change. Every margin compares BOQ plus variations with the budget, since the budget line
already includes the variation's budget change.

## Consequences

- Claims and variations work end to end for the PM, QS and client, and the budget page shows the
  forecast and variance (the guide's "done when").
- Committed cost still covers materials only (Phase 5), so the forecast is a materials-led trend
  applied to the whole budget line. Labour, subcontract and plant costs are tracked in
  [#26](https://github.com/whoispasindu/SiteSense/issues/26). The screen says what
  the forecast is based on.
- Releasing retention and client-issued variations are left to later phases. Decided for the Phase 12
  portal: clients will also see variations a PM approved under their limit, labelled "Approved by
  contractor, under your approval limit", without decision buttons or internal costs, and the
  contract value they see includes them ([Phase 12 plan](../plans/phase-12-client-portal.md)).
- The risk model does not yet use variation counts as an input; that comes with risk model v2
  (Phase 10).
