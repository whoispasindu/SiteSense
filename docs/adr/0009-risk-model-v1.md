# ADR 0009: Risk model v1 and how the backend runs it

- Status: accepted
- Date: 2026-10-10

## Context

Phase 6 is the first AI feature: a daily delay and cost-overrun risk score for every project,
calculated from live app data, ranked on the dashboard, with a High alert (BR-10). No real project
history is available, so training data has to be simulated. The model must be explainable to site
managers, safe to load in the API, and reproducible.

## Decisions

**Synthetic training data with real weather.** `ml/data_generator/simulate.py` simulates 300
projects week by week, with every assumption written down (`ASSUMPTIONS.md`) so a contractor can
check it. Rainfall is real (Open-Meteo archive, seven towns, 2012 to 2025). A hidden management
quality drives outcomes; the model only sees its symptoms. This is stated plainly in the model card
and in the UI ("trained on simulated projects").

**Features are defined once, in two mirrored places.** The simulator and
`backend/app/ai/risk/features.py` compute the same 16 features with the same definitions; the model
file lists them, and tests in both projects check the lists match. One definition changed while
building: the cost feature first compared all costs with progress, but the app only tracks material
commitments, so live projects would always look under budget. It now compares committed cost with
the budgeted value of the same quantities, which both sides can compute.

**LightGBM, exported as JSON, scored in pure Python. No pickles.** The guide suggests saving with
joblib. Loading a joblib/pickle file runs arbitrary code, so a tampered model file would take over
the server. Instead `ml/train.py` exports the trees as JSON (`[feature, threshold, left, right,
value]` nodes) and `app/ai/risk/model.py` validates and walks them. Validation checks the structure,
feature indexes, finite numbers, and that children come after parents so a walk always ends. The
backend therefore does not depend on LightGBM, NumPy or scikit-learn at all. Golden predictions in
the model file prove the evaluator matches LightGBM exactly (difference 0.0), and CI retrains from
the committed code to check the shipped model is reproducible.

**Monotone constraints.** Where the direction is known (behind plan, late deliveries, missed
reports, short crews, cost running over), the trees are constrained so the model cannot learn a
backwards rule from noise. That matters for trust: "more behind" must never mean "less risk".

**Score and bands.** Score = the worse of delay (25% of the planned duration late scores 100) and
overrun (20% over scores 100), so one number covers both. BR-10 bands: 70+ High, 40 to 69 Medium.
The same function makes the training labels and the live score.

**Drivers by path attribution.** Walking each tree, the change in node value at each split is
credited to that split's feature. Contributions add up exactly to the forecast. It is simpler than
SHAP (planned for v2) and labelled approximate; drivers are compared with a typical project at the
same stage, and the screen says so.

**When scores are made.** A daily job at 06:00 site time (after the 05:30 weather refresh), after
each daily report (best effort: a scoring failure never fails the report), and from the CLI
(`score-risk`). One row per project per day (`risk_scores`), replaced on re-scoring. The row keeps
the inputs, the missing-data notes, the drivers and the model version.

**BR-10 alerts on entry only.** A project that becomes High notifies the site's project managers
once. Staying High does not repeat the alert; recovering and becoming High again does.

**Who sees it.** `risk:read`: project managers and quantity surveyors, on their own sites (404
elsewhere). Site engineers, procurement and clients do not.

**Weather fetches 14 days.** The strip still shows five, but the risk model counts heavy-rain days
over the next two weeks. Fewer cached days are scaled up and noted.

## Consequences

- The backend's risk feature adds no heavy dependencies and no code-execution path through model
  files.
- Retraining means: run the simulator and `train.py`, review `metrics.json`, commit the new JSON
  (bump the version for any change in features or behaviour).
- The overrun model is weak until overheads and variations are recorded; the model card says so.
- Projects without a programme, planned crew or forecast are still scored, with the gaps listed.
