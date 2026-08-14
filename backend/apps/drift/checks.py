"""The six things that separate a fixed workspace from a stock one.

Each check is a pure function over a workspace path returning (state, detail). They are
deliberately textual rather than executable: the scanner must be able to grade a workspace whose
backend has never booted, and must never mutate or run anything belonging to another app.

State is three-valued, not a bool. A frontend-only app cannot drift on a backend check, but it has
not satisfied it either; scoring "not applicable" as a pass would report 4/6 for a workspace where
only two checks ever ran, and that inflated score would collapse the moment someone enabled a
backend. N/A is carried through and excluded from the denominator instead.
"""

import os
import time
from typing import Callable, Dict, List, Optional, Tuple, Union

from typeguard import typechecked

# Sentinel for "this check does not apply here". Deliberately not True/False so it can never be
# silently counted as either.
P_NA = "na"

CheckState = Union[bool, str]

# A dist can only ever be considered fresh if it is newer than every source file. Parking the
# marker's mtime beyond any plausible build time makes that comparison permanently false. Anything
# comfortably past "now" works; the template ships 2038-01-01.
P_MIN_MARKER_MTIME = 2145916800.0  # 2038-01-01 UTC

P_MARKER_REL = os.path.join("frontend", "src", ".no-serve-mode")


@typechecked
def p_read(path: str) -> Optional[str]:
    """File contents, or None when it does not exist / cannot be decoded."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


@typechecked
def check_httpx_declared(ws: str) -> Tuple[CheckState, str]:
    """`httpx` is imported by apps/openswarm_host but stock pyproject.toml never declares it.

    It only resolves at all because `fastapi[standard]` happens to pull it in transitively. The day
    that extra changes, every app that talks to the host API breaks on import.
    """
    toml = p_read(os.path.join(ws, "backend", "pyproject.toml"))
    if toml is None:
        return P_NA, "no backend/pyproject.toml — backend not enabled for this app"
    if "httpx" in toml:
        return True, "httpx is declared explicitly"
    return False, "httpx is imported by openswarm_host but only resolves as a transitive of fastapi[standard]"


@typechecked
def check_ensurepip_guard(ws: str) -> Tuple[CheckState, str]:
    """run.sh must reject an interpreter that cannot build a venv, not just one that isn't Python 3.

    The bundled interpreter ships without `ensurepip`, so `python3 -m venv` yields a venv with no
    pip and the install dies on "No module named pip". A version check alone accepts it.
    """
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    if sh is None:
        return P_NA, "no backend/run.sh — backend not enabled for this app"
    if "ensurepip" in sh:
        return True, "run.sh probes ensurepip before accepting an interpreter"
    return False, "run.sh accepts any python3, including the bundled one that cannot create a venv"


@typechecked
def check_venv_health_gate(ws: str) -> Tuple[CheckState, str]:
    """The install-skip sentinel must be corroborated by a venv that actually has pip.

    Stock run.sh skips the whole venv+install block on the sentinel alone, so a hollow venv paired
    with a stale sentinel boots straight into a broken interpreter on every single start, with no
    path to self-heal.
    """
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    if sh is None:
        return P_NA, "no backend/run.sh — backend not enabled for this app"
    if "venv_healthy" in sh:
        return True, "sentinel is corroborated by a pip probe, and an unusable venv is rebuilt"
    return False, "a stale sentinel over a hollow venv is trusted forever with no way to self-heal"


@typechecked
def check_pythonpath_stripped(ws: str) -> Tuple[CheckState, str]:
    """pip and uvicorn must run with PYTHONPATH unset.

    OpenSwarm exports a PYTHONPATH pointing at the app bundle's own site-packages. That shadows the
    venv, so pip reports success while installing nothing and uvicorn imports the bundle's copies of
    fastapi/typeguard instead of the app's.
    """
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    if sh is None:
        return P_NA, "no backend/run.sh — backend not enabled for this app"
    if "env -u PYTHONPATH" in sh:
        return True, "pip and uvicorn both run with PYTHONPATH stripped"
    return False, "the bundle's site-packages shadows the venv; installs silently no-op"


@typechecked
def check_cache_populated_gate(ws: str) -> Tuple[CheckState, str]:
    """backend_init.sh must gate the warm cache on a completion marker, not on the directory.

    A `-d` test passes for a half-written cache left behind by a failed build, and that broken venv
    then gets copied into every app seeded afterwards.
    """
    sh = p_read(os.path.join(ws, "backend_init.sh"))
    if sh is None:
        return P_NA, "no backend_init.sh — this workspace predates it or is a partial seed"
    if "cache_usable" in sh or ".populated" in sh:
        return True, "warm cache is gated on a completion marker plus a real interpreter"
    return False, "warm cache is accepted on a bare directory test; a failed build gets copied forward"


@typechecked
def check_serve_mode_marker(ws: str) -> Tuple[CheckState, str]:
    """The serve-mode marker must exist AND carry a far-future mtime.

    Serve-mode decides freshness by comparing dist's mtime against the newest file under
    frontend/. That check is frontend-only, so an app with a backend gets "restarted" into a static
    bundle with nothing serving /api. It also deadlocks restart.sh: the sentinel watcher skips
    runtimes that aren't running, and a process-less runtime never is.

    The mtime half matters as much as the file: git does not preserve mtimes, so a clone lands this
    file with a checkout-time mtime and the workaround silently stops working.
    """
    marker = os.path.join(ws, P_MARKER_REL)
    if not os.path.isfile(marker):
        return False, "no marker: serve-mode can park this app in a static bundle with no backend"
    mtime = os.path.getmtime(marker)
    if mtime < P_MIN_MARKER_MTIME:
        return False, (
            f"marker present but its mtime is {time.strftime('%Y-%m-%d', time.localtime(mtime))}, "
            "not far-future — a build newer than this defeats it (this is what a git clone leaves behind)"
        )
    return True, "marker present with a far-future mtime; serve-mode can never win"


P_CHECKS: List[Dict[str, object]] = [
    {
        "id": "httpx_declared",
        "label": "httpx declared in pyproject.toml",
        "fn": check_httpx_declared,
        "severity": "medium",
        "fix": "Add \"httpx\" to [project].dependencies in backend/pyproject.toml.",
    },
    {
        "id": "ensurepip_guard",
        "label": "run.sh rejects interpreters without ensurepip",
        "fn": check_ensurepip_guard,
        "severity": "high",
        "fix": "Add a py_usable() helper that probes `import ensurepip`, and select the interpreter through it.",
    },
    {
        "id": "venv_health_gate",
        "label": "venv health gate on the install sentinel",
        "fn": check_venv_health_gate,
        "severity": "high",
        "fix": "Add venv_healthy() (interpreter exists AND `-m pip --version` works); require it alongside the sentinel and rm -rf the venv when it fails.",
    },
    {
        "id": "pythonpath_stripped",
        "label": "PYTHONPATH stripped for pip and uvicorn",
        "fn": check_pythonpath_stripped,
        "severity": "high",
        "fix": "Run every venv invocation through `env -u PYTHONPATH`, including the final exec of uvicorn.",
    },
    {
        "id": "cache_populated_gate",
        "label": "warm cache gated on a completion marker",
        "fn": check_cache_populated_gate,
        "severity": "medium",
        "fix": "Replace the `-d $CACHE_ROOT` test with cache_usable(): require .populated plus a real venv interpreter.",
    },
    {
        "id": "serve_mode_marker",
        "label": "serve-mode marker present and far-future",
        "fn": check_serve_mode_marker,
        "severity": "high",
        "fix": "Create frontend/src/.no-serve-mode, then `touch -t 203801010000` it.",
    },
]


@typechecked
def p_grade_workspace(ws: str) -> Dict[str, object]:
    """Run every check against one workspace. Never raises: one bad workspace can't kill a scan."""
    results: List[Dict[str, object]] = []
    for spec in P_CHECKS:
        fn: Callable[[str], Tuple[CheckState, str]] = spec["fn"]  # type: ignore[assignment]
        try:
            state, detail = fn(ws)
        except Exception as exc:  # a scan must degrade, not abort
            state, detail = False, f"check raised: {exc}"
        results.append({
            "id": spec["id"],
            "label": spec["label"],
            "severity": spec["severity"],
            "fix": spec["fix"],
            "state": P_NA if state == P_NA else ("pass" if state else "fail"),
            "detail": detail,
        })
    failed = sum(1 for r in results if r["state"] == "fail")
    applicable = sum(1 for r in results if r["state"] != P_NA)
    return {
        "checks": results,
        "failed": failed,
        "applicable": applicable,
        "passed": applicable - failed,
    }
