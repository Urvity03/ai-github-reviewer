"""Tests for ML and AI code review heuristics."""

from ai_reviewer.ml_analysis import is_ml_related_file, run_heuristic_ml_checks
from ai_reviewer.models.review import CategoryEnum, SeverityEnum


def test_is_ml_related_file():
    assert is_ml_related_file("train_model.py", "") is True
    assert is_ml_related_file("service.py", "import torch\nimport numpy as np") is True
    assert is_ml_related_file("web_routes.py", "def index(): return 'hello'") is False


def test_heuristic_data_leakage_detection():
    code_with_leakage = """
from sklearn.preprocessing import StandardScaler

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.fit_transform(X_test)
"""
    findings = run_heuristic_ml_checks("pipeline.py", code_with_leakage)
    assert len(findings) >= 1
    leak_finding = next(f for f in findings if "Data Leakage" in f.title)
    assert leak_finding.category == CategoryEnum.ML
    assert leak_finding.severity == SeverityEnum.HIGH
    assert leak_finding.line == 6


def test_heuristic_pytorch_no_grad():
    pytorch_code = """
import torch

def evaluate(model, val_loader):
    for x, y in val_loader:
        pred = model(x)
"""
    findings = run_heuristic_ml_checks("model_eval.py", pytorch_code)
    assert any("torch.no_grad" in f.title for f in findings)
