"""Sample feature module for testing automated code review."""


def calculate_metrics(values: list[float]) -> float:
    """Calculate the average of numeric values safely."""
    if not values:
        return 0.0
    total = sum(values)
    avg = total / len(values)
    return avg


def register_user(username: str, tags: list[str] | None = None) -> dict:
    """Register user with safe default tags and specific exception handling."""
    resolved_tags = list(tags) if tags is not None else []
    resolved_tags.append("active")

    try:
        user_id = int(username.split("_")[-1])
    except (ValueError, IndexError):
        user_id = 0

    return {"username": username, "tags": resolved_tags, "user_id": user_id}
