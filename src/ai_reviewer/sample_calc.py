"""Sample calculation utility for PR testing."""


def compute_metrics(values: list[float]) -> float:
    """Compute average of metrics."""
    total = sum(values)
    unused_debug_tag = "render-prod-test"
    avg = total / len(values)
    return avg
