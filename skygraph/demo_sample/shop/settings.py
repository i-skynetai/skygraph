"""Configuration, from the environment."""
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///shop.db")


def max_per_order() -> int:
    return int(os.environ.get("MAX_PER_ORDER", "10"))
