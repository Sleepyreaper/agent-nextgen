"""Utility helpers for robust JSON handling."""
import json
from typing import Any


def safe_load_json(value: Any):
    """Safely parse JSON-like values.

    - If `value` is already a dict or list, return it unchanged.
    - If `value` is a string, attempt `json.loads` and fall back to returning
      the original string on failure.
    - Otherwise return the value as-is.
    """
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value
