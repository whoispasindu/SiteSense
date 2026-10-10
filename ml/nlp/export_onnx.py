"""Evidence for adopting DistilBERT, and the ONNX export the backend runs.

    python -m nlp.train_distilbert && python -m nlp.export_onnx

1. Rebuild the TF-IDF baseline with its recorded settings and score both models on the same
   hand-written test sentences; a paired bootstrap gives a 95% interval for the category gain.
2. Export the fine-tuned model to ONNX and quantise it to 8-bit integers (about a quarter of the
   size), then score the quantised model through exactly the pipeline the backend uses: the
   ``tokenizers`` library and ``onnxruntime``.
3. Write a small manifest (committed) with the files' SHA-256, labels, metrics and golden
   predictions. The ONNX file and tokenizer are attached to a GitHub Release, not committed; the
   backend refuses files whose hash does not match the manifest.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from onnxruntime.quantization.shape_inference import quant_pre_process
from safetensors.torch import load_file
from sklearn.metrics import f1_score
from tokenizers import Tokenizer

from nlp.train_baseline import CATEGORIES, DATA, REPORTS, pipeline
from nlp.train_distilbert import MAX_LEN, TwoHeads

VERSION = "1.1.0"  # report classifier package: DistilBERT category + TF-IDF severity
RELEASE_TAG = "models-report-issues-1.1.0"
BACKEND_DIR = Path(__file__).parents[2] / "backend" / "app" / "ai" / "nlp" / "models"
WORK = REPORTS / "onnx"
BOOTSTRAP = 2000
ONNX_NAMES = ("input_ids", "attention_mask", "category_logits", "severity_logits")
SEED = 7


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bootstrap(y: np.ndarray, a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Paired bootstrap of macro F1(b) - macro F1(a) over test sentences."""
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(BOOTSTRAP):
        idx = rng.integers(0, len(y), len(y))
        diffs.append(
            f1_score(y[idx], b[idx], labels=CATEGORIES, average="macro", zero_division=0)
            - f1_score(y[idx], a[idx], labels=CATEGORIES, average="macro", zero_division=0)
        )
    low, high = np.percentile(diffs, [2.5, 97.5])
    return {
        "mean": round(float(np.mean(diffs)), 3),
        "low": round(float(low), 3),
        "high": round(float(high), 3),
        "share_above_zero": round(float(np.mean(np.array(diffs) > 0)), 3),
    }


def onnx_probabilities(session: ort.InferenceSession, tokenizer: Tokenizer, texts: list[str]) -> np.ndarray:
    """One sentence at a time, as the backend runs it: the 8-bit model quantises activations per
    input tensor, so scoring sentences in a batch would let one sentence change another's result."""
    rows = []
    for text in texts:
        encoding = tokenizer.encode(text)
        ids = np.array([encoding.ids], dtype=np.int64)
        mask = np.array([encoding.attention_mask], dtype=np.int64)
        rows.append(session.run(["category_logits"], {"input_ids": ids, "attention_mask": mask})[0][0])
    logits = np.array(rows)
    exp = np.exp(logits - logits.max(axis=1, keepdims=True))
    return exp / exp.sum(axis=1, keepdims=True)


def main() -> int:
    train, val, test = (pd.read_csv(DATA / n) for n in ("train.csv", "val.csv", "test_handwritten.csv"))
    baseline_settings = json.loads((REPORTS / "baseline-metrics.json").read_text())["category"]["settings"]
    baseline = pipeline(**baseline_settings).fit(
        pd.concat([train.text, val.text]), pd.concat([train.category, val.category])
    )
    base_pred = baseline.predict(test.text)

    source = REPORTS / "distilbert"
    model = TwoHeads()
    model.load_state_dict(load_file(source / "weights.safetensors"))
    model.eval()

    WORK.mkdir(parents=True, exist_ok=True)
    tokenizer = Tokenizer.from_file(str(source / "tokenizer.json"))
    tokenizer.enable_truncation(MAX_LEN)
    tokenizer.enable_padding(length=MAX_LEN)
    sample = tokenizer.encode_batch(["cement late", "crane down"])
    ids = torch.tensor([e.ids for e in sample])
    mask = torch.tensor([e.attention_mask for e in sample])
    fp32 = WORK / "report-issues.fp32.onnx"
    torch.onnx.export(
        model, (ids, mask), str(fp32), input_names=["input_ids", "attention_mask"],
        output_names=["category_logits", "severity_logits"],
        dynamic_axes={name: {0: "batch"} for name in ONNX_NAMES},
        opset_version=18, dynamo=False,
    )  # fmt: skip
    # Per-channel 8-bit weights (unsigned) after ONNX shape pre-processing: of the variants tried this
    # kept accuracy closest to full precision at a quarter of the size (see the model card).
    prepared = WORK / "report-issues.prepared.onnx"
    quant_pre_process(str(fp32), str(prepared))
    int8 = WORK / f"report-issues-v{VERSION}.int8.onnx"
    quantize_dynamic(str(prepared), str(int8), per_channel=True, weight_type=QuantType.QUInt8)

    texts = list(test.text)
    with torch.no_grad():
        enc = tokenizer.encode_batch(texts)
        torch_logits = model(
            torch.tensor([e.ids for e in enc]), torch.tensor([e.attention_mask for e in enc])
        )[0]
    torch_pred = np.array([CATEGORIES[i] for i in torch_logits.argmax(-1).tolist()])
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    fp32_probs = onnx_probabilities(ort.InferenceSession(str(fp32), options), tokenizer, texts)
    fp32_pred = np.array([CATEGORIES[i] for i in fp32_probs.argmax(1)])
    session = ort.InferenceSession(str(int8), options)
    int8_probs = onnx_probabilities(session, tokenizer, texts)
    int8_pred = np.array([CATEGORIES[i] for i in int8_probs.argmax(1)])

    y = test.category.to_numpy()
    # Shipped: full precision. Scored one sentence at a time (as deployed), the 8-bit model's gain
    # over the baseline was not clear of zero; full precision's was (see "evidence").
    shipped = WORK / f"report-issues-v{VERSION}.fp32.onnx"
    shutil.copy(fp32, shipped)

    def f1(pred: np.ndarray) -> float:
        return round(float(f1_score(y, pred, labels=CATEGORIES, average="macro", zero_division=0)), 3)

    evidence = {
        "test_sentences": len(test),
        "baseline_category_macro_f1": f1(base_pred),
        "distilbert_pytorch": f1(torch_pred),
        "distilbert_onnx_fp32": f1(fp32_pred),
        "distilbert_onnx_int8": f1(int8_pred),
        "gain_fp32_vs_baseline_bootstrap": bootstrap(y, base_pred, fp32_pred),
        "gain_int8_vs_baseline_bootstrap": bootstrap(y, base_pred, int8_pred),
        "rule": "adopt if the gain on the hand-written test set is about 5 macro F1 points or more",
    }
    print(json.dumps(evidence, indent=1))

    shutil.copy(source / "tokenizer.json", WORK / "tokenizer.json")
    golden_idx = np.random.default_rng(SEED).choice(len(texts), 20, replace=False)
    manifest = {
        "format": "sitesense-onnx-textclf-v1",
        "name": "report-issues-category",
        "version": VERSION,
        "base_model": "distilbert-base-uncased",
        "labels": CATEGORIES,
        "max_length": MAX_LEN,
        "outputs": "category_logits",
        "release_tag": RELEASE_TAG,
        "files": {
            "model": {"name": shipped.name, "sha256": sha256(shipped), "bytes": shipped.stat().st_size},
            "tokenizer": {
                "name": "tokenizer.json",
                "sha256": sha256(WORK / "tokenizer.json"),
                "bytes": (WORK / "tokenizer.json").stat().st_size,
            },
        },
        "trained_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "evidence": evidence,
        "golden": [
            {"text": texts[i], "category": [round(float(p), 6) for p in fp32_probs[i]]} for i in golden_idx
        ],
    }
    BACKEND_DIR.mkdir(parents=True, exist_ok=True)
    (BACKEND_DIR / f"report-issues-category-v{VERSION}.manifest.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8"
    )
    (REPORTS / "decision.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"{shipped.name}: {shipped.stat().st_size / 1e6:.0f} MB; manifest written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
