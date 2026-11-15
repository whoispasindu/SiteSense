# Historical project data for Phase 14

What to ask the pilot company for, so SiteSense's AI models can be checked against real outcomes
([Phase 14 plan](../plans/phase-14-uat.md), part 3). Everything SiteSense's models know today comes
from simulated projects; this data is the first test against reality.

The more finished projects the better: **10 is useful, 30 or more is good**. Partial rows are fine;
leave unknown cells empty. Rough figures from the company's records are better than none.

## What to ask for

### 1. Finished projects (`projects.csv`): the most important

One row per finished (or abandoned) project. This checks the risk model's core assumptions: how
late projects really finish, and how far costs really move.

| Column | Example | Notes |
| --- | --- | --- |
| `project_ref` | `P-017` | The company's own code, **not the project or client name** |
| `project_type` | `residential` | One of `residential`, `commercial`, `mixed_use`, `industrial`, `institutional` |
| `district` | `Colombo` | Nearest town or district (for rain); no street address |
| `contract_value` | `685000000` | Original contract value |
| `currency` | `LKR` | |
| `planned_start` | `2023-03-01` | Dates as YYYY-MM-DD |
| `planned_end` | `2024-08-31` | The contract completion date at signing |
| `actual_end` | `2024-12-20` | Practical completion (handover) |
| `cost_budget` | `610000000` | The contractor's own cost budget at the start, if they had one |
| `final_cost` | `655000000` | What it actually cost the contractor |
| `approved_variations` | `42000000` | Total value of approved variations, if known |
| `extension_days` | `45` | Time extensions granted by the client, if any |
| `planned_crew` | `40` | Typical daily workforce planned, if known |
| `main_delay_causes` | `material_delay;weather` | Optional; any of `material_delay`, `labour`, `weather`, `equipment`, `safety`, `design`, `quality`, `other`, separated by `;` |
| `weather_lost_days` | `12` | Optional; working days lost to rain, if they kept count |

A template with these columns: [historical-projects-template.csv](historical-projects-template.csv).

### 2. Deliveries (`deliveries.csv`): for the supplier model (BR-12)

One row per purchase order or delivery, from any recent period (a year is plenty).

| Column | Example | Notes |
| --- | --- | --- |
| `supplier_ref` | `S-04` | A code per supplier, **not its name** |
| `material` | `cement` | A short category: cement, steel, sand, formwork, ready-mix… |
| `ordered_on` | `2024-02-05` | |
| `promised_on` | `2024-02-12` | The date the supplier agreed to |
| `delivered_on` | `2024-02-15` | Empty if never delivered |
| `critical` | `yes` | Whether a delay in it held up the programme, if they know |

Template: [historical-deliveries-template.csv](historical-deliveries-template.csv).

### 3. Optional: daily report problems, only with written permission

If the company keeps site diaries or daily reports, a sample of the "problems" lines (100 or more)
would test the report classifier on real wording, beyond what the pilot itself produces. This is
the most sensitive part: **remove every person's name, phone number and company name first**, and
only with the company's written permission for this use.

## How the data is handled

- **Codes, not names.** No client, supplier, project or person names; no addresses. The company
  keeps the key that maps codes to names.
- **It never goes into the repository**, not even anonymised. Keep it in a folder outside the
  clone, or in `uat-data/` inside it, which git ignores.
- **Only aggregate results are published**: how late projects finish on average, how spread out
  overruns are, how well the model's ranges cover reality. Never a row, never a single project.
- **Written permission** from the company for this use, covering what is shared, who sees it,
  what is published, and that they can withdraw it. The consent form for the pilot covers this.
- **Deleted at the end of Phase 14** unless the company agrees to keep it for a later retraining.

## What it is used for

- **Risk model:** do real projects finish about 10% late on average, as the simulator assumes? How
  spread out are the delays and overruns? Would the model's "likely ranges" have covered what
  happened? If not, the simulator is recalibrated (`ml/data_generator/ASSUMPTIONS.md`) and the model
  retrained before v1.0, or the model card says why not.
- **Supplier model:** real on-time rates against the 80% starting assumption and the wet-season
  effect.
- **Rain:** weather-lost days against the climate the model uses
  ([#27](https://github.com/whoispasindu/SiteSense/issues/27)).
