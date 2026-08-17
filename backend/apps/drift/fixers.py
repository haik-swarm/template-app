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
    delete: bool = False   # unlink instead of writing new_text (see revert_serve_mode_marker)


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

P_PY_USABLE_HELPER = '''# A candidate is only usable if it can actually BUILD a venv, which means
# importing ensurepip. The bundled interpreter ships without ensurepip, so
# `python3 -m venv` leaves a hollow venv with no pip and the install below
# dies on "No module named pip". Version-checking alone accepts it.
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

# Anchors the note branch to the `else` that opens the PATH-probing fallback. Once py_usable()
# can reject OPENSWARM_PYTHON, falling through here stops meaning "unset" and starts also meaning
# "set but unusable" — silently ignoring an interpreter the caller explicitly chose. The reverter
# already dropped this block; nothing wrote it, so a hardened file never matched the real variant.
P_OSPY_ELSE_RE = re.compile(r'^(\s*)PYTHON="\$\{OPENSWARM_PYTHON\}"\n(\s*)else\n', re.M)


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
    new = P_OSPY_ELSE_RE.sub(
        lambda m: f'{m.group(1)}PYTHON="${{OPENSWARM_PYTHON}}"\n{m.group(2)}else\n' + P_OSPY_NOTE_BLOCK,
        new, count=1,
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

# These two helpers are inserted together by the health-gate fixer but removed independently by
# two different reverters, so each is defined once, here, and the combined block is composed from
# them. Keeping a separate hand-written copy of the pair is what broke the round trip before: the
# fixer wrote one wording, revert_pythonpath_stripped's guard searched for another, the guard's
# .replace() no-opped, and venv_py() was stranded in the reverted file while the reverter reported
# success. Concatenation makes "what we write" and "what we look for" the same bytes by
# construction, which no amount of keeping two literals in sync can guarantee.
P_VENV_PY_HELPER = '''# OpenSwarm exports a PYTHONPATH pointing at the app bundle's own
# site-packages. That leaks bundle copies of fastapi/typeguard/etc into this
# venv and shadows what's actually installed here, so pip "succeeds" while
# silently no-opping deps. Everything below runs the venv python clean.
venv_py() { env -u PYTHONPATH "$VENV_PY" "$@"; }

'''

P_VENV_HEALTHY_HELPER = '''# A venv is only trustworthy if its interpreter exists AND has pip. A venv
# built by an ensurepip-less interpreter satisfies `-d $VENV_DIR` but can
# never install anything, so the directory check alone is not enough.
venv_healthy() {
    [[ -x "$VENV_PY" ]] || return 1
    venv_py -m pip --version &>/dev/null || return 1
    return 0
}

'''

# Each helper owns the blank line that follows it, so removing both reclaims every line the fixer
# added. A separator appended here instead would belong to neither block and survive the revert as
# a stray blank line — cosmetic, but enough to fail a byte-for-byte round trip.
P_VENV_HELPERS = P_VENV_PY_HELPER + P_VENV_HEALTHY_HELPER

P_FAST_PATH_RE = re.compile(r'^if \[\[ -d "\$VENV_DIR" && -f "\$SENTINEL" \]\]; then\s*$', re.M)

P_SELF_HEAL = '''    # Drop a venv that exists but is unusable (e.g. copied in from a warm
    # cache that was built without pip); otherwise the install below fails
    # on every boot with no way to self-heal.
    if [[ -d "$VENV_DIR" ]] && ! venv_healthy; then
        echo "Existing .venv has no usable pip — rebuilding it from scratch."
        rm -rf "$VENV_DIR"
    fi

'''

P_CREATE_BLOCK_RE = re.compile(r'^(\s*)if \[\[ ! -d "\$VENV_DIR" \]\]; then\s*$', re.M)

# The `fi` closing the create block, pinned by the install comment that follows it so it cannot
# match the inner `fi` of the venv-create failure branch.
P_CREATE_CLOSE_RE = re.compile(
    r'^(    fi\n\n)(?=    # --- Install Python dependencies ---)', re.M
)


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
    # The reverter undoes both of these, but nothing here ever applied them, so a hardened file
    # never matched the real variant and the harden->revert->harden cycle could not close. A venv
    # that fails to build must be removed rather than left half-made for the next boot to trust,
    # and a venv that builds without pip has to fail loudly here instead of at the pip install.
    new = new.replace(P_STOCK_CREATE, P_HARDENED_CREATE, 1)
    new = P_CREATE_CLOSE_RE.sub(lambda m: m.group(0) + P_NO_PIP_GUARD, new, count=1)
    return Edit(
        rel_path=rel,
        old_text=sh,
        new_text=new,
        language=P_SH,
        note="Corroborate the install sentinel with a real pip probe, and rebuild a hollow venv instead of trusting it forever.",
    )


# ############################### run.sh: PYTHONPATH ###############################

P_PIP_INSTALL_RE = re.compile(r'^(\s*)"\$VENV_PY" -m pip install -e \.\s*$', re.M)

# The stock pip call plus the `$?` test that follows it, as one unit — the exact inverse of
# P_HARDENED_PIP_HELPER_RE on the revert side.
P_STOCK_PIP_BLOCK_RE = re.compile(
    r'^(\s*)"\$VENV_PY" -m pip install -e \.\n'
    r'\s*if \[\[ \$\? -ne 0 \]\]; then\n'
    r'(\s*echo "Error: Failed to install Python dependencies\."\n)'
    r'(\s*exit 1\n)'
    r'(\s*fi)$',
    re.M,
)
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
    # Prefer routing pip through venv_py() when the health-gate fix has already defined it, and
    # collapse the trailing `$?` test into the `if !` form at the same time. Inverse of the
    # reverter's multi-line swap: doing only half of it leaves a file that is neither variant.
    if "venv_py()" in new:
        new = P_STOCK_PIP_BLOCK_RE.sub(
            lambda m: f'{m.group(1)}if ! venv_py -m pip install -e .; then\n'
                      f'{m.group(2)}{m.group(3)}{m.group(4)}',
            new, count=1,
        )
    else:
        new = P_PIP_INSTALL_RE.sub(
            lambda m: f'{m.group(1)}env -u PYTHONPATH "$VENV_PY" -m pip install -e .', new, count=1
        )
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

# Byte-for-byte the marker this repo already ships, because the fixer's output IS that file and a
# second hand-written wording is just drift waiting to happen: it round-trips to a body the app's
# author never wrote, and the diff the user approves stops matching the file on disk.
P_MARKER_BODY = """Keeps this app on a real dev-server runtime instead of OpenSwarm's static
serve-mode. Not imported by anything; only its mtime matters.

Serve-mode (runtime.py:250) skips spawning any process when static_fresh()
says frontend/dist is newer than every file under frontend/. That check is
frontend-only, so an app with a FastAPI backend gets "restarted" into a
bundle with no backend behind it. It also breaks restart.sh: the sentinel
watcher ignores runtimes where `running` is False (runtime.py:653), and a
process-less runtime is never running, so restart requests are never
consumed and the script times out after 30s.

This file is dated far in the future, so dist can never be newer than it
and static_fresh() is always False. Deleting it re-enables serve-mode and
brings both problems back.
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


# ############################### reverters: hardened -> stock ###############################
#
# The mirror image of the fixers above, and they exist because "is this workspace hardened?" is a
# question you can only really answer by seeing the same app both ways. Terminal boots fine on the
# stock scripts; the template's are strictly better but different, and a one-way tool cannot show
# you the difference or undo a push you regret.
#
# Every reverter obeys the same two rules as its fixer, for the same reasons. Idempotent: returns
# None when the check already reads as stock. Anchored: it un-inserts the exact helper text the
# fixer inserted, so a workspace someone hand-fixed in a different style matches no anchor, returns
# None, and is reported as skipped rather than being rewritten into a shape its author never chose.
#
# These are deliberately NOT "restore the .drift-backup snapshot". A snapshot only exists for apps
# this tool already fixed, which would make revert unavailable on exactly the workspace that
# motivated it. Computing the inverse means direction is a property of the patch, not of history.


@typechecked
def p_words(text: str) -> set:
    """The distinct words of some comment prose, lowercased and stripped of punctuation."""
    return {w for w in re.findall(r"[A-Za-z_]{3,}", text.lower())}


@typechecked
def p_drop(text: str, block: str) -> Optional[str]:
    """Remove one occurrence of `block`, tolerating a rewrapped comment header. None if absent.

    The code lines are matched byte-for-byte, because that is what makes a revert honest: if the
    statements we inserted are not there exactly, this workspace's fix is not the one we wrote and
    the caller must return None rather than approximate.

    The COMMENT lines above them are matched by content instead. Every one of these blocks is stored
    here wrapped at ~100 chars but lands on disk wrapped at ~72, so a literal match found nothing and
    three reverters silently no-opped while reporting success. Comments get reflowed by formatters
    and by hand; the statements do not. So: locate the code exactly, then walk backwards over
    contiguous `#` lines and remove only those whose words are already accounted for by the block's
    own comment. A neighbouring comment nobody here wrote shares few words, fails that test, and
    survives — which is what keeps this from eating the shared preamble above the cache gate.
    """
    lines = block.split("\n")
    split = 0
    while split < len(lines) and (lines[split].lstrip().startswith("#") or not lines[split].strip()):
        split += 1
    comment_words = p_words("\n".join(lines[:split]))
    code = "\n".join(lines[split:])
    if not code.strip():
        return None
    if code not in text:
        return None

    # A block that already ends in a blank line carries its own separator, so the blank above it
    # belongs to whatever precedes it and must survive. Absorbing both removed two blank lines for
    # one inserted, which is the stray-blank-line drift that kept the round trip one byte off.
    owns_trailing_blank = block.endswith("\n\n")

    start = text.index(code)
    head = text[:start]
    head_lines = head.split("\n")
    # head_lines[-1] is the (possibly blank) indent before the code; walk back from the line above.
    cut = len(head_lines) - 1
    while cut > 0:
        candidate = head_lines[cut - 1]
        stripped = candidate.strip()
        if not stripped:
            # A blank line separating two comment blocks ends the run; one directly above the code
            # is part of our own block's trailing newline and can be absorbed.
            if cut == len(head_lines) - 1 and not owns_trailing_blank:
                cut -= 1
                continue
            break
        if not stripped.startswith("#"):
            break
        if not p_words(stripped) <= comment_words:
            break
        cut -= 1

    return "\n".join(head_lines[:cut]) + ("\n" if cut else "") + text[start + len(code):]


# ############################### httpx: shared, not swappable ###############################
#
# There is deliberately no httpx reverter. Both variants declare it explicitly — Terminal lists it
# in [project].dependencies just as the template does — so "the Terminal version of this check" and
# "the template version" are the same file content, and a swap between them is a no-op.
#
# An earlier draft reverted this to stock (undeclared) on the theory that revert always means
# "back to the original". The round-trip harness caught it immediately: reverting Terminal stripped
# an httpx line Terminal's author wrote on purpose and left the workspace one check WORSE than it
# started. Stock is not the other side of this swap; Terminal is, and Terminal already agrees.
#
# cache_populated_gate is here for the same reason, found the same way. check_cache_populated_gate
# asks one question — is the warm cache gated on a completion marker rather than a bare `-d` test —
# and both variants answer yes: Terminal with an inline `.populated` test, the template with
# cache_usable(). Neither is the fail state, so "the other side of the swap" does not exist and a
# reverter can only rewrite working code into differently-working code. Reverting one into the
# other also silently dropped the template's extra `-x .../bin/python` probe, a real behavioural
# change this check never asked for and does not measure.
P_SHARED_CHECKS = {"httpx_declared", "cache_populated_gate"}


# ############################### run.sh: ensurepip ###############################

P_OSPY_STOCK = (
    'if [[ -n "${OPENSWARM_PYTHON:-}" ]] && "${OPENSWARM_PYTHON}" '
    '-c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" &>/dev/null; then'
)
P_CAND_STOCK = (
    'if command -v "$candidate" &>/dev/null && "$candidate" '
    '-c "import sys; sys.exit(0 if sys.version_info[0]==3 else 1)" &>/dev/null; then'
)

P_OSPY_NOTE_BLOCK = '''    if [[ -n "${OPENSWARM_PYTHON:-}" ]]; then
        echo "Note: OPENSWARM_PYTHON cannot create a venv (no ensurepip); probing PATH instead."
    fi
'''

P_ENSUREPIP_ERROR = (
    'echo "Error: No Python 3 capable of creating a virtual environment was found."\n'
    '    echo "       (candidates must provide \'ensurepip\'; the bundled interpreter does not)"'
)


@typechecked
def revert_ensurepip_guard(ws: str) -> Optional[Edit]:
    rel = os.path.join("backend", "run.sh")
    sh = p_read(os.path.join(ws, rel))
    if sh is None or check_ensurepip_guard(ws)[0] is not True:
        return None
    # Only the helper we wrote can be un-written. `uv venv` also passes the check and is somebody
    # else's (arguably better) answer; rewriting it into a stock probe would be a downgrade nobody
    # asked for, so it matches no anchor and is skipped.
    if 'if py_usable "${OPENSWARM_PYTHON:-}"; then' not in sh:
        return None
    new = p_drop(sh, P_PY_USABLE_HELPER)
    if new is None:
        return None
    new = new.replace('if py_usable "${OPENSWARM_PYTHON:-}"; then', P_OSPY_STOCK, 1)
    new = new.replace(
        'if command -v "$candidate" &>/dev/null && py_usable "$candidate"; then', P_CAND_STOCK, 1
    )
    dropped = p_drop(new, P_OSPY_NOTE_BLOCK)
    if dropped is not None:
        new = dropped
    new = new.replace(P_ENSUREPIP_ERROR, 'echo "Error: No working Python 3 found."', 1)
    return Edit(
        rel_path=rel,
        old_text=sh,
        new_text=new,
        language=P_SH,
        note="Accept any python3 again, without probing whether it can actually build a venv.",
    )


# ############################### run.sh: venv health gate ###############################

P_STOCK_FAST_PATH = 'if [[ -d "$VENV_DIR" && -f "$SENTINEL" ]]; then'

P_HARDENED_CREATE = '''        if ! "$PYTHON" -m venv "$VENV_DIR"; then
            echo "Error: Failed to create virtual environment."
            rm -rf "$VENV_DIR"
            exit 1
        fi'''

P_STOCK_CREATE = '''        "$PYTHON" -m venv "$VENV_DIR"
        if [[ $? -ne 0 ]]; then
            echo "Error: Failed to create virtual environment."
            exit 1
        fi'''

P_NO_PIP_GUARD = '''    if ! venv_healthy; then
        echo "Error: virtual environment was created without pip."
        exit 1
    fi

'''

# P_VENV_HELPERS is two helpers with a comment between them, so p_drop cannot take it whole: it
# matches code byte-for-byte and stops at that interior comment. The two are defined separately at
# the fixer above and concatenated, so each can be dropped on its own here. They also belong to
# different checks — venv_py() is the PYTHONPATH fix, venv_healthy() the sentinel fix — which is
# what lets either be reverted without the other.


@typechecked
def revert_venv_health_gate(ws: str) -> Optional[Edit]:
    rel = os.path.join("backend", "run.sh")
    sh = p_read(os.path.join(ws, rel))
    if sh is None or check_venv_health_gate(ws)[0] is not True:
        return None
    if 'if [[ -f "$SENTINEL" ]] && venv_healthy; then' not in sh:
        return None
    new = sh.replace('if [[ -f "$SENTINEL" ]] && venv_healthy; then', P_STOCK_FAST_PATH, 1)
    dropped = p_drop(new, P_SELF_HEAL)
    if dropped is None:
        return None
    new = dropped
    dropped = p_drop(new, P_NO_PIP_GUARD)
    if dropped is not None:
        new = dropped
    new = new.replace(P_HARDENED_CREATE, P_STOCK_CREATE, 1)
    # Drop venv_healthy() itself, now that its last caller is gone. venv_py() is NOT dropped here:
    # it belongs to the PYTHONPATH fix and may still have callers. When both checks are reverted
    # together p_plan threads this text into the next reverter, which removes it then.
    dropped = p_drop(new, P_VENV_HEALTHY_HELPER)
    if dropped is not None:
        new = dropped
    if new == sh:
        return None
    return Edit(
        rel_path=rel,
        old_text=sh,
        new_text=new,
        language=P_SH,
        note="Trust the install sentinel on its own again, with no pip probe and no self-heal.",
    )


# ############################### run.sh: PYTHONPATH ###############################

P_HARDENED_UVICORN_RE = re.compile(r'^(\s*)exec env -u PYTHONPATH ("\$VENV_PY" -m uvicorn .*)$', re.M)
P_HARDENED_PIP_RE = re.compile(r'^(\s*)env -u PYTHONPATH "\$VENV_PY" -m pip install -e \.\s*$', re.M)
# Variant A routes pip through the helper AND checks it inline with `if ! ...; then`; variant B runs
# the command bare and tests `$?` on the next line. So this is not a command swap with the error
# handling left alone — the two variants spell the same check with a different number of lines, and
# the whole construct has to move together or `venv_py` keeps a caller and can never be dropped.
P_HARDENED_PIP_HELPER_RE = re.compile(
    r'^(\s*)if ! venv_py -m pip install -e \.; then\n'
    r'(\s*echo "Error: Failed to install Python dependencies\."\n)'
    r'(\s*exit 1\n)'
    r'(\s*fi)$',
    re.M,
)
P_HARDENED_DEBUG_RE = re.compile(r'&& env -u PYTHONPATH ("\$SWARM_DEBUG_BIN" toggle on --all)')

@typechecked
def revert_pythonpath_stripped(ws: str) -> Optional[Edit]:
    rel = os.path.join("backend", "run.sh")
    sh = p_read(os.path.join(ws, rel))
    if sh is None or check_pythonpath_stripped(ws)[0] is not True:
        return None
    if not P_HARDENED_UVICORN_RE.search(sh):
        return None
    new = P_HARDENED_UVICORN_RE.sub(lambda m: f'{m.group(1)}{m.group(2)}', sh, count=1)
    new = P_HARDENED_PIP_RE.sub(lambda m: f'{m.group(1)}"$VENV_PY" -m pip install -e .', new, count=1)
    new = P_HARDENED_PIP_HELPER_RE.sub(
        lambda m: f'{m.group(1)}"$VENV_PY" -m pip install -e .\n'
                  f'{m.group(1)}if [[ $? -ne 0 ]]; then\n'
                  f'{m.group(2)}{m.group(3)}{m.group(4)}',
        new, count=1,
    )
    new = P_HARDENED_DEBUG_RE.sub(r'&& \1', new, count=1)
    # venv_py() exists only to route calls through `env -u PYTHONPATH`; with the call sites back to
    # stock it is dead code. Drop it only once nothing else calls it — venv_healthy() also uses it,
    # and survives when that check is not part of this same revert. Ask that question of the text
    # itself rather than by subtracting a literal copy of the definition: a stale literal silently
    # matches nothing, reports "no callers left", and stranded venv_py() in the reverted file.
    dropped = p_drop(new, P_VENV_PY_HELPER)
    if dropped is not None and "venv_py" not in dropped:
        new = dropped
    if new == sh:
        return None
    return Edit(
        rel_path=rel,
        old_text=sh,
        new_text=new,
        language=P_SH,
        note="Let pip and uvicorn inherit the bundle's PYTHONPATH again, as the stock script does.",
    )


# ############################### serve-mode marker ###############################


@typechecked
def revert_serve_mode_marker(ws: str) -> Optional[Edit]:
    """Re-enable serve-mode by deleting the marker.

    The only reverter whose edit is a deletion, which is why Edit carries `delete`: writing the
    file empty would leave a zero-byte file with a 2038 mtime, and the mtime IS the mechanism, so
    an "empty" marker suppresses serve-mode exactly as well as a full one. It has to be unlinked.
    """
    if check_serve_mode_marker(ws)[0] is not True:
        return None
    existing = p_read(os.path.join(ws, P_MARKER_REL))
    if existing is None:
        return None
    return Edit(
        rel_path=P_MARKER_REL,
        old_text=existing,
        new_text="",
        language="text",
        note="Delete the serve-mode marker, re-enabling OpenSwarm's static serve-mode for this app.",
        delete=True,
    )


# No entry for the ids in P_SHARED_CHECKS: see the comment there. A check with a fixer but no
# reverter is one-way by design, and p_plan reports it as shared rather than silently doing nothing.
P_REVERTERS: Dict[str, Callable[[str], Optional[Edit]]] = {
    "ensurepip_guard": revert_ensurepip_guard,
    "venv_health_gate": revert_venv_health_gate,
    "pythonpath_stripped": revert_pythonpath_stripped,
    "serve_mode_marker": revert_serve_mode_marker,
}


@typechecked
def p_plan(ws: str, check_ids: List[str], direction: str = "harden") -> Dict[str, object]:
    """Compute every edit for the requested checks without touching disk.

    Three fixers rewrite run.sh, so their edits are folded in sequence: each one re-reads from the
    running text rather than from the file, and the diff the user sees is the combined result.

    `direction` selects the table. Both directions share this function deliberately: the fold, the
    determinism and the one-diff-per-file collapse are properties of planning, not of which way you
    are going, and duplicating them is how the two paths would drift apart.
    """
    table = P_FIXERS if direction == "harden" else P_REVERTERS
    edits: List[Edit] = []
    skipped: List[Dict[str, str]] = []
    # A check both variants implement identically has a fixer but no reverter. Saying so beats
    # dropping it from `pending` silently, which reads as "the tool forgot about this one".
    shared = {cid for cid in check_ids if cid in P_SHARED_CHECKS} if direction == "revert" else set()
    for cid in check_ids:
        if cid in shared:
            skipped.append({
                "id": cid,
                "reason": "both variants implement this the same way, so there is nothing to swap",
            })
    # Applied in table order, not caller order, so a plan is deterministic. Reverting walks the
    # same order; each reverter re-reads the running text, so the shared run.sh helpers are dropped
    # by whichever one is last to need them.
    pending = [cid for cid in table if cid in check_ids and cid not in shared]

    # Fold same-file edits by threading the running text through an overlay the fixers read from.
    overlay: Dict[str, str] = {}
    real_read = p_read

    verb = "satisfied" if direction == "harden" else "already stock"
    for cid in pending:
        edit = _with_overlay(overlay, ws, table[cid])
        if edit is None:
            skipped.append({"id": cid, "reason": f"{verb}, or no anchor found in this file"})
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
                delete=e.delete or prev.delete,
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
