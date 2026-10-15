"""Single source of truth for job-name normalization.

Derived from scanning every real_*.html fixture:
  Job column:      Sandbox-Testing, PERF, LOAD, BATS, ASAN build, ASAN AURA, LSAN build,
                   LSAN AURA, TSAN build, Baseline Regression
  "Not selected":  PERF, LOAD, BATS, ASAN build, LSAN build, TSAN build, Baseline Regression
Short aliases from the spec (ASAN, Baseline, ...) are mapped too. The API exposes this
mapping (GET /api/meta) so the frontend never keeps its own copy.
"""
import re

CANONICAL_JOBS = [
    "PERF",
    "LOAD",
    "BATS",
    "ASAN build",
    "ASAN AURA",
    "LSAN build",
    "LSAN AURA",
    "TSAN build",
    "Baseline Regression",
]

# Keys are lower-case with single spaces.
JOB_NAME_MAP: dict[str, str] = {
    "perf": "PERF",
    "load": "LOAD",
    "bats": "BATS",
    "asan": "ASAN build",
    "asan build": "ASAN build",
    "asan aura": "ASAN AURA",
    "lsan": "LSAN build",
    "lsan build": "LSAN build",
    "lsan aura": "LSAN AURA",
    "tsan": "TSAN build",
    "tsan build": "TSAN build",
    "baseline": "Baseline Regression",
    "baseline regression": "Baseline Regression",
}


def _key(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


def normalize_job_name(name: str) -> str:
    """Return the canonical job name; unknown names are returned whitespace-cleaned."""
    cleaned = re.sub(r"\s+", " ", name).strip()
    return JOB_NAME_MAP.get(_key(name), cleaned)


def is_known_job(name: str) -> bool:
    return _key(name) in JOB_NAME_MAP
