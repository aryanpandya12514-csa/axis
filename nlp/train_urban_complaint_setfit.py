#!/usr/bin/env python3
"""
Train a SetFit classifier for urban complaint routing.

Input:
    training_complaints.csv with exact columns: text,label

Output:
    ./urban-complaint-setfit-model
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from datasets import Dataset
from sklearn.model_selection import train_test_split
from setfit import SetFitModel, SetFitTrainer
from sentence_transformers.losses import CosineSimilarityLoss

SEED = 42
CSV_PATH = Path("training_complaints.csv")
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
OUTPUT_DIR = Path("./urban-complaint-setfit-model")
BATCH_SIZE = 16
NUM_EPOCHS = 2
TEST_TEXT = (
    "Street is dark because the pole light is dead, but there are also unknown men loitering near the corner at night."
)


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def load_and_validate_data(csv_path: Path) -> tuple[pd.DataFrame, list[str], dict[str, int], dict[int, str]]:
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing input file: {csv_path.resolve()}")

    df = pd.read_csv(csv_path)
    expected_cols = ["text", "label"]
    if list(df.columns) != expected_cols:
        raise ValueError(f"CSV columns must be exactly {expected_cols}, got {list(df.columns)}")

    df = df.dropna(subset=["text", "label"]).copy()
    df["text"] = df["text"].astype(str).str.strip()
    df["label"] = df["label"].astype(str).str.strip()
    df = df[(df["text"] != "") & (df["label"] != "")].reset_index(drop=True)

    if df.empty:
        raise ValueError("No usable rows found in CSV.")

    labels = sorted(df["label"].unique().tolist())
    if len(labels) < 2:
        raise ValueError("Need at least 2 unique labels for classification.")

    label2id = {label: idx for idx, label in enumerate(labels)}
    id2label = {idx: label for label, idx in label2id.items()}
    df["label_id"] = df["label"].map(label2id).astype(int)
    return df, labels, label2id, id2label


def main() -> None:
    set_seed(SEED)

    # Force CPU execution so the script is safe on a machine without a GPU.
    # If CUDA exists, it is intentionally not used here.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    device = "cpu"

    df, labels, label2id, id2label = load_and_validate_data(CSV_PATH)

    train_df, eval_df = train_test_split(
        df[["text", "label_id"]],
        test_size=0.2,
        random_state=SEED,
        stratify=df["label_id"],
    )

    train_dataset = Dataset.from_pandas(
        train_df.rename(columns={"label_id": "label"}).reset_index(drop=True),
        preserve_index=False,
    )
    eval_dataset = Dataset.from_pandas(
        eval_df.rename(columns={"label_id": "label"}).reset_index(drop=True),
        preserve_index=False,
    )

    model = SetFitModel.from_pretrained(MODEL_NAME, device=device)

    trainer = SetFitTrainer(
        model=model,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        loss_class=CosineSimilarityLoss,
        batch_size=BATCH_SIZE,
        num_epochs=NUM_EPOCHS,
        column_mapping={"text": "text", "label": "label"},
        metric="accuracy",
    )

    # Contrastive geometry intuition:
    # Each training step reshapes the embedding space so complaints with the same
    # route label move closer together, while different labels are pushed farther apart.
    # The result is tight semantic clusters that make routing robust for short, messy text.
    trainer.train()
    metrics = trainer.evaluate()
    print("Evaluation metrics:", metrics)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(OUTPUT_DIR))

    with (OUTPUT_DIR / "label_mapping.json").open("w", encoding="utf-8") as f:
        json.dump({"label2id": label2id, "id2label": id2label}, f, indent=2, ensure_ascii=False)

    print(f"Model saved to: {OUTPUT_DIR.resolve()}")

    # Final self-check: load the saved model and run one ambiguous prediction.
    loaded_model = SetFitModel.from_pretrained(str(OUTPUT_DIR), device=device)
    predicted = loaded_model.predict([TEST_TEXT])[0]

    if torch.is_tensor(predicted):
        predicted_label = id2label[int(predicted.item())]
    elif isinstance(predicted, (int, np.integer)):
        predicted_label = id2label[int(predicted)]
    else:
        predicted_label = str(predicted)

    print("\nSample complaint:")
    print(TEST_TEXT)
    print("Predicted route:", predicted_label)


if __name__ == "__main__":
    main()
