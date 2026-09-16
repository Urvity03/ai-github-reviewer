"""ML/AI specific review rules, heuristic checks, and prompt guidelines."""

from __future__ import annotations

import re

from ai_reviewer.models.review import CategoryEnum, ReviewFinding, SeverityEnum

ML_IMPORT_KEYWORDS = {
    "torch",
    "tensorflow",
    "tf",
    "sklearn",
    "scikit-learn",
    "keras",
    "transformers",
    "datasets",
    "xgboost",
    "lightgbm",
    "catboost",
    "scipy",
    "pandas",
    "numpy",
    "optuna",
    "wandb",
    "mlflow",
}


def is_ml_related_file(filename: str, source_code: str) -> bool:
    """Detect if a file contains machine learning or data science code."""
    lower_name = filename.lower()
    if any(k in lower_name for k in ["train", "model", "dataset", "preprocess", "pipeline", "infer", "eval", "loss"]):
        return True

    # Check for ML imports
    for kw in ML_IMPORT_KEYWORDS:
        if f"import {kw}" in source_code or f"from {kw}" in source_code:
            return True

    return False


def run_heuristic_ml_checks(filename: str, source_code: str) -> list[ReviewFinding]:
    """Perform deterministic checks for common ML bugs and anti-patterns."""
    findings: list[ReviewFinding] = []
    lines = source_code.splitlines()

    for idx, line in enumerate(lines, start=1):
        # 1. Test set data leakage: fit_transform on test data or with test argument
        is_leakage = (
            re.search(r"(?i)\b(test_data|test_x|x_test|x_val|val_data|eval_data)\b.*\.fit_transform\(", line)
            or re.search(r"(?i)\.fit_transform\([^)]*\b(test_data|test_x|x_test|x_val|val_data|eval_data|x_eval|eval_x)\b", line)
        )
        if is_leakage:
            findings.append(
                ReviewFinding(
                    severity=SeverityEnum.HIGH,
                    category=CategoryEnum.ML,
                    title="Data Leakage: fit_transform called on validation/test set",
                    description=(
                        f"Line {idx} appears to call `fit_transform()` on a test or validation dataset. "
                        "Transformers must be fitted strictly on the training set (`fit()` / `fit_transform()`), "
                        "and only applied to test/validation data via `transform()`. Fitting on evaluation data leaks "
                        "target/feature distributions into the model."
                    ),
                    file=filename,
                    line=idx,
                    suggested_fix="Use `.transform()` instead of `.fit_transform()` on validation or test sets.",
                    confidence=0.95,
                )
            )

        # 2. PyTorch evaluation without torch.no_grad() or model.eval()
        if "def predict(" in line or "def evaluate(" in line:
            # Check upcoming lines for torch inference without torch.no_grad()
            window = "\n".join(lines[idx : min(idx + 15, len(lines))])
            if "model(" in window and "torch.no_grad()" not in window and "inference_mode" not in window:
                findings.append(
                    ReviewFinding(
                        severity=SeverityEnum.MEDIUM,
                        category=CategoryEnum.ML,
                        title="PyTorch Inference: Missing `torch.no_grad()` or `torch.inference_mode()`",
                        description=(
                            f"In function around line {idx}, model evaluation/prediction is performed without "
                            "`with torch.no_grad():` or `@torch.inference_mode()`. This consumes significant GPU/CPU "
                            "memory storing gradient computation graphs during inference."
                        ),
                        file=filename,
                        line=idx,
                        suggested_fix="Wrap inference calls inside `with torch.no_grad():` or use `@torch.inference_mode()`.",
                        confidence=0.85,
                    )
                )

        # 3. Missing random seed in train_test_split
        if "train_test_split(" in line and "random_state=" not in line:
            findings.append(
                ReviewFinding(
                    severity=SeverityEnum.LOW,
                    category=CategoryEnum.ML,
                    title="Reproducibility: `train_test_split` without explicit `random_state`",
                    description=(
                        f"Line {idx} calls `train_test_split` without setting `random_state`. "
                        "This leads to nondeterministic train/test splits across runs, breaking experiment "
                        "reproducibility."
                    ),
                    file=filename,
                    line=idx,
                    suggested_fix="Pass an explicit `random_state=42` (or seed parameter) to `train_test_split`.",
                    confidence=0.88,
                )
            )

    return findings


ML_SYSTEM_PROMPT_GUIDELINES = """
## ML / AI Specific Review Guidelines
When analyzing Machine Learning, Deep Learning, or Data Science code, rigorously evaluate:
1. **Data Leakage & Contamination**:
   - Verify that data standardization/imputation/encoding is fit solely on train splits and transformed on validation/test splits.
   - Look for temporal leakage in time-series data (e.g. random shuffling instead of chronological splitting).
   - Check for target leakage in feature engineering (features that incorporate future information or target indicators).
2. **Evaluation & Metrics**:
   - Check if metrics match class distribution (e.g. accuracy used for severely imbalanced classes instead of PR-AUC / F1 / MCC).
   - Beware of hyperparameter tuning directly against the final test set.
3. **Reproducibility**:
   - Check for deterministic seeds in PyTorch (`torch.manual_seed`), NumPy (`np.random.seed`), and random splitters.
4. **Deep Learning Best Practices**:
   - PyTorch: Ensure `model.eval()` and `torch.no_grad()` are set during inference.
   - Ensure tensors and models share identical device locations (`.to(device)`).
   - Ensure `optimizer.zero_grad()` is invoked before `loss.backward()`.
5. **NLP / Tokenization**:
   - Verify tokenizers and preprocessors match the model vocabulary and truncation/padding policies.
"""
