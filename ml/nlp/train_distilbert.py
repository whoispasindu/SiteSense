"""Fine-tune DistilBERT for the report issue classifier, for comparison with the TF-IDF baseline.

    pip install -r requirements-transformer.txt     # PyTorch (CPU) and transformers, about 1 GB
    python -m nlp.train_distilbert

One shared encoder (distilbert-base-uncased, loaded from safetensors) with two heads: category and
severity. Same protocol as the baseline: epochs and learning rate are chosen on the validation set
(held-out templates), then the model is trained on train + validation and the hand-written test set
is scored once. Writes models/report-nlp/distilbert-metrics.json. Weights go to
models/report-nlp/distilbert/ and are not committed (see .gitignore).
"""

from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import torch
from safetensors.torch import save_file
from torch import nn
from transformers import AutoModel, AutoTokenizer

from nlp import rules
from nlp.train_baseline import CATEGORIES, DATA, REPORTS, SEVERITIES, evaluate_predictions

BASE = "distilbert-base-uncased"
MAX_LEN = 48
BATCH = 16
SEED = 7
GRID = [{"lr": lr, "epochs": epochs} for lr in (3e-5, 5e-5) for epochs in (3, 5)]


class TwoHeads(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.encoder = AutoModel.from_pretrained(BASE, use_safetensors=True)
        hidden = self.encoder.config.dim
        self.dropout = nn.Dropout(0.1)
        self.category = nn.Linear(hidden, len(CATEGORIES))
        self.severity = nn.Linear(hidden, len(SEVERITIES))

    def forward(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        cls = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state[:, 0]
        cls = self.dropout(cls)
        return self.category(cls), self.severity(cls)


def seed_everything() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)


def encode(tokenizer: Any, frame: pd.DataFrame) -> dict[str, torch.Tensor]:
    batch = tokenizer(
        list(frame.text), padding="max_length", truncation=True, max_length=MAX_LEN, return_tensors="pt"
    )
    return {
        "input_ids": batch["input_ids"],
        "attention_mask": batch["attention_mask"],
        "category": torch.tensor([CATEGORIES.index(c) for c in frame.category]),
        "severity": torch.tensor([SEVERITIES.index(s) for s in frame.severity]),
    }


def train(tokenizer: Any, frame: pd.DataFrame, lr: float, epochs: int) -> TwoHeads:
    seed_everything()
    model = TwoHeads()
    data = encode(tokenizer, frame)
    optimiser = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * ((len(frame) + BATCH - 1) // BATCH)
    scheduler = torch.optim.lr_scheduler.LinearLR(
        optimiser, start_factor=1.0, end_factor=0.0, total_iters=steps
    )
    loss_fn = nn.CrossEntropyLoss()
    model.train()
    for _ in range(epochs):
        order = torch.randperm(len(frame))
        for start in range(0, len(frame), BATCH):
            idx = order[start : start + BATCH]
            cat_logits, sev_logits = model(data["input_ids"][idx], data["attention_mask"][idx])
            loss = loss_fn(cat_logits, data["category"][idx]) + loss_fn(sev_logits, data["severity"][idx])
            optimiser.zero_grad()
            loss.backward()
            optimiser.step()
            scheduler.step()
    return model


@torch.no_grad()
def predict(model: TwoHeads, tokenizer: Any, frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    model.eval()
    data = encode(tokenizer, frame)
    cats, sevs = [], []
    for start in range(0, len(frame), 64):
        cat_logits, sev_logits = model(
            data["input_ids"][start : start + 64], data["attention_mask"][start : start + 64]
        )
        cats += [CATEGORIES[i] for i in cat_logits.argmax(-1).tolist()]
        sevs += [SEVERITIES[i] for i in sev_logits.argmax(-1).tolist()]
    return cats, sevs


def main() -> int:
    torch.set_num_threads(max(1, torch.get_num_threads()))
    train_df, val_df, test_df = (
        pd.read_csv(DATA / n) for n in ("train.csv", "val.csv", "test_handwritten.csv")
    )
    tokenizer = AutoTokenizer.from_pretrained(BASE)

    tuning = []
    for settings in GRID:
        began = time.time()
        model = train(tokenizer, train_df, **settings)
        cats, sevs = predict(model, tokenizer, val_df)
        scores = {
            "category": evaluate_predictions(val_df.category, cats, CATEGORIES)["macro_f1"],
            "severity": evaluate_predictions(val_df.severity, sevs, SEVERITIES)["macro_f1"],
        }
        tuning.append({**settings, "val": scores, "seconds": round(time.time() - began)})
        print(f"{settings}: val {scores} ({tuning[-1]['seconds']} s)")
    best = max(tuning, key=lambda t: t["val"]["category"] + t["val"]["severity"])
    chosen = {"lr": best["lr"], "epochs": best["epochs"]}

    began = time.time()
    model = train(tokenizer, pd.concat([train_df, val_df]), **chosen)
    cats, sevs = predict(model, tokenizer, test_df)
    # Same severity rules as the baseline (rules.py), using this model's severity for each text.
    texts = list(test_df.text)
    stripped = [re.sub(r"\s+", " ", rules.REPEAT.sub(" ", t)).strip(" ,.-;") or t for t in texts]
    _, stripped_sevs = predict(
        model,
        tokenizer,
        pd.DataFrame({"text": stripped, "category": test_df.category, "severity": test_df.severity}),
    )
    lookup = dict(zip(texts, sevs, strict=True)) | {
        s: v for s, v in zip(stripped, stripped_sevs, strict=True)
    }
    sevs_rules = [rules.severity(t, lambda x: lookup[x]) for t in texts]
    results = {
        "model": f"{BASE} fine-tuned, two heads",
        "settings": chosen,
        "tuning": tuning,
        "category": {"test": evaluate_predictions(test_df.category, cats, CATEGORIES)},
        "severity": {
            "test": evaluate_predictions(test_df.severity, sevs, SEVERITIES),
            "test_with_rules": evaluate_predictions(test_df.severity, sevs_rules, SEVERITIES),
        },
        "final_training_seconds": round(time.time() - began),
        "trained_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "device": "cpu",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "distilbert-metrics.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    out = REPORTS / "distilbert"
    out.mkdir(exist_ok=True)
    save_file({k: v.contiguous() for k, v in model.state_dict().items()}, out / "weights.safetensors")
    tokenizer.save_pretrained(out)
    print(
        f"test: category {results['category']['test']['macro_f1']}, "
        f"severity {results['severity']['test']['macro_f1']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
