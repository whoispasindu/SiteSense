# Model card: daily report issue classifier, v1.1.0

| | |
| --- | --- |
| Model | Two parts. **Category**: DistilBERT (`distilbert-base-uncased`) fine-tuned with two heads, run as ONNX at full precision. **Severity**: TF-IDF and logistic regression, with the labelling guide's rules around it |
| Version | 1.1.0, trained 2026-10-10. Fallback when the DistilBERT files are not present: 1.0.0 (TF-IDF for both) |
| Files | `backend/app/ai/nlp/models/report-issues-v1.0.0.json` (TF-IDF, committed). DistilBERT: 266 MB, attached to the GitHub Release `models-report-issues-1.1.0`, pinned by SHA-256 in `report-issues-category-v1.1.0.manifest.json` (committed) |
| Training code | `ml/nlp/generate.py`, `train_baseline.py`, `train_distilbert.py`, `export_onnx.py`. Labelling guide: `ml/nlp/LABELLING.md` |
| Training data | **Synthetic**: 1,243 training and 277 validation sentences from templates and phrase banks |
| Test data | 199 sentences written by hand, separately from the templates, never used for training or tuning |

## What it is for

A site engineer writes the day's problems in free text ("cement not delivered again, crane down
from 2pm"). After the report is filed, the classifier splits the text into sentences and suggests,
for each one:

- a **category**: material delay, labour, weather, equipment, safety, design, quality, other;
- a **severity**: low, medium, high;
- a **confidence** (the category probability). Under 0.6 the tag is highlighted as "check this".

The author keeps, edits or removes each tag, may add their own, and may tick follow-ups: raise a
material request, alert the project manager, flag stop-work (BR-11). **Nothing happens until the
author confirms**, and every follow-up box starts unticked. Confirmed issues feed the risk model
(material, safety and design issues over the last 14 days).

**Not for:** judging workers or subcontractors, safety reporting that has to be complete (a missed
tag is not a "no incident"), or text that is not a site problem description.

## How it was chosen

The rule set by the project owner: **adopt DistilBERT only if it beats the TF-IDF baseline by about
5 macro-F1 points or more on the hand-written test set; otherwise ship the baseline.** Both models
were tuned on the validation set only. The validation split holds out whole templates (about 20%
per category), so it measures wording the model has not seen, not memorised templates.

| Category, hand-written test set | Macro F1 |
| --- | --- |
| TF-IDF baseline (words and characters, balanced) | 0.730 |
| DistilBERT, PyTorch | 0.801 |
| DistilBERT, ONNX full precision (**shipped**) | **0.801** |
| DistilBERT, ONNX 8-bit (a quarter of the size) | 0.785 |

- **Gain at full precision: +7.2 points**, paired bootstrap 95% interval +1.2 to +13.4 (2,000
  resamples). The rule is met and the gain is clear of zero.
- **8-bit: +5.6 points**, interval −0.9 to +12.1. The gain is not clear of zero, so the smaller file
  was not shipped. The 8-bit model also quantises activations per input, so a sentence's score
  changed with the other sentences in the batch; full precision does not (tested).

| Severity, hand-written test set | Macro F1 | With the guide's rules |
| --- | --- | --- |
| TF-IDF (**shipped**) | 0.467 | **0.500** |
| DistilBERT severity head | 0.468 | 0.484 |

DistilBERT did not beat the baseline for severity, so severity stays with TF-IDF and the rules:
repetition ("again", "third time") raises severity one step, and an injury or stopped work is high.

Evidence: `ml/models/report-nlp/decision.json`, `baseline-metrics.json`, `distilbert-metrics.json`.
The manifest repeats it, and a backend test fails if the shipped manifest does not meet the rule.

## Results of what ships

Scored exactly as the backend runs it (`ml/models/report-nlp/shipped-metrics.json`).

**Category: macro F1 0.801, accuracy 80%.**

| | Material | Labour | Weather | Equipment | Safety | Design | Quality | Other |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F1 | 0.78 | 0.79 | 0.95 | 0.87 | 0.72 | 0.82 | 0.67 | 0.81 |

The main confusions: quality read as material delay (wrong grade or damaged material, 4 of 26) or
design (3); labour read as material delay (3 of 22); "other" read as safety (4 of 25); and safety
read as quality (3 of 26).

**Severity: macro F1 0.50, accuracy 53%.** It is the weak part. Low is rarely recognised (recall
29%) and high is over-called (recall 72%, precision 52%). Of 49 low sentences, 22 were called medium
and 13 high. In practice it leans towards suggesting a PM alert more often than needed. That is why
the alert box is never pre-ticked, and the author sees and can change every severity.

**Low confidence (under 0.6).** On the test set, 21% of tags fall below it. They are right 51% of
the time, against 87% above it, and they hold half of all category errors. The threshold is a fixed
round number, not tuned on any data. Flagging catches half the mistakes for a fifth of the tags.

## Responsible use

- **Names are removed before anything else.** These become `[PERSON]` before the text is
  classified or stored:
  - names of people on the project's site, and the author's;
  - titled names ("Mr Perera", "baas Nimal");
  - 236 common Sri Lankan given names and surnames, in any case and without a title ("sunil absent",
    [#23](https://github.com/whoispasindu/SiteSense/issues/23)).

  The name list holds no word from the 1,719 training, validation and test sentences (a test checks
  this), and none that is an ordinary English word. Company names stay, except a listed surname
  inside one ("Gamage Hardware" becomes "[PERSON] Hardware"): when unsure, a word is removed. A rare
  name in none of these still gets through. The only module that calls out of the server is the
  weather client, and a test fails if another one appears before someone checks what it sends.
- The AI suggests; the author decides. Each stored issue keeps what the AI said (category, severity,
  confidence, model version) beside what the author confirmed, so disagreement can be measured.
- Only the author can analyse and confirm, on the day of the report. A tag not confirmed that day
  is lost; a 24-hour window or PM confirmation is proposed in
  [#24](https://github.com/whoispasindu/SiteSense/issues/24).
- Issues describe the work, never a person's performance.

## Limitations

- **No real reports yet.** Training data is generated from templates. The test sentences were
  written by the project in deliberately varied wording, mixing English with Sinhala and Tamil words
  in English letters. They are not real site reports, and the same people wrote the templates. Real
  reports will be harder. Collecting confirmed tags (with consent) and re-measuring comes before
  trusting these numbers.
- **Code-mixing is shallow.** Only common Sinhala and Tamil words written in English letters are
  covered. Sinhala or Tamil script is not.
- **`[PERSON]` lowers confidence.** The model never saw it in training, so sentences with a
  redacted name score lower (for example 0.52 for "[PERSON] absent", which is still tagged labour)
  and are more often highlighted for the author to check. The next retraining should put
  `[PERSON]` into the generated sentences.
- **One label per sentence.** A sentence with two problems gets the one that matters most, as the
  labelling guide says. The author can add the second.
- **Severity is weak** (above).
- **Size.** The DistilBERT file is 266 MB and loads in about 2 s on first use. Each API worker holds
  one copy in memory. Tagging takes about 20 ms a sentence on a laptop CPU, and the 20-sentence limit
  keeps a report under half a second.

## Model files and integrity

- Weights are never committed. `scripts/fetch_models.py` downloads them from the GitHub Release
  (or copies them from a folder) and refuses files whose SHA-256 or size differs from the committed
  manifest.
- The backend checks the hash again before onnxruntime parses the file. A tampered, truncated or
  missing file is never loaded; the tagger falls back to TF-IDF (1.0.0), logs it once, and records
  1.0.0 on the issues it tags.
- The TF-IDF model is JSON data, validated and scored in pure Python (no pickle), like the risk
  model.
- Golden predictions in the manifest prove the backend's ONNX path reproduces training within 1e-4.
  CI fetches the files and runs these checks with `SITESENSE_REQUIRE_MODELS=1`, so they cannot be
  skipped.

## Retraining

```
cd ml
python -m nlp.generate
python -m nlp.train_baseline --export
pip install -r requirements-transformer.txt   # PyTorch (CPU) and transformers: a large install
python -m nlp.train_distilbert                # about an hour on a laptop CPU (4 tuning runs + final)
python -m nlp.export_onnx                     # evidence, ONNX export and the manifest
```

A new version gets a new release tag and manifest, and must meet the same rule against the current
model on the hand-written test set. The test set is only extended, never used for training.
