# ADR 0010: Report issue classifier and how the backend runs it

- Status: accepted
- Date: 2026-10-11

## Context

Phase 7 tags the problems written in daily reports (category and severity) so they can be counted,
followed up and used by the risk model. No real reports are available. The guide suggests comparing
a fine-tuned DistilBERT with a simpler model. The project owner's rule: **use DistilBERT in the
backend only if it beats the TF-IDF baseline by about 5 macro-F1 points on a hand-written test set;
keep the test set apart from training data; keep model weights out of normal commits.**

## Decisions

**Synthetic training data, hand-written test data.** `ml/nlp/generate.py` builds training and
validation sentences from phrase banks and templates, with site-style noise (abbreviations, missing
apostrophes, Sinhala and Tamil words in English letters). Validation holds out about 20% of the
templates per category; the first, random split scored 1.0 on validation and 0.64 on the test set,
because it measured memorised templates. The 199 test sentences are written by hand in wording the
templates do not produce, and a test fails if any of them appears in the training or validation
data.

**The comparison decided the model, per output.** On the test set DistilBERT gained 7.2 category
points (95% interval +1.2 to +13.4) and nothing on severity. So the shipped classifier (1.1.0) is
a hybrid: DistilBERT for category, TF-IDF and the labelling guide's rules for severity. TF-IDF
(1.0.0) is the full fallback. Each stored issue records the version that tagged it.

**Full precision, not 8-bit.** The 8-bit ONNX file is a quarter of the size, but its gain was not
clear of zero (+5.6, interval −0.9 to +12.1). Its activations are also quantised per input, so one
sentence's score changed with the others in a batch (a 0.087 probability difference on the golden
rows). Full precision has neither problem and is the one shipped (266 MB).

**ONNX Runtime in the backend, not PyTorch.** The backend adds `onnxruntime` and `tokenizers` (about
55 MB installed) instead of PyTorch and transformers (over 1 GB). An ONNX file is a graph of
standard operators, not code, so loading it does not run arbitrary Python, unlike a pickled
PyTorch checkpoint. Golden predictions in the manifest prove the ONNX path matches PyTorch.

**Weights in a GitHub Release, pinned by hash.** Git LFS would charge for bandwidth on every
clone and CI run and still needs a hash check. The files are attached to the release
`models-report-issues-1.1.0`. A small committed manifest pins each file's SHA-256 and size.
`scripts/fetch_models.py` verifies before moving a file into place, and the backend verifies again
before onnxruntime parses it. A mismatch or missing file means the TF-IDF fallback, never a
half-checked model. CI fetches with the workflow token and fails if the files are missing.

**The TF-IDF model is JSON, scored in pure Python.** As with the risk model (ADR 0009), no pickle is
loaded. The exporter writes the vocabulary, IDF weights and coefficients; the backend mirrors
scikit-learn's analyzers (words and `char_wb` n-grams, sublinear TF, L2 norm), and golden rows check
it matches.

**Severity rules sit around the model.** The guide's rules are applied in one place (`rules.py`,
kept in `ml/` and copied into the backend, with a test that the two copies are the same code).
Repetition is judged on the sentence with the repeat words removed, then raised one step; injury or
stopped work is high. On the test set the rules lift severity from 0.467 to 0.500.

**Names are redacted first.** Before classification or storage, names of people on the project's
site, the author's name and titled names become `[PERSON]`. The stored snippet is the redacted
sentence. Company names stay.

**Suggest, then confirm.** Analysis stores suggestions only. The author confirms (keep, edit,
remove, add) and ticks follow-ups, all unticked by default. Only the author, on the day of the
report, can analyse or confirm. Confirmation happens once.

**Follow-ups.**

- *Material request* (needs a confirmed material delay): opens a request form prefilled with the
  sentence; it closes when a request is raised from it, or the author dismisses it.
- *PM alert* (needs a confirmed high severity): notifies the site's project managers at once.
- *Stop-work* (needs a confirmed safety issue): notifies the PMs and stays open, shown as a banner on
  the project, until a project manager clears it. This is BR-11 in part: blocking the related tasks
  in the programme comes with the advanced schedule (Phase 9).

**Confirmed issues are risk inputs.** Risk model 1.1.0 adds material, safety and design issues
confirmed in the last 14 days, simulated in the training data with their own random stream so the
other numbers stayed the same. Confirming re-scores the project.

**Confidence threshold 0.6.** A fixed round number, not tuned. On the test set it flags a fifth of
tags, which hold half of the errors (see the model card).

## Consequences

- A fresh clone runs without the large files: tagging uses TF-IDF until `fetch_models.py` is run.
  In development the backend folder is mounted into the container, so fetched files are used
  directly. The production image copies `app/`, so fetch the files before building it; without
  them it runs on the fallback and logs that once.
- A new classifier version needs a new release tag and manifest, and must meet the same rule.
- Severity is weak (macro F1 0.50) and the UI treats it as a suggestion the author must check.
- The numbers come from synthetic training data and project-written test sentences. Real confirmed
  tags are needed before trusting them.
