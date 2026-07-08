def add(a: int, b: int) -> int:
    return a + b


def subtract(a: int, b: int) -> int:
    # BUG: 应该是 a - b
    return a + b