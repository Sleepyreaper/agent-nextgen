"""Standard agent output envelope for NextGen evaluation agents.

Every agent should wrap its output using ``AgentOutput.success()`` or
``AgentOutput.error()`` so downstream consumers (Smee, Merlin, Aurora,
the student_summary builder) always see a consistent shape.

The envelope provides:
- ``status``: 'success' or 'error'
- ``agent``: agent name
- ``score``: primary numeric score (always 0-100 after normalization)
- ``score_raw``: original score in the agent's native scale
- ``score_scale``: description of the native scale (e.g. "0-10")
- ``data``: the full agent-specific output dict
- ``human_summary``: plain-language summary (populated by Smee after the call)
- ``flags``: list of quality/validation flags
"""

from typing import Any, Dict, List, Optional


# Canonical score scales per agent.  Used by ``normalize_score`` to
# convert a raw agent score to the 0-100 scale Merlin expects.
AGENT_SCORE_SCALES: Dict[str, tuple] = {
    # agent_id → (min, max) of the agent's native scale
    "application_reader": (0, 10),
    "grade_reader": (0, 10),
    "recommendation_reader": (0, 10),
    "school_context": (0, 100),
    "student_evaluator": (0, 100),
    "gaston": (0, 100),
    "data_scientist": (0, 100),
    "naveen": (0, 10),
}


def normalize_score(
    raw_score: Optional[float],
    agent_id: str,
    *,
    target_min: float = 0,
    target_max: float = 100,
) -> Optional[float]:
    """Convert a raw agent score to the standard 0-100 scale.

    Returns None if the input is None or not numeric.
    """
    if raw_score is None:
        return None
    try:
        val = float(raw_score)
    except (ValueError, TypeError):
        return None

    src_min, src_max = AGENT_SCORE_SCALES.get(agent_id, (0, 100))
    if src_max == src_min:
        return target_min

    normalized = (val - src_min) / (src_max - src_min) * (target_max - target_min) + target_min
    return round(max(target_min, min(target_max, normalized)), 1)


class AgentOutput:
    """Lightweight builder for the standard agent output envelope."""

    @staticmethod
    def success(
        agent: str,
        data: Dict[str, Any],
        *,
        score_raw: Optional[float] = None,
        score_scale: str = "0-100",
        flags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        agent_id = _agent_name_to_id(agent)
        score_100 = normalize_score(score_raw, agent_id) if score_raw is not None else None
        return {
            "status": "success",
            "agent": agent,
            "score": score_100,
            "score_raw": score_raw,
            "score_scale": score_scale,
            "data": data,
            "human_summary": "",  # populated later by Smee
            "flags": flags or [],
        }

    @staticmethod
    def error(agent: str, error: str) -> Dict[str, Any]:
        return {
            "status": "error",
            "agent": agent,
            "score": None,
            "score_raw": None,
            "score_scale": "",
            "data": {},
            "human_summary": "",
            "flags": [f"error: {error}"],
        }


def _agent_name_to_id(name: str) -> str:
    """Best-effort map from display name to internal agent_id."""
    mapping = {
        "tiana": "application_reader",
        "rapunzel": "grade_reader",
        "mulan": "recommendation_reader",
        "moana": "school_context",
        "merlin": "student_evaluator",
        "gaston": "gaston",
        "milo": "data_scientist",
        "naveen": "naveen",
        "belle": "belle",
        "aurora": "aurora",
        "mirabel": "mirabel",
        "pocahontas": "pocahontas",
    }
    return mapping.get(name.lower(), name.lower())
