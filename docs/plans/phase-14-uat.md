# Phase 14 plan: the pilot, user acceptance and evaluation (after v1.0)

Status: decided (2026-11-15). **v1.0 is released first**, as open source; then a two-month pilot
with a construction company run by a friend of the project owner, on the company's own server,
installed from the public release, plus the company's historical project data. Findings ship as
1.0.x patch releases and a 1.1 at the end. Some decisions remain (see the end).

## Goal

Phases 0 to 13 built and tested SiteSense against its specification. Phase 14 asks the questions
the test suite cannot answer:

1. **Does it work for real people on real sites?** Site engineers on phones, a project manager, a
   quantity surveyor, procurement, an admin and a client, doing their own work.
2. **Are the AI models useful on real data?** Every model so far is trained on synthetic data, and
   every model card says its scores are not yet evidence about real sites.
3. **Can a company install and run it by itself**, from the guide alone, and recover from a backup?

**Done when** (all with a written record in `docs/uat/`):

- Every acceptance test case (TC-01 to TC-12, below) passes when **done by a person in the role**,
  in the app, on the pilot installation.
- No open finding of severity **Critical or High**. Medium ones are fixed or have a decision and an
  issue.
- Each role scores the app **68 or more on the System Usability Scale** (68 is the published
  average; below it means real usability problems), or the reasons are understood and the worst
  ones fixed.
- A site engineer files a typical daily report in **5 minutes or less** (median, on a phone).
- The **screen-reader session** (NVDA on Windows, TalkBack on Android) on the daily report and the
  client portal finds no blocker.
- **Install and restore** were done by someone who is not a developer of SiteSense, from
  [self-hosting.md](../self-hosting.md) only: install under an hour, and a restore drill on the
  pilot server.
- The **model evaluation** is published in the model cards, whatever it shows, with the claims in
  the app and the README adjusted to match.

## Who

| Who | How many | Why |
| --- | --- | --- |
| The pilot contractor | 1 company (decided), 1 or 2 active sites | Real projects, real reports, real approvals |
| Project manager | 1 or 2 | Dashboard, approvals, risk and what-if, programme, claims |
| Quantity surveyor | 1 | BOQ import, pricing (BR-01, BR-13), claims (BR-08), variations |
| Site engineers | 2 to 4 | Daily reports with photos on phones, AI tags, material requests: the heaviest use |
| Procurement officer | 1 | Orders, deliveries, suppliers (BR-12) |
| Company Admin | 1 | Users, sites, holidays, two-step resets, backups |
| Client | 1 (the pilot's own client, if willing) | The portal and variation approval |
| Installer | 1, not a SiteSense developer | Installs from the guide, does the restore drill |
| Facilitator | the project owner | Runs sessions, records findings, collects consent |

**A friend's company: honest feedback takes some design.** People are kind to a friend's product.
So the plan leans on what people do rather than what they say:

- the app's own records: reports filed, tags changed, approval times, screens never opened;
- watching sessions without helping;
- an anonymous usability survey;
- interviews with the people doing the work (engineers, the QS), not only the owner.

Every finding is logged, however small, and "it's fine" with no example counts as no answer.

(The fallback, if the pilot falls through: moderated sessions with 5 to 8 construction professionals
on the demo company. The model evaluation would then rest on synthetic data, and the README would
say so.)

## Where

The pilot runs on **its own installation, on the company's own server** (decided), from the release
bundle (`1.0.x`, public, with signed images). Their IT person (or whoever will look after it) installs it from the guide,
which is also the install test. It holds real company data, so:

- **demo mode off**, two-step sign-in on, nightly `backup.py create` copied off the server;
- **no pilot data leaves their server**: the evaluation runs there and only aggregate figures come
  back (see "Evaluation tools" below);
- a written **consent and data agreement** with the pilot: what is recorded, who sees it, that they
  can stop at any time, and that their data is theirs.

Fixes found during the pilot ship as patch releases (`1.0.1`, `1.0.2`…) and the pilot
upgrades with the documented procedure. That procedure gets tested along the way.

The repository is public from v1.0, so the pilot's server pulls the release images like any other
installation: no GitHub account needed.

## Part 1: acceptance test cases, done by people

Each case is done by a person in the role, on the pilot installation, with the facilitator
recording the steps, the result and anything surprising (`docs/uat/acceptance-tests.md`, one table
row per case and run). The automated test for each already exists. This checks the real screens,
words and phones.

| Case | Who | What they do | Pass when |
| --- | --- | --- | --- |
| TC-01 | Site engineer | Try to approve a material request | No way to do it, or a clear refusal, and nothing changes |
| TC-02 | QS | Price a request 6% over the budgeted rate | It goes to the PM, and the screen says why (BR-01) |
| TC-03 | Site engineer | File a second report for the same site and day | Refused with a clear message; they can open and edit the first |
| TC-04 | Site engineer | Submit a material request with a required field missing | A clear validation message; nothing saved |
| TC-05 | QS | Approve a request they raised themselves | Refused (BR-04); another QS can |
| TC-06 | Site engineer | Write "cement not delivered again" in today's problems | Tagged material delay, high; once confirmed, the project's risk is re-scored |
| TC-07 | Client | Look for any internal cost, budget or margin | None anywhere in the portal |
| TC-08 | Facilitator | Turn live weather off, then open a report | The last cached forecast with a warning; nothing breaks |
| TC-09 | Anyone | Enter a wrong password 6 times | Locked for 15 minutes, with a clear message |
| TC-10 | Client | Approve a variation with a time impact | Contract value, budget and programme update; audited |
| TC-11 | PM | Tick every recovery action in the what-if planner | Delay, cost and score recalculated, each with its range |
| TC-12 | PM | A pour falls on a heavy-rain day | The task is flagged and the PM alerted (BR-06) |

## Part 2: the pilot (two months of real use)

- **Training:** one 45-minute session per role group, then a one-page guide per role
  (`docs/uat/role-guides/`). Watch what people miss: anything that needs explaining twice goes
  on the findings list.
- **Daily use:** reports every working day; requests, orders and deliveries as they happen; at
  least one progress claim and one variation through the full workflow. Two months also means at
  least one monthly claim cycle, and enough reports (about 40 working days per site) for a real
  measure of the report classifier.
- **Measured** (from the app's own records, aggregates only):
  - reports filed on time (BR-07). The app records when a report is submitted, not when it was
    started, so the time to file one is timed in the observed sessions (a stopwatch on at least 10
    reports per engineer), or measured throughout if the small `started_at` change below is made;
  - requests through the approval chain, and how long each stage took;
  - AI tags accepted unchanged, changed or removed (see Part 3);
  - which screens are used, and which never are.
- **Asked:** the System Usability Scale after week 1 and at the end, per person; a 20-minute
  interview per role at the end ("what did you stop doing on paper?", "what did you work around?").
- **Findings** are logged by the facilitator as GitHub issues with a `uat` label and a severity:
  - **Critical:** data lost or wrong, someone sees what they must not, or work cannot be done;
  - **High:** a core task fails or misleads, with no reasonable way round it;
  - **Medium:** a task is slow, confusing or needs help;
  - **Low:** polish.

  An issue template for these is part of this phase.

## Part 3: evaluating the models on real data

Honesty matters more than the score: the model cards have said from the start that synthetic
results prove the pipeline, not the predictions.

**Report issue classifier** (the cleanest real signal SiteSense has). Every AI tag is suggested,
then confirmed, changed or removed by the report's author, and the app records both. So over the
pilot:

- category: the share of suggestions accepted unchanged, macro F1 against the authors' final
  categories, and the confusion between categories;
- severity: the same;
- **safety recall**: of the issues authors marked as safety, how many the model had suggested as
  safety. A safety issue the model misses still gets recorded, because the author writes it and
  confirms the tags. But this number decides how the app describes the model.

Whatever the numbers, they go in the model card. If category accuracy on real text is clearly below
the 80% on the hand-written test set, the app's wording stays "suggestions to check", and labelled
real sentences (only with the pilot's written permission, redacted) become the next training set.

**Risk model.** A few weeks cannot show final delay or overrun, so:

- **Historical check:** the pilot company gives planned and actual end dates, and budget and final
  cost, for their **finished projects** (decided: the owner can get this data; what to ask for, and
  how it is handled, is in [historical-data.md](../uat/historical-data.md)). As many as they can,
  ideally 10 or more. This tests the simulator's
  central assumptions directly (the median project finishes about 10% late; how overruns spread)
  and decides whether to recalibrate it (`ml/data_generator/ASSUMPTIONS.md`).
- **Face validity:** each week the PM ranks their projects by how worried they are, before looking
  at the scores. Record how well that agrees with the model's ranking, and every case where the
  drivers shown were wrong or unhelpful.
- **Rain:** the pilot's own record of weather-lost days, if they keep one, against the climate
  input ([#27](https://github.com/whoispasindu/SiteSense/issues/27)).

**Supplier on-time model (BR-12).** From the pilot's delivery history (past purchase orders, if they
can export them): on-time rates per supplier against the model's starting assumptions, and whether
any BR-12 suggestion during the pilot was right.

**AI briefing.** If the pilot sets a Claude key: each morning's briefing marked useful or not by
the PM (a thumbs up or down), and every claim checked against the records once a week. The briefing
must never state something the facts it was given do not support.

## Part 4: the other checks

- **Accessibility:** the screen-reader session (NVDA and TalkBack) on the daily report and the
  client portal, recorded in [accessibility.md](../accessibility.md). Phase 13 deferred it here.
- **Phones in the field:** the installable app on the engineers' own phones (Android and any
  iPhones), in sunlight, with gloves where they wear them, on site signal. Photos from the camera,
  the offline notice, the update prompt.
- **Install and restore** by the non-developer installer, timed, with every question they had to
  ask added to [self-hosting.md](../self-hosting.md). The restore drill on a spare machine from a
  real pilot backup.
- **Upgrade:** at least one `rc` to `rc` upgrade on the pilot by the documented procedure.
- **Security:** dependency audits and the secret scan clean on the release commit; the Phase 13
  OWASP walk-through re-read against everything added since (any country, the installable app,
  self-hosting, backups); a short external review if anyone qualified is willing.

## Engineering work in this phase

Small tools, so the evaluation needs no pilot data to leave their server:

1. **`python -m app.cli evaluate`**: prints aggregate figures only, never records. Covers the
   classifier against confirmed tags, report timing and on-time rates, approval stage times, and
   the BR-12 outcomes. Tested like any other command.
2. **Optional: `started_at` on daily reports**, set by the form when it opens and stored with the
   report, so the time to file is measured across the whole pilot rather than in sampled sessions.
3. **Historical projects import for the risk check:** a CSV template (planned and actual dates,
   budget and final cost) and a command that compares them with the simulator's assumptions, again
   printing aggregates.
4. **End-to-end browser tests for TC-01 to TC-12** (Playwright, against the production compose
   stack in CI), so the cases people pass in this phase stay passing.
5. **`docs/uat/`**: the acceptance-test record, the role guides, the SUS form, the consent and data
   agreement, and the `uat` issue template.
6. Fixes from the findings, as release candidates.

## Rough timeline

About 12 weeks, with two months of real use in the middle:

| Week | What |
| --- | --- |
| 1 | Remaining decisions (below); ask for the historical data; build the evaluation tools and `docs/uat/`; `1.0.1` |
| 2 | Access to the images; install at the pilot by their installer, from the guide; training; TC-01 to TC-12 with each role |
| 3 to 10 | Two months of real use; SUS after week 1; weekly check-ins and PM rankings; fixes as `1.0.2`, `1.0.3`… The historical data is analysed meanwhile |
| 11 | Final SUS and interviews; evaluation run; restore drill; screen-reader session; write-up |
| 12 | Fix what the findings need; update the model cards and README; tag **v1.1.0** |

## Decided by the project owner (2026-11-15)

1. **Plan A:** a pilot with a construction company run by a friend of the project owner.
2. **It runs on the company's own server**, installed by them from the guide.
3. **Two months** of real use.
4. **Historical project data** from the company, for the model evaluation, handled as in
   [historical-data.md](../uat/historical-data.md).
5. **v1.0 first, then the pilot:** release v1.0 as open source and make the repository public, so the
   pilot installs the public release.

## Still to decide

1. **Evaluation data:** aggregates only (proposed), or also redacted, labelled report sentences kept
   for retraining, with the company's written permission.
2. **The bar for the models:** proposed is "measured and published honestly, with the app's
   wording matched to the results", rather than a minimum score, since no real baseline exists yet.
