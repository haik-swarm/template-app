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
import re
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

# `unset PYTHONPATH` (alone or alongside PYTHONHOME/VIRTUAL_ENV) clears the variable for every
# later command, which protects pip and uvicorn just as well as per-invocation `env -u`.
P_UNSET_PP_RE = re.compile(r"^\s*unset\s+[^\n#]*\bPYTHONPATH\b", re.M)

# A pip probe against the venv interpreter proves the venv is usable, whether it lives in a helper
# or is written inline as `"$VENV_PY" -m pip --version`.
P_PIP_PROBE_RE = re.compile(r"-m\s+pip\s+(--version|-V)\b")

# The line that actually launches the server. It is the strictest signal for PYTHONPATH: a script
# can strip the variable for pip and still hand a poisoned environment to uvicorn, which is the
# invocation that decides which fastapi/typeguard the app imports for the rest of its life.
P_UVICORN_LINE_RE = re.compile(r"^.*-m\s+uvicorn\b.*$", re.M)


@typechecked
def p_read(path: str) -> Optional[str]:
    """File contents, or None when it does not exist / cannot be decoded."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


# ############################### which variant is this side ###############################
#
# A failing check answers "this workspace lacks the protection". It does NOT answer "this workspace
# is the Terminal variant", and conflating the two is what made the page incoherent: converting to
# Terminal turned four rows red with messages like "trusted forever with no way to self-heal" while
# the header announced the conversion had succeeded.
#
# So each deciding check gets a second, POSITIVE detector for Terminal's own spelling. Terminal is
# recognised by what it contains, not by failing to be the template, which means a workspace that is
# neither — a half-applied swap, or something older than both — stays distinguishable from one that
# is deliberately on the other side.
#
# Each deciding check also carries a `terminal_detail`: what Terminal's spelling IS, stated flatly.
# The failure strings below are bug reports, and rightly so for a workspace that is behind both, but
# handing one to a user who just deliberately converted describes their choice as damage.
P_VERSION_PROBE = "sys.version_info[0]==3"
P_TERMINAL_SENTINEL_RE = re.compile(r'if \[\[ -d "\$VENV_DIR" && -f "\$SENTINEL" \]\]; then')
P_BARE_UVICORN_RE = re.compile(r'^\s*"\$VENV_PY" -m uvicorn\b', re.M)


@typechecked
def side_ensurepip_guard(ws: str) -> bool:
    """Terminal picks an interpreter on a bare `version_info[0]==3` probe and nothing more."""
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    return sh is not None and P_VERSION_PROBE in sh


@typechecked
def side_venv_health_gate(ws: str) -> bool:
    """Terminal trusts `-d $VENV_DIR && -f $SENTINEL` with no pip probe behind it."""
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    return sh is not None and bool(P_TERMINAL_SENTINEL_RE.search(sh))


@typechecked
def side_pythonpath_stripped(ws: str) -> bool:
    """Terminal launches uvicorn straight off "$VENV_PY", inherited PYTHONPATH intact."""
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    return sh is not None and bool(P_BARE_UVICORN_RE.search(sh))


@typechecked
def side_serve_mode_marker(ws: str) -> bool:
    """Terminal has no marker at all. A marker with a stale mtime is neither variant: that is what
    a git clone leaves behind, which is a broken template rather than a deliberate choice."""
    return not os.path.isfile(os.path.join(ws, P_MARKER_REL))


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

    Graded on behavior, not spelling: probing `ensurepip` and switching to `uv venv` are different
    solutions to the same problem, and uv arguably the better one since it never needs pip in the
    base interpreter at all. Matching only this template's wording would report a working app as
    broken, and an auto-fix built on that would overwrite a fix that already works.
    """
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    if sh is None:
        return P_NA, "no backend/run.sh — backend not enabled for this app"
    if "ensurepip" in sh:
        return True, "run.sh probes ensurepip before accepting an interpreter"
    if "uv venv" in sh:
        return True, "run.sh builds the venv with uv, which does not need ensurepip in the base interpreter"
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
    # Any real pip probe counts, whether it is wrapped in a helper named venv_healthy or written
    # inline as `"$VENV_PY" -m pip --version`. The behavior is what protects the boot, not the name.
    if "venv_healthy" in sh or P_PIP_PROBE_RE.search(sh):
        return True, "sentinel is corroborated by a pip probe, and an unusable venv is rebuilt"
    if "uv venv --clear" in sh:
        return True, "venv is rebuilt from scratch with uv --clear rather than trusting a stale sentinel"
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
    # `unset PYTHONPATH` near the top is the same fix with wider blast radius: it clears the
    # variable for every later command, so no individual invocation needs its own guard.
    if P_UNSET_PP_RE.search(sh):
        return True, "PYTHONPATH is unset for the whole script, so the venv resolves its own packages"
    # Otherwise the protection is per-invocation, and the launch line is the one that must have it.
    # Grading on "env -u PYTHONPATH appears somewhere" passes a script that shields pip and then
    # hands uvicorn the poisoned environment anyway — the failure this check exists to catch.
    launch = P_UVICORN_LINE_RE.search(sh)
    if launch is None:
        return False, "no uvicorn launch line found; cannot confirm the server starts with a clean environment"
    if "env -u PYTHONPATH" not in launch.group(0):
        return False, "uvicorn is launched with the bundle's PYTHONPATH still set; it imports the bundle's packages, not the venv's"
    if "env -u PYTHONPATH" not in sh.replace(launch.group(0), ""):
        return False, "uvicorn is protected but pip is not; installs into the venv still silently no-op"
    return True, "pip and uvicorn both run with PYTHONPATH stripped"


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
        # Labels on the four deciding checks name the DIMENSION, not the template's answer to it.
        # "run.sh rejects interpreters without ensurepip" is a claim, and rendering it beside a chip
        # reading Terminal put an assertion next to its own contradiction.
        "label": "interpreter selection in run.sh",
        "fn": check_ensurepip_guard,
        "side": side_ensurepip_guard,
        "terminal_detail": "run.sh selects an interpreter on a bare `version_info[0]==3` probe, which is Terminal's spelling",
        "severity": "high",
        "fix": "Add a py_usable() helper that probes `import ensurepip`, and select the interpreter through it.",
    },
    {
        "id": "venv_health_gate",
        "label": "install-skip sentinel in run.sh",
        "fn": check_venv_health_gate,
        "side": side_venv_health_gate,
        "terminal_detail": "run.sh skips the install on `-d $VENV_DIR && -f $SENTINEL` alone, which is Terminal's spelling",
        "severity": "high",
        "fix": "Add venv_healthy() (interpreter exists AND `-m pip --version` works); require it alongside the sentinel and rm -rf the venv when it fails.",
    },
    {
        "id": "pythonpath_stripped",
        "label": "PYTHONPATH handling for pip and uvicorn",
        "fn": check_pythonpath_stripped,
        "side": side_pythonpath_stripped,
        "terminal_detail": "run.sh launches uvicorn straight off \"$VENV_PY\" with PYTHONPATH inherited, which is Terminal's spelling",
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
        "label": "serve-mode marker",
        "fn": check_serve_mode_marker,
        "side": side_serve_mode_marker,
        "terminal_detail": "no serve-mode marker, so OpenSwarm's static serve-mode stays available, which is Terminal's spelling",
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
        # Three-way, and the third value is the point. "template" means this workspace has the
        # protection; "terminal" means it positively matches Terminal's own spelling; "neither"
        # means it has no protection AND does not look like Terminal either, i.e. it is genuinely
        # behind rather than deliberately on the other side. Only "neither" is a defect.
        side_fn: Optional[Callable[[str], bool]] = spec.get("side")  # type: ignore[assignment]
        if state == P_NA:
            side = P_NA
        elif state:
            side = "template"
        elif side_fn is None:
            # A shared check has no other side to be on: both variants implement it identically,
            # so failing it cannot mean "Terminal-flavoured" and can only mean behind both.
            side = "neither"
        else:
            try:
                side = "terminal" if side_fn(ws) else "neither"
            except Exception:
                side = "neither"
        # `detail` is written as a bug report, which is right for a workspace that is behind both and
        # wrong for one deliberately sitting in Terminal. Swap in the neutral description of what
        # Terminal's spelling IS, so a converted app is described rather than accused.
        if side == "terminal":
            detail = str(spec.get("terminal_detail") or detail)
        results.append({
            "id": spec["id"],
            "label": spec["label"],
            "severity": spec["severity"],
            "fix": spec["fix"],
            "state": P_NA if state == P_NA else ("pass" if state else "fail"),
            "side": side,
            "detail": detail,
        })
    failed = sum(1 for r in results if r["state"] == "fail")
    applicable = sum(1 for r in results if r["state"] != P_NA)
    return {
        "checks": results,
        "failed": failed,
        "applicable": applicable,
        "passed": applicable - failed,
        "variant": p_variant(results),
        # Shared checks that FAIL. Both variants pass these, so failing one means this workspace
        # predates both on that dimension — it is not a variant difference and converting sideways
        # will never address it. Surfaced separately because p_variant deliberately ignores these
        # when deciding, and silently ignoring a real failure is how Style Guide Extractor read as
        # a clean Terminal app while missing a fix neither variant goes without.
        "shared_missing": [
            r["id"] for r in results if r["id"] in P_VARIANT_BLIND and r["state"] == "fail"
        ],
    }


# Checks both variants satisfy identically, so they say nothing about which one you are looking at.
# Grading a workspace on them is what made a clean Terminal tree read as "2/6 drifted" — it scores
# two out of six precisely because these two pass everywhere, including in the variant that fails
# every check that actually discriminates. Kept here rather than imported from fixers to avoid a
# cycle; fixers imports this module.
P_VARIANT_BLIND = {"httpx_declared", "cache_populated_gate"}

# The deciding checks that read backend/run.sh. All three go N/A without a backend, which leaves
# serve_mode_marker as the only gradable one — and a variant named off that single bit is wrong
# twice over. It is one signal, and for a frontend-only app it is not even a signal: the marker
# exists to stop an app WITH a backend being parked in a static bundle, so its absence there is the
# correct state rather than Terminal's spelling. That is how a frontend-only app reported as a
# settled Terminal workspace while having no backend to hold either variant's scripts.
P_BACKEND_DECIDING = {"ensurepip_guard", "venv_health_gate", "pythonpath_stripped"}


@typechecked
def p_variant(results: List[Dict[str, object]]) -> str:
    """Which of the two variants this workspace is in, or 'mixed' / 'unknown'.

    There is no correct variant. A workspace is in one, the other, in between, or in neither, and
    only the in-between case is a problem worth a user's attention: it means a swap was half
    applied and the tree is in a state neither variant's author ever wrote. Reporting "N/6 passing"
    instead framed one variant as correct and the other as damage, which it is not.

    Decided on `side`, not on pass/fail. Reading a failure as "therefore Terminal" is what let a
    workspace that is merely behind both — a git clone whose marker lost its mtime, a tree older
    than either variant — report as a settled Terminal app. A check now has to positively look like
    Terminal to count as Terminal, and a file matching neither spelling is by definition a file
    neither author wrote, which is the same thing a half-applied swap produces: mixed, not settled.

    'unknown' is reserved for having nothing to go on at all (a frontend-only app), so it stays a
    shrug rather than doubling as a diagnosis.
    """
    # No backend, no variant. The variants differ almost entirely in backend/run.sh, so an app
    # without one is not in either and never was; saying so beats naming a variant off the single
    # check that happens to still be gradable.
    if not any(str(r["id"]) in P_BACKEND_DECIDING and r["side"] != P_NA for r in results):
        return "unknown"
    sides = [
        str(r["side"]) for r in results
        if r["id"] not in P_VARIANT_BLIND and r["side"] != P_NA
    ]
    if not sides:
        return "unknown"
    if all(s == "template" for s in sides):
        return "template"
    if all(s == "terminal" for s in sides):
        return "terminal"
    return "mixed"
