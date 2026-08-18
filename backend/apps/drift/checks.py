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

# Sentinel for "both variants pass this identically, so it names no variant". A passing check used
# to be hardcoded to side="patched", which meant the two shared checks reported a variant they
# cannot distinguish: Launch Film Agent Atlas showed cache_populated_gate as PATCHED while its
# backend_init.sh carried Default's inline `.populated` spelling, and the to-Default button could
# never clear it because there is no reverter to run.
P_SHARED = "shared"

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


@typechecked
def p_code_only(text: str) -> str:
    """`text` with whole-line comments removed, for questions about what a script DOES.

    Grading has to ignore prose. check_venv_health_gate accepted any file containing the substring
    "venv_healthy", and after a to-Default conversion the definition and every call are gone while
    a neighbouring comment still explains why the helper mattered — so the check read a sentence,
    reported "sentinel is corroborated by a pip probe", and graded a stock file as Patched. That is
    the same trap p_no_callers already dodges on the fixer side and the same one that produced two
    earlier bugs here: a comment asserting something the code does not do.

    Only whole-line comments are dropped. A trailing `#` inside a quoted string is not a comment,
    and stripping from the first `#` on a line would corrupt exactly the shell this is grading.
    """
    return "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("#"))

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


@typechecked
def p_declares_backend(ws: str) -> bool:
    """Whether this workspace runs a backend, asked the way the RUNTIME asks it.

    Serve-mode is gated on `BACKEND_PORT` in .env, not on a backend/ directory: runtime.py's
    p_start_new_mode reads `BACKEND_PORT` and refuses serve-mode outright when it is set to anything
    but NONE. Grading has to ask that same question, because a directory that exists while the port
    says NONE is a backend the runtime will never start.

    Falls back to the directory when there is no .env to read, which is the only case where the
    runtime's own signal is unavailable.
    """
    env_path = os.path.join(ws, ".env")
    try:
        with open(env_path, "r", encoding="utf-8", errors="ignore") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() != "BACKEND_PORT":
                    continue
                # The runtime strips an inline `# comment` before comparing, and the seeded .env
                # ships one on this very line, so a raw compare reads "NONE # backend port ..." and
                # never equals NONE.
                value = value.split("#", 1)[0].strip().strip('"').strip("'")
                return bool(value) and value != "NONE"
    except OSError:
        pass
    return os.path.isdir(os.path.join(ws, "backend"))


# ############################### which variant is this side ###############################
#
# A failing check answers "this workspace lacks the protection". It does NOT answer "this workspace
# is the Default variant", and conflating the two is what made the page incoherent: converting to
# Default turned four rows red with messages like "trusted forever with no way to self-heal" while
# the header announced the conversion had succeeded.
#
# So each deciding check gets a second, POSITIVE detector for Default's own spelling. Default is
# recognised by what it contains, not by failing to be Patched, which means a workspace that is
# neither — a half-applied swap, or something older than both — stays distinguishable from one that
# is deliberately on the other side.
#
# Each deciding check also carries a `default_detail`: what Default's spelling IS, stated flatly.
# The failure strings below are bug reports, and rightly so for a workspace that is behind both, but
# handing one to a user who just deliberately converted describes their choice as damage.
P_VERSION_PROBE = "sys.version_info[0]==3"
P_DEFAULT_SENTINEL_RE = re.compile(r'if \[\[ -d "\$VENV_DIR" && -f "\$SENTINEL" \]\]; then')
P_BARE_UVICORN_RE = re.compile(r'^\s*"\$VENV_PY" -m uvicorn\b', re.M)


@typechecked
def side_ensurepip_guard(ws: str) -> bool:
    """Default picks an interpreter on a bare `version_info[0]==3` probe and nothing more."""
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    return sh is not None and P_VERSION_PROBE in sh


@typechecked
def side_venv_health_gate(ws: str) -> bool:
    """Default trusts `-d $VENV_DIR && -f $SENTINEL` with no pip probe behind it."""
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    return sh is not None and bool(P_DEFAULT_SENTINEL_RE.search(sh))


@typechecked
def side_pythonpath_stripped(ws: str) -> bool:
    """Default launches uvicorn straight off "$VENV_PY", inherited PYTHONPATH intact."""
    sh = p_read(os.path.join(ws, "backend", "run.sh"))
    return sh is not None and bool(P_BARE_UVICORN_RE.search(sh))


@typechecked
def side_serve_mode_marker(ws: str) -> bool:
    """Default has no marker at all. A marker with a stale mtime is neither variant: that is what
    a git clone leaves behind, which is a broken Patched rather than a deliberate choice."""
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
    #
    # Asked of the code alone. A converted workspace can keep a comment mentioning venv_healthy long
    # after the helper and its callers are gone, and matching the raw text there graded a stock file
    # as Patched on the strength of a sentence.
    code = p_code_only(sh)
    if "venv_healthy" in code or P_PIP_PROBE_RE.search(code):
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

    This is the one axis that is entirely frontend-side: the marker lives under frontend/src, and
    nothing about it needs a backend/ directory to exist.

    It is also the one axis that only BITES without a backend. runtime.py:255 now refuses serve-mode
    for any workspace whose .env declares a BACKEND_PORT, so for a backend app this marker is
    redundant belt-and-braces. For a frontend-only app serve-mode is live, and this marker is the
    only thing deciding between a real vite process and a statically served bundle. An earlier
    version of this docstring had that exactly backwards and justified the marker by a
    backend-gets-parked-with-no-API failure the runtime no longer has.

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
        # Labels on the four deciding checks name the DIMENSION, not Patched's answer to it.
        # "run.sh rejects interpreters without ensurepip" is a claim, and rendering it beside a chip
        # reading Default put an assertion next to its own contradiction.
        "label": "interpreter selection in run.sh",
        "fn": check_ensurepip_guard,
        "side": side_ensurepip_guard,
        "default_detail": "run.sh selects an interpreter on a bare `version_info[0]==3` probe, which is Default V1.7.8-exp.8+'s spelling",
        "severity": "high",
        "fix": "Add a py_usable() helper that probes `import ensurepip`, and select the interpreter through it.",
    },
    {
        "id": "venv_health_gate",
        "label": "install-skip sentinel in run.sh",
        "fn": check_venv_health_gate,
        "side": side_venv_health_gate,
        "default_detail": "run.sh skips the install on `-d $VENV_DIR && -f $SENTINEL` alone, which is Default V1.7.8-exp.8+'s spelling",
        "severity": "high",
        "fix": "Add venv_healthy() (interpreter exists AND `-m pip --version` works); require it alongside the sentinel and rm -rf the venv when it fails.",
    },
    {
        "id": "pythonpath_stripped",
        "label": "PYTHONPATH handling for pip and uvicorn",
        "fn": check_pythonpath_stripped,
        "side": side_pythonpath_stripped,
        "default_detail": "run.sh launches uvicorn straight off \"$VENV_PY\" with PYTHONPATH inherited, which is Default V1.7.8-exp.8+'s spelling",
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
        "default_detail": "no serve-mode marker, so OpenSwarm's static serve-mode stays available, which is Default V1.7.8-exp.8+'s spelling",
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
        # Four-way, and the last two are the point. "patched" means this workspace has the
        # protection; "default" means it positively matches Default's own spelling; "neither"
        # means it has no protection AND does not look like Default either, i.e. it is genuinely
        # behind rather than deliberately on the other side; "shared" means the question does not
        # name a variant at all. Only "neither" is a defect.
        #
        # A check with no `side` detector has no Default spelling to recognise, which is the same
        # fact P_VARIANT_BLIND encodes and the same one fixers.P_SHARED_CHECKS refuses to revert.
        # Passing one means "this workspace has the fix", never "this workspace is Patched", so
        # answering "patched" put a variant name on the one axis that cannot carry one. That is
        # what made cache_populated_gate read PATCHED on a workspace whose backend_init.sh is
        # written Default's way, and left the row unmovable: eligible on the to-Default leg by
        # `side != target`, then dropped by p_plan because no reverter exists.
        side_fn: Optional[Callable[[str], bool]] = spec.get("side")  # type: ignore[assignment]
        if state == P_NA:
            side = P_NA
        elif state and side_fn is None:
            side = P_SHARED
        elif state:
            side = "patched"
        elif side_fn is None:
            # A shared check has no other side to be on: both variants implement it identically,
            # so failing it cannot mean "Default-flavoured" and can only mean behind both.
            side = "neither"
        else:
            try:
                side = "default" if side_fn(ws) else "neither"
            except Exception:
                side = "neither"
        # `detail` is written as a bug report, which is right for a workspace that is behind both and
        # wrong for one deliberately sitting in Default. Swap in the neutral description of what
        # Default's spelling IS, so a converted app is described rather than accused.
        if side == "default":
            detail = str(spec.get("default_detail") or detail)
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
        # a clean Default app while missing a fix neither variant goes without.
        "shared_missing": [
            r["id"] for r in results if r["id"] in P_VARIANT_BLIND and r["state"] == "fail"
        ],
    }


# Checks both variants satisfy identically, so they say nothing about which one you are looking at.
# Grading a workspace on them is what made a clean Default tree read as "2/6 drifted" — it scores
# two out of six precisely because these two pass everywhere, including in the variant that fails
# every check that actually discriminates. Kept here rather than imported from fixers to avoid a
# cycle; fixers imports this module.
P_VARIANT_BLIND = {"httpx_declared", "cache_populated_gate"}

# The deciding checks that read backend/run.sh. All three go N/A without a backend, leaving
# serve_mode_marker as the only gradable one.
#
# That used to force 'unknown', on the theory that the marker says nothing about a frontend-only
# app. The opposite is true. runtime.py:255 exempts every workspace declaring a BACKEND_PORT from
# serve-mode, so the marker is inert for backend apps and decisive for frontend-only ones — it is
# the ONLY variant axis that still does anything there. Refusing to grade on it meant the three
# frontend-only apps in this install were the only ones whose live difference the tool ignored,
# and both of the marker-carrying ones really do sit on the opposite side from the third.
P_BACKEND_DECIDING = {"ensurepip_guard", "venv_health_gate", "pythonpath_stripped"}


@typechecked
def p_variant(results: List[Dict[str, object]]) -> str:
    """Which of the two variants this workspace is in, or 'mixed' / 'unknown'.

    There is no correct variant. A workspace is in one, the other, in between, or in neither, and
    only the in-between case is a problem worth a user's attention: it means a swap was half
    applied and the tree is in a state neither variant's author ever wrote. Reporting "N/6 passing"
    instead framed one variant as correct and the other as damage, which it is not.

    Decided on `side`, not on pass/fail. Reading a failure as "therefore Default" is what let a
    workspace that is merely behind both — a git clone whose marker lost its mtime, a tree older
    than either variant — report as a settled Default app. A check now has to positively look like
    Default to count as Default, and a file matching neither spelling is by definition a file
    neither author wrote, which is the same thing a half-applied swap produces: mixed, not settled.

    'unknown' is reserved for having nothing to go on at all — every deciding check N/A — so it
    stays a shrug rather than doubling as a diagnosis. A frontend-only app is NOT that case: its
    serve-mode marker is a real, live variant difference, and the sides list below picks it up.
    """
    # Excluded two ways on purpose. P_VARIANT_BLIND is a hand-maintained id list; P_SHARED is
    # computed from the absence of a `side` detector, which is the same fact the check itself
    # already knows. Dropping either test would make this correct only for as long as the list and
    # the specs agree, and a check added later without a detector would silently start voting.
    sides = [
        str(r["side"]) for r in results
        if r["id"] not in P_VARIANT_BLIND and r["side"] not in (P_NA, P_SHARED)
    ]
    if not sides:
        return "unknown"
    if all(s == "patched" for s in sides):
        return "patched"
    if all(s == "default" for s in sides):
        return "default"
    return "mixed"
