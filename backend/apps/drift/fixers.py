"""Patch generators: one per drift check, each turning a drifted file into a fixed one.

Every fixer is a pure function `(workspace) -> Optional[Edit]`. It reads, it computes new text, and
it returns it. Nothing here writes to disk — that is the endpoint's job, and keeping the two apart
is what makes a preview honest: the diff the user approves is produced by the same code path that
later applies it, so the preview can never disagree with the result.

Two rules every fixer obeys:

Idempotent. A fixer returns None when its check already passes, including when it passes via
somebody else's solution. Twelve of these workspaces were hand-fixed by earlier sessions in at
least three incompatible styles; re-applying our version on top would be a regression, not a
repair.

Insertion over rewrite. Where possible a fixer adds a helper and re-points call sites rather than
replacing a block wholesale. Across 15 observed run.sh variants, a wholesale replace would clobber
whatever else that workspace's author changed. If an anchor isn't found we return None and report
it, rather than guessing at a position.
"""

import os
import re
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from typeguard import typechecked

from backend.apps.drift.checks import (
    P_MARKER_REL,
    P_MIN_MARKER_MTIME,
    check_cache_populated_gate,
    check_ensurepip_guard,
    check_httpx_declared,
    check_pythonpath_stripped,
    check_serve_mode_marker,
    check_venv_health_gate,
    p_read,
)


class Edit(NamedTuple):
    """One file's before/after, plus the marker mtime side effect where relevant."""
    rel_path: str          # workspace-relative, e.g. "backend/run.sh"
    old_text: str
    new_text: str
    language: str
    note: str
    set_mtime: Optional[float] = None  # touch the file to this mtime after writing


P_SH = "bash"


# ############################### httpx ###############################

P_DEPS_OPEN_RE = re.compile(r"dependencies\s*=\s*\[")


@typechecked
def p_deps_span(toml: str) -> Optional[Tuple[int, int]]:
    """(start, end) of the dependencies array body, or None.

    A non-greedy `\\[(.*?)\\]` cannot do this: the first `]` it finds belongs to `"fastapi[standard]"`,
    so it splices new entries into the middle of that extras string and silently corrupts the file.
    Scan instead, tracking quotes so brackets inside a string never move the depth.
    """
    m = P_DEPS_OPEN_RE.search(toml)
    if not m:
        return None
    start = m.end()
    depth = 1
    quote = ""
    i = start
    while i < len(toml):
        ch = toml[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            nl = toml.find("\n", i)
            i = len(toml) if nl == -1 else nl
            continue
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return start, i
        i += 1
    return None


@typechecked
def fix_httpx_declared(ws: str) -> Optional[Edit]:
    rel = os.path.join("backend", "pyproject.toml")
    toml = p_read(os.path.join(ws, rel))
    if toml is None:
        return None
    if check_httpx_declared(ws)[0] is True:
        return None
    span = p_deps_span(toml)
    if span is None:
        return None
    body_start, body_end = span
    body = toml[body_start:body_end]
    # Match the indentation and quote style already used by the last entry so the result looks
    # like the file's author wrote it.
    entries = re.findall(r"^(\s*)([\"'])([^\"']+)\2\s*,?\s*$", body, re.M)
    if entries:
        indent, quote = entries[-1][0], entries[-1][1]
    else:
        indent, quote = "    ", '"'
    new_body = body.rstrip()
    if new_body and not new_body.endswith(","):
        new_body += ","
    new_body += f"\n{indent}{quote}httpx{quote},\n"
    new_toml = toml[:body_start] + new_body + toml[body_end:]
    return Edit(
        rel_path=rel,
        old_text=toml,
        new_text=new_toml,
        language="toml",
        note="Declare httpx explicitly instead of relying on it arriving as a transitive of fastapi[standard].",
    )


# ############################### run.sh: ensurepip ###############################

P_PY_USABLE_HELPER = '''# A candidate is only usable if it can actually BUILD a venv, which means importing ensurepip.
# The bundled interpreter ships without ensurepip, so `python3 -m venv` leaves a hollow venv with
# no pip and the install below dies on "No module named pip". Version-checking alone accepts it.
py_usable() {
    [[ -n "$1" ]] || return 1
    "$1" -c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" &>/dev/null || return 1
    "$1" -c "import ensurepip" &>/dev/null || return 1
    return 0
}

'''

P_PYTHON_DECL_RE = re.compile(r'^PYTHON=""\s*$', re.M)

# The two stock version-only probes: the OPENSWARM_PYTHON branch and the PATH-candidate loop.
P_OSPY_PROBE_RE = re.compile(
    r'if \[\[ -n "\$\{OPENSWARM_PYTHON:-\}" \]\] && "\$\{OPENSWARM_PYTHON\}" '
    r'-c "import sys; sys\.exit\(0 if sys\.version_info\[0\]==3 else 1\)" &>/dev/null; then'
)
P_CAND_PROBE_RE = re.compile(
    r'if command -v "\$candidate" &>/dev/null && "\$candidate" '
    r'-c "import sys; sys\.exit\(0 if sys\.version_info\[0\]==3 else 1\)" &>/dev/null; then'
)


@typechecked
def fix_ensurepip_guard(ws: str) -> Optional[Edit]:
    rel = os.path.join("backend", "run.sh")
    sh = p_read(os.path.join(ws, rel))
    if sh is None or check_ensurepip_guard(ws)[0] is True:
        return None
    if not (P_PYTHON_DECL_RE.search(sh) and P_OSPY_PROBE_RE.search(sh) and P_CAND_PROBE_RE.search(sh)):
        return None
    new = P_PYTHON_DECL_RE.sub(lambda m: P_PY_USABLE_HELPER + m.group(0), sh, count=1)
    new = P_OSPY_PROBE_RE.sub('if py_usable "${OPENSWARM_PYTHON:-}"; then', new, count=1)
    new = P_CAND_PROBE_RE.sub(
        'if command -v "$candidate" &>/dev/null && py_usable "$candidate"; then', new, count=1
    )
    new = new.replace(
        'echo "Error: No working Python 3 found."',
        'echo "Error: No Python 3 capable of creating a virtual environment was found."\n'
        '    echo "       (candidates must provide \'ensurepip\'; the bundled interpreter does not)"',
        1,
    )
    return Edit(
        rel_path=rel,
        old_text=sh,
        new_text=new,
        language=P_SH,
        note="Reject interpreters that cannot build a venv, instead of accepting any python3.",
    )


# ############################### run.sh: venv health gate ###############################

P_VENV_HELPERS = '''# OpenSwarm exports a PYTHONPATH pointing at the app bundle's own site-packages, which shadows
# this venv, so pip "succeeds" while silently no-opping deps. Everything below runs clean.
venv_py() { env -u PYTHONPATH "$VENV_PY" "$@"; }

# A venv is only trustworthy if its interpreter exists AND has pip. A venv built by an
# ensurepip-less interpreter satisfies `-d $VENV_DIR` but can never install anything.
venv_healthy() {
    [[ -x "$VENV_PY" ]] || return 1
    venv_py -m pip --version &>/dev/null || return 1
    return 0
}

'''

P_FAST_PATH_RE = re.compile(r'^if \[\[ -d "\$VENV_DIR" && -f "\$SENTINEL" \]\]; then\s*$', re.M)

P_SELF_HEAL = '''    # Drop a venv that exists but is unusable (e.g. copied in from a warm cache built without
    # pip); otherwise the install below fails on every boot with no way to self-heal.
    if [[ -d "$VENV_DIR" ]] && ! venv_healthy; then
        echo "Existing .venv has no usable pip — rebuilding it from scratch."
        rm -rf "$VENV_DIR"
    fi

'''

P_CREATE_BLOCK_RE = re.compile(r'^(\s*)if \[\[ ! -d "\$VENV_DIR" \]\]; then\s*$', re.M)


@typechecked
def fix_venv_health_gate(ws: str) -> Optional[Edit]:
    rel = os.path.join("backend", "run.sh")
    sh = p_read(os.path.join(ws, rel))
    if sh is None or check_venv_health_gate(ws)[0] is True:
        return None
    if not (P_FAST_PATH_RE.search(sh) and P_CREATE_BLOCK_RE.search(sh)):
        return None
    new = sh
    if "venv_healthy" not in new:
        new = P_FAST_PATH_RE.sub(lambda m: P_VENV_HELPERS + m.group(0), new, count=1)
    new = P_FAST_PATH_RE.sub('if [[ -f "$SENTINEL" ]] && venv_healthy; then', new, count=1)
    new = P_CREATE_BLOCK_RE.sub(lambda m: P_SELF_HEAL + m.group(0), new, count=1)
    return Edit(
        rel_path=rel,
        old_text=sh,
        new_text=new,
        language=P_SH,
        note="Corroborate the install sentinel with a real pip probe, and rebuild a hollow venv instead of trusting it forever.",
    )


# ############################### run.sh: PYTHONPATH ###############################

P_PIP_INSTALL_RE = re.compile(r'^(\s*)"\$VENV_PY" -m pip install -e \.\s*$', re.M)
P_UVICORN_RE = re.compile(r'^(\s*)("\$VENV_PY" -m uvicorn .*)$', re.M)
P_SWARM_DEBUG_RE = re.compile(r'&& ("\$SWARM_DEBUG_BIN" toggle on --all)')


@typechecked
def fix_pythonpath_stripped(ws: str) -> Optional[Edit]:
    rel = os.path.join("backend", "run.sh")
    sh = p_read(os.path.join(ws, rel))
    if sh is None or check_pythonpath_stripped(ws)[0] is True:
        return None
    if not P_UVICORN_RE.search(sh):
        return None
    new = sh
    # `exec` on the final uvicorn line hands the pid straight to the runtime supervisor instead of
    # leaving a bash parent between them; the stock script omits it.
    new = P_UVICORN_RE.sub(
        lambda m: f'{m.group(1)}exec env -u PYTHONPATH {m.group(2)}', new, count=1
    )
    new = P_PIP_INSTALL_RE.sub(lambda m: f'{m.group(1)}env -u PYTHONPATH "$VENV_PY" -m pip install -e .', new, count=1)
    new = P_SWARM_DEBUG_RE.sub(r'&& env -u PYTHONPATH \1', new, count=1)
    if new == sh:
        return None
    return Edit(
        rel_path=rel,
        old_text=sh,
        new_text=new,
        language=P_SH,
        note="Strip the bundle's PYTHONPATH so pip installs into the venv and uvicorn imports from it.",
    )


# ############################### backend_init.sh: cache gate ###############################

P_CACHE_DECL_RE = re.compile(r'^CACHE_VENV="\$\{OPENSWARM_BACKEND_VENV_CACHE:-\}/\.venv"\s*$', re.M)
P_CACHE_IF_RE = re.compile(r'^if \[\[ -d "\$CACHE_VENV" \]\]; then\s*$', re.M)

P_CACHE_GATE = '''# The cache builder writes a `.populated` sentinel next to .venv only after pip-install succeeds.
# A crashed build still leaves the half-made .venv directory behind, so `-d` alone will happily
# copy in a venv with no pip and no site-packages. Require the sentinel, and require a real pip.
CACHE_ROOT="${OPENSWARM_BACKEND_VENV_CACHE:-}"
CACHE_VENV="$CACHE_ROOT/.venv"
cache_usable() {
    [[ -n "$CACHE_ROOT" ]] || return 1
    [[ -f "$CACHE_ROOT/.populated" ]] || return 1
    [[ -x "$CACHE_VENV/bin/python" || -x "$CACHE_VENV/Scripts/python.exe" ]] || return 1
    return 0
}

if [[ -d "$CACHE_VENV" ]] && ! cache_usable; then
    echo "Warm venv cache at $CACHE_VENV is incomplete (no .populated sentinel);" >&2
    echo "ignoring it. backend/run.sh will build the venv on first boot." >&2
fi
'''


@typechecked
def fix_cache_populated_gate(ws: str) -> Optional[Edit]:
    rel = "backend_init.sh"
    sh = p_read(os.path.join(ws, rel))
    if sh is None or check_cache_populated_gate(ws)[0] is True:
        return None
    if not (P_CACHE_DECL_RE.search(sh) and P_CACHE_IF_RE.search(sh)):
        return None
    new = P_CACHE_DECL_RE.sub(P_CACHE_GATE.rstrip("\n"), sh, count=1)
    new = P_CACHE_IF_RE.sub("if cache_usable; then", new, count=1)
    return Edit(
        rel_path=rel,
        old_text=sh,
        new_text=new,
        language=P_SH,
        note="Gate the warm cache on a completion marker so a failed build never gets copied forward.",
    )


# ############################### serve-mode marker ###############################

P_MARKER_BODY = """Serve mode decides freshness by comparing dist's mtime against the newest file under
frontend/. That check is frontend-only, so an app WITH a backend gets "restarted" into a static
bundle with nothing serving /api — and it deadlocks restart.sh, because the sentinel watcher skips
runtimes that aren't running and a process-less runtime never is.

This file's mtime is parked in 2038, so it is permanently newer than any dist build and the
freshness comparison can never come out true. The mtime is the mechanism, not the filename: git
does not preserve mtimes, so a fresh clone lands this file with a checkout-time mtime and the
workaround silently stops working. frontend/run.sh re-stamps it on every boot for that reason.
"""


@typechecked
def fix_serve_mode_marker(ws: str) -> Optional[Edit]:
    if check_serve_mode_marker(ws)[0] is True:
        return None
    if not os.path.isdir(os.path.join(ws, "frontend", "src")):
        return None
    existing = p_read(os.path.join(ws, P_MARKER_REL))
    return Edit(
        rel_path=P_MARKER_REL,
        old_text=existing or "",
        new_text=P_MARKER_BODY,
        language="text",
        note="Create the serve-mode marker and park its mtime in 2038 so a static bundle can never win.",
        set_mtime=P_MIN_MARKER_MTIME + 86400.0,
    )


P_FIXERS: Dict[str, Callable[[str], Optional[Edit]]] = {
    "httpx_declared": fix_httpx_declared,
    "ensurepip_guard": fix_ensurepip_guard,
    "venv_health_gate": fix_venv_health_gate,
    "pythonpath_stripped": fix_pythonpath_stripped,
    "cache_populated_gate": fix_cache_populated_gate,
    "serve_mode_marker": fix_serve_mode_marker,
}


@typechecked
def p_plan(ws: str, check_ids: List[str]) -> Dict[str, object]:
    """Compute every edit for the requested checks without touching disk.

    Two fixers both rewrite run.sh, so their edits are folded in sequence: each one re-reads from
    the running text rather than from the file, and the diff the user sees is the combined result.
    """
    edits: List[Edit] = []
    skipped: List[Dict[str, str]] = []
    # Fixers are applied in P_FIXERS order, not caller order, so a plan is deterministic.
    pending = [cid for cid in P_FIXERS if cid in check_ids]

    # Fold same-file edits by threading the running text through an overlay the fixers read from.
    overlay: Dict[str, str] = {}
    real_read = p_read

    for cid in pending:
        fixer = P_FIXERS[cid]
        edit = _with_overlay(overlay, ws, fixer)
        if edit is None:
            skipped.append({"id": cid, "reason": "already satisfied, or no anchor found in this file"})
            continue
        overlay[edit.rel_path] = edit.new_text
        edits.append(edit)

    del real_read
    # Collapse to one entry per file so the preview shows one diff per file, not one per fix.
    by_file: Dict[str, Edit] = {}
    for e in edits:
        if e.rel_path in by_file:
            prev = by_file[e.rel_path]
            by_file[e.rel_path] = prev._replace(
                new_text=e.new_text,
                note=f"{prev.note} {e.note}",
                set_mtime=e.set_mtime or prev.set_mtime,
            )
        else:
            by_file[e.rel_path] = e
    return {"edits": list(by_file.values()), "skipped": skipped}


@typechecked
def _with_overlay(overlay: Dict[str, str], ws: str, fixer: Callable[[str], Optional[Edit]]) -> Optional[Edit]:
    """Run a fixer with p_read serving already-computed text for files earlier fixers rewrote."""
    import backend.apps.drift.checks as checks_mod
    import backend.apps.drift.fixers as fixers_mod

    original = checks_mod.p_read

    def patched(path: str) -> Optional[str]:
        for rel, text in overlay.items():
            if os.path.abspath(path) == os.path.abspath(os.path.join(ws, rel)):
                return text
        return original(path)

    checks_mod.p_read = patched
    fixers_mod.p_read = patched
    try:
        return fixer(ws)
    finally:
        checks_mod.p_read = original
        fixers_mod.p_read = original
