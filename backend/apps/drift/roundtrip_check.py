"""Round-trip harness: a workspace taken to the other variant and back must be byte-identical.

Run directly (`python -m backend.apps.drift.roundtrip_check <workspace>`) against any workspace.
Not a pytest file and not imported by the app; it exists so the fixers and reverters can be proven
against a real tree rather than believed.

The property under test is SYMMETRY, not convergence on some privileged original. There is no
hardened-versus-stock axis here: there are two variants a workspace can be in, either is a fine
place to be, and anything matching neither is what the tool has no opinion about. So the assertion
is that going there and coming back is the identity function, in whichever direction this workspace
happens to start from. The earlier version asserted "revert reproduces the baseline", which is
unsatisfiable for a workspace already sitting in the variant revert targets, and which quietly
encoded the wrong idea that one of the two was the real one.
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

from backend.apps.drift.checks import p_grade_workspace  # noqa: E402
from backend.apps.drift.fixers import P_SHARED_CHECKS, p_plan  # noqa: E402

FILES = ["backend/run.sh", "backend_init.sh", "backend/pyproject.toml", "frontend/src/.no-serve-mode"]


def snapshot(ws):
    out = {}
    for rel in FILES:
        p = os.path.join(ws, rel)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                out[rel] = f.read()
    return out


def apply(ws, direction):
    """Plan and write every check currently on the wrong side of `direction`."""
    graded = p_grade_workspace(ws)
    want = "fail" if direction == "harden" else "pass"
    targets = [c["id"] for c in graded["checks"] if c["state"] == want]
    plan = p_plan(ws, targets, direction)
    for e in plan["edits"]:
        dest = os.path.join(ws, e.rel_path)
        if e.delete:
            if os.path.exists(dest):
                os.unlink(dest)
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(e.new_text)
        # Load-bearing, not cosmetic: serve_mode_marker is satisfied by the marker's mtime being in
        # the future, so a harness that writes the bytes and drops the mtime fails a check the real
        # apply would have passed, and blames the fixer for its own omission.
        if e.set_mtime is not None:
            os.utime(dest, (e.set_mtime, e.set_mtime))
    return plan


def main(src):
    tmp = tempfile.mkdtemp(prefix="drift-roundtrip-")
    ws = os.path.join(tmp, "ws")
    shutil.copytree(src, ws, symlinks=True,
                    ignore=shutil.ignore_patterns(".venv", "node_modules", ".git", "__pycache__", "dist"))

    before = snapshot(ws)
    g0 = p_grade_workspace(ws)
    print(f"baseline: {g0['passed']}/{g0['applicable']} passing")

    # Move AWAY from wherever this workspace already is, then come back: two legs, not three. A
    # third leg lands in the OTHER variant and every file legitimately differs, which reads as a
    # round-trip failure when the round trip never actually closed. Starting with the direction the
    # workspace is already in would instead make leg one a no-op and pass without testing anything.
    first = "revert" if g0["passed"] == g0["applicable"] else "harden"
    seq = [first, "harden" if first == "revert" else "revert"]

    ok = True
    for i, direction in enumerate(seq, 1):
        p = apply(ws, direction)
        g = p_grade_workspace(ws)
        print(f"  {i}. {direction:6} -> {g['passed']}/{g['applicable']} passing  "
              f"({len(p['edits'])} file(s) written)")
        for s in p["skipped"]:
            print(f"          skipped {s['id']}: {s['reason']}")
        # A leg that lands between the two variants is a half-applied swap: some fixer moved its
        # code but its partner found no anchor. It round-trips back to clean only by luck, and the
        # workspace is in a state neither variant's author ever wrote.
        #
        # The floor is the shared checks, not zero. Both variants satisfy those by definition, so a
        # fully-reverted tree still passes exactly them; comparing against 0 called every clean
        # revert half-applied and flagged the one state it was meant to certify.
        gradable = {c["id"] for c in g["checks"] if c["state"] in ("pass", "fail")}
        want = (gradable & P_SHARED_CHECKS) if direction == "revert" else gradable
        got = {c["id"] for c in g["checks"] if c["state"] == "pass"}
        if got != want:
            print(f"          WARNING: neither variant cleanly; "
                  f"unexpected fail: {', '.join(sorted(want - got)) or '-'}; "
                  f"unexpected pass: {', '.join(sorted(got - want)) or '-'}")
            ok = False

    end = p_grade_workspace(ws)
    if end["passed"] != g0["passed"]:
        print(f"          REGRESSION: started at {g0['passed']}/{g0['applicable']}, "
              f"ended at {end['passed']}/{end['applicable']}")
        ok = False

    after = snapshot(ws)
    for rel in sorted(set(before) | set(after)):
        a, b = before.get(rel), after.get(rel)
        if a == b:
            continue
        ok = False
        if a is None:
            print(f"\nMISMATCH {rel}: file did not exist at start, exists after round-trip")
        elif b is None:
            print(f"\nMISMATCH {rel}: existed at start, missing after round-trip")
        else:
            import difflib
            print(f"\nMISMATCH {rel}:")
            for line in list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                                  "start", "round-tripped", lineterm=""))[:40]:
                print("   " + line)

    print()
    if ok:
        print(f"ROUND TRIP CLEAN: {' -> '.join(seq)} reproduced the starting tree byte-for-byte.")
        return 0
    print("ROUND TRIP FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
