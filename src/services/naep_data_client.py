"""
NAEP Data Service Client
========================
Queries the NCES Nation's Report Card (NAEP) API to retrieve
state- and national-level education performance data.

API docs: https://www.nationsreportcard.gov/api/data
Base URL: https://www.nationsreportcard.gov/DataService/GetAdhocData.aspx

This data enriches school context by providing objective, federally
collected benchmarks for how a state's students perform in mathematics and
reading relative to national averages — broken down by demographics,
free/reduced lunch eligibility, and achievement levels.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://www.nationsreportcard.gov/DataService/GetAdhocData.aspx"

# Two-letter codes the NAEP API uses for each US state / territory
STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY", "PR", "GU", "VI", "AS",
}

# Subjects we care about for school enrichment
SUBJECTS = {
    "mathematics": "MRPCM",   # Math composite
    "reading": "RRPCM",       # Reading composite
}

# Stat types we pull per subject
STAT_TYPES = {
    "mean": "MN:MN",
    "at_or_above_proficient": "ALC:AP",
}

# Variables we pull per subject — keep lean for API speed
VARIABLES = {
    "total": "TOTAL",
    "race": "SDRACE",
    "lunch_eligibility": "SLUNCH3",
}

# Use the most recent NAEP assessment year (adjust when new data drops)
DEFAULT_YEAR = "2022"
GRADES = ["8"]   # Grade 8 only — closest to high school (our applicants)

# Module-level in-memory cache (persists for the process lifetime)
_STATE_CACHE: Dict[str, Dict[str, Any]] = {}


class NAEPDataClient:
    """Client for the NAEP (Nation's Report Card) Data Service API."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "NextGenAgents/1.0 SchoolEnrichment",
        })

    # ── Low-level query ────────────────────────────────────────────

    def query(self, **params) -> List[Dict[str, Any]]:
        """
        Execute a raw NAEP DataService query.

        Returns the ``result`` array on success, or an empty list on failure.
        All params are forwarded as query-string parameters.
        """
        params.setdefault("type", "data")
        try:
            resp = self._session.get(BASE_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") == 200:
                return body.get("result", [])
            logger.warning("NAEP API returned status %s: %s", body.get("status"), body)
            return []
        except requests.RequestException as exc:
            logger.error("NAEP API request failed: %s", exc)
            return []
        except ValueError:
            logger.error("NAEP API returned non-JSON response")
            return []

    # ── High-level state profile builder ───────────────────────────

    def get_state_education_profile(
        self,
        state_code: str,
        year: str = DEFAULT_YEAR,
        include_national: bool = True,
    ) -> Dict[str, Any]:
        """
        Build a comprehensive education performance profile for a state.

        Pulls math + reading scores (mean, proficiency %) for grades 4 & 8,
        overall and broken down by race and lunch-eligibility, with national
        comparison data alongside.

        Returns a nested dict suitable for injection into Naveen / Moana
        analysis prompts:

        {
          "state_code": "GA",
          "year": 2022,
          "source": "NAEP / Nation's Report Card",
          "subjects": {
            "mathematics": {
              "grade_4": { ... },
              "grade_8": { ... }
            },
            "reading": { ... }
          }
        }
        """
        sc = state_code.upper()
        if sc not in STATE_CODES:
            logger.warning("Unknown state code '%s' for NAEP lookup.", sc)
            return {"state_code": sc, "error": "unknown_state"}

        cache_key = f"{sc}_{year}"
        if cache_key in _STATE_CACHE:
            logger.debug("NAEP cache hit for %s", cache_key)
            return _STATE_CACHE[cache_key]

        logger.info("📊 NAEP: Building education profile for %s (year %s)…", sc, year)
        t0 = time.time()

        jurisdiction = f"{sc},NT" if include_national else sc

        profile: Dict[str, Any] = {
            "state_code": sc,
            "year": int(year) if year.isdigit() else year,
            "source": "NAEP / Nation's Report Card (nces.ed.gov)",
            "subjects": {},
        }

        # Build all query combinations up-front
        tasks: List[Tuple[str, str, str, str, str, str, str]] = []
        # Each task: (subj_label, subscale, grade, stat_label, stat_code, var_label, var_code)
        for subj_label, subscale in SUBJECTS.items():
            for grade in GRADES:
                for stat_label, stat_code in STAT_TYPES.items():
                    for var_label, var_code in VARIABLES.items():
                        tasks.append((subj_label, subscale, grade, stat_label, stat_code, var_label, var_code))

        logger.info("📊 NAEP: Firing %d parallel API calls for %s…", len(tasks), sc)

        # Fire all queries in parallel — cap at 4 workers to avoid rate-limiting
        def _fetch(task_tuple):
            subj_label, subscale, grade, stat_label, stat_code, var_label, var_code = task_tuple
            rows = self.query(
                subject=subj_label,
                grade=grade,
                subscale=subscale,
                variable=var_code,
                jurisdiction=jurisdiction,
                stattype=stat_code,
                Year=year,
            )
            return (subj_label, grade, stat_label, var_label, rows)

        results: List[Tuple[str, str, str, str, List[Dict]]] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_fetch, t): t for t in tasks}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    task_info = futures[future]
                    logger.error("NAEP query failed for %s: %s", task_info, exc)

        # Assemble results into the profile structure
        # Value 999 is NAEP's "suppressed / not available" sentinel — skip it
        SUPPRESSED = 999

        for subj_label, grade, stat_label, var_label, rows in results:
            if not rows:
                continue
            subj_data = profile["subjects"].setdefault(subj_label, {})
            grade_key = f"grade_{grade}"
            grade_data = subj_data.setdefault(grade_key, {})

            for row in rows:
                value = row.get("value")
                if value is None or value == SUPPRESSED:
                    continue

                jur = row.get("jurisdiction", "")
                is_national = jur in ("NT", "NP")
                prefix = "national" if is_national else "state"
                val_label = row.get("varValueLabel", "All students")

                key = f"{prefix}_{stat_label}"
                if var_label != "total":
                    key = f"{prefix}_{var_label}_{stat_label}"

                if key not in grade_data:
                    grade_data[key] = {}

                grade_data[key][val_label] = round(value, 2)

        elapsed = round(time.time() - t0, 1)
        profile["fetch_time_seconds"] = elapsed
        logger.info("📊 NAEP: %s profile complete (%.1fs, %d subject groups)",
                     sc, elapsed, len(profile["subjects"]))

        _STATE_CACHE[cache_key] = profile
        return profile

    # ── Convenience: compact summary for agent prompts ─────────────

    def get_state_summary_for_prompt(
        self,
        state_code: str,
        year: str = DEFAULT_YEAR,
    ) -> str:
        """
        Return a human-readable text summary of a state's NAEP data
        suitable for injection into an LLM system/user prompt.
        """
        profile = self.get_state_education_profile(state_code, year)
        if profile.get("error"):
            return f"NAEP data not available for state '{state_code}'."

        lines = [
            f"=== NAEP Education Data for {state_code} ({year}) ===",
            f"Source: {profile.get('source', 'NAEP')}",
            "",
        ]

        for subj, subj_data in profile.get("subjects", {}).items():
            lines.append(f"── {subj.upper()} ──")
            for grade_key, metrics in subj_data.items():
                grade_label = grade_key.replace("_", " ").title()
                lines.append(f"  {grade_label}:")

                # Mean scores (the most useful single metric)
                state_mean = metrics.get("state_mean", {}).get("All students")
                national_mean = metrics.get("national_mean", {}).get("All students")
                if state_mean is not None and national_mean is not None:
                    diff = round(state_mean - national_mean, 1)
                    sign = "+" if diff >= 0 else ""
                    lines.append(
                        f"    Mean Score: {state_code} {state_mean} vs National {national_mean} ({sign}{diff})"
                    )

                # Proficiency
                state_prof = metrics.get("state_at_or_above_proficient", {}).get("All students")
                nat_prof = metrics.get("national_at_or_above_proficient", {}).get("All students")
                if state_prof is not None and nat_prof is not None:
                    lines.append(
                        f"    At/Above Proficient: {state_code} {state_prof:.1f}% vs National {nat_prof:.1f}%"
                    )

                # Race breakdown (mean)
                race_state = metrics.get("state_race_mean", {})
                race_nat = metrics.get("national_race_mean", {})
                if race_state:
                    parts = []
                    for race, val in race_state.items():
                        nat_val = race_nat.get(race)
                        if nat_val is not None:
                            parts.append(f"{race}: {val} (nat {nat_val})")
                        else:
                            parts.append(f"{race}: {val}")
                    if parts:
                        lines.append(f"    By Race: {'; '.join(parts)}")

                # Lunch eligibility (socioeconomic indicator)
                lunch_state = metrics.get("state_lunch_eligibility_mean", {})
                lunch_nat = metrics.get("national_lunch_eligibility_mean", {})
                if lunch_state:
                    parts = []
                    for cat, val in lunch_state.items():
                        if "not available" in cat.lower():
                            continue  # skip "Information not available" category
                        nat_val = lunch_nat.get(cat)
                        if nat_val is not None:
                            parts.append(f"{cat}: {val} (nat {nat_val})")
                        else:
                            parts.append(f"{cat}: {val}")
                    if parts:
                        lines.append(f"    By Lunch Eligibility: {'; '.join(parts)}")

                lines.append("")

        return "\n".join(lines)

    # ── Quick single-metric helpers ────────────────────────────────

    def get_state_math_mean(self, state_code: str, grade: int = 8, year: str = DEFAULT_YEAR) -> Optional[float]:
        """Return the composite math mean score for a state, or None."""
        rows = self.query(
            subject="mathematics", grade=str(grade), subscale="MRPCM",
            variable="TOTAL", jurisdiction=state_code.upper(),
            stattype="MN:MN", Year=year,
        )
        if rows:
            return round(rows[0].get("value", 0), 2)
        return None

    def get_state_reading_mean(self, state_code: str, grade: int = 8, year: str = DEFAULT_YEAR) -> Optional[float]:
        """Return the composite reading mean score for a state, or None."""
        rows = self.query(
            subject="reading", grade=str(grade), subscale="RRPCM",
            variable="TOTAL", jurisdiction=state_code.upper(),
            stattype="MN:MN", Year=year,
        )
        if rows:
            return round(rows[0].get("value", 0), 2)
        return None


# ── Module-level singleton ─────────────────────────────────────────
_client: Optional[NAEPDataClient] = None


def get_naep_client() -> NAEPDataClient:
    """Return (or create) the module-level NAEPDataClient singleton."""
    global _client
    if _client is None:
        _client = NAEPDataClient()
    return _client
