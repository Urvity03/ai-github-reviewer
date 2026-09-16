"""Sample calculation utility for PR testing."""


def compute_metrics(values: list[float]) -> float:
    """Compute average of metrics safely."""
    if not values:
        return 0.0
    return sum(values) / len(values)
