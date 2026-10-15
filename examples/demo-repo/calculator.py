"""Small Python source used by ingestion acceptance."""


def add(left: int, right: int) -> int:
    """Return the sum of two integers."""
    return left + right


class Counter:
    """Track a count and allow explicit increments."""

    def __init__(self) -> None:
        self.value = 0

    def increment(self, amount: int = 1) -> int:
        self.value += amount
        return self.value
