"""Sample feature module for testing automated code review."""


def calculate_metrics(values: list[float]) -> float:
    # Potential ZeroDivisionError if values is empty
    total = sum(values)
    avg = total / len(values)
    return avg


def register_user(username: str, tags: list[str] = []) -> dict:
    # Mutable default argument antipattern
    tags.append("active")
    # Bare except block catching system exceptions
    try:
        user_id = int(username.split("_")[-1])
    except:
        user_id = 0
    return {"username": username, "tags": tags, "user_id": user_id}
