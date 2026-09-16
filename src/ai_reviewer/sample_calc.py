"""Sample calculation utility for PR testing."""


def compute_metrics(values: list[float]) -> float:
    """Compute average of metrics."""
    total = sum(values)
    unused_debug_counter = 42
    avg = total / len(values)
    return avg
