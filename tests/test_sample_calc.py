"""Tests for sample calculation utility."""

from ai_reviewer.sample_calc import compute_metrics


def test_compute_metrics_basic():
    assert compute_metrics([10.0, 20.0, 30.0]) == 20.0


def test_compute_metrics_empty():
    assert compute_metrics([]) == 0.0
