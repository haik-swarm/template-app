"""Round-trip harness: a workspace taken to the other variant and back must be byte-identical.

Run directly (`python -m backend.apps.drift.roundtrip_check <workspace>`) against any workspace.
Not a pytest file and not imported by the app; it exists so the fixers and reverters can be proven
against a real tree rather than believed.

The property under test is SYMMETRY, not convergence on some privileged original. There is no
hardened-versus-stock axis here: there are two variants a workspace can be in, either is a fine
place to be, and anything matching neither is what the tool has no opinion about. So the assertion
is that going there and coming back is the identity function, in whichever target this workspace
happens to start from. The earlier version asserted "revert reproduces the baseline", which is
unsatisfiable for a workspace already sitting in the variant revert targets, and which quietly
encoded the wrong idea that one of the two was the real one.
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

from backend.apps.drift.checks import P_NA, P_SHARED, p_grade_workspace  # noqa: E402
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


def apply(ws, target):
    """Plan and write every check currently on the wrong side of `target`. Returns the plan."""
    graded = p_grade_workspace(ws)
    # Must be the same rule the /fix endpoint uses, keyed on `side`, or the harness certifies a
    # selection no user can actually request. P_SHARED joins P_NA as un-convertible: both variants
    # already agree there, so there is no other side to move it to.
    targets = [
        c["id"] for c in graded["checks"]
        if c["side"] not in (P_NA, P_SHARED, target)
    ]
    plan = p_plan(ws, targets, target)
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
    # round-trip failure when the round trip never actually closed. Starting with the target the
    # workspace is already in would instead make leg one a no-op and pass without testing anything.
    first = "default" if g0["passed"] == g0["applicable"] else "patched"
    seq = [first, "patched" if first == "default" else "default"]

    ok = True
    for i, target in enumerate(seq, 1):
        p = apply(ws, target)
        g = p_grade_workspace(ws)
        print(f"  {i}. {target:6} -> {g['passed']}/{g['applicable']} passing  "
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
        want = (gradable & P_SHARED_CHECKS) if target == "default" else gradable
        got = {c["id"] for c in g["checks"] if c["state"] == "pass"}
        # A check the planner reported as skipped is one whose fixer found no anchor, which for a
        # workspace written in its own dialect is the CORRECT outcome: to_default_ensurepip_guard
        # only un-writes the helper this tool wrote, so a workspace that fused `import ensurepip`
        # into its version probe, or spelled the health gate as an inline `-m pip --version`, is
        # deliberately left alone and keeps passing. Counting that as "landed between variants"
        # blamed the tool for honouring its own don't-touch-what-we-didn't-write rule, and it is
        # what kept 00da51a5 failing even once every file round-tripped byte-identically.
        skipped_ids = {s["id"] for s in p["skipped"]}
        unexpected_pass = got - want - skipped_ids
        unexpected_fail = want - got
        if unexpected_pass or unexpected_fail:
            print(f"          WARNING: neither variant cleanly; "
                  f"unexpected fail: {', '.join(sorted(unexpected_fail)) or '-'}; "
                  f"unexpected pass: {', '.join(sorted(unexpected_pass)) or '-'}")
            ok = False
        elif got - want:
            print(f"          note: {', '.join(sorted(got - want))} kept its own spelling "
                  f"(no anchor to convert), left untouched")

    end = p_grade_workspace(ws)
    if end["passed"] != g0["passed"]:
        print(f"          REGRESSION: started at {g0['passed']}/{g0['applicable']}, "
              f"ended at {end['passed']}/{end['applicable']}")
        ok = False

    after = snapshot(ws)

    # A second identical round trip. Under normalization the property under test is not "trip one
    # reproduced the input" — a workspace written in a hand-rolled dialect is deliberately rewritten
    # into canonical spelling, so trip one legitimately differs and asserting byte-identity there
    # flags the tool working as designed. What must hold is that the rewrite SETTLES: once a tree is
    # canonical, converting it again changes nothing further. Comparing trip one against trip two
    # tests exactly that, and it is the assertion that distinguishes stable normalization from
    # unbounded drift, which is the failure mode that would actually matter.
    for target in seq:
        apply(ws, target)
    twice = snapshot(ws)

    normalized = []
    for rel in sorted(set(before) | set(after)):
        a, b = before.get(rel), after.get(rel)
        if a == b:
            continue
        if a is None:
            ok = False
            print(f"\nMISMATCH {rel}: file did not exist at start, exists after round-trip")
        elif b is None:
            ok = False
            print(f"\nMISMATCH {rel}: existed at start, missing after round-trip")
        else:
            normalized.append(rel)

    # Drift is trip two disagreeing with trip one: the tool never reached a fixed point.
    for rel in sorted(set(after) | set(twice)):
        if after.get(rel) != twice.get(rel):
            ok = False
            import difflib
            a, b = after.get(rel) or "", twice.get(rel) or ""
            print(f"\nUNSTABLE {rel}: a second round trip changed the file again")
            for line in list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                                  "trip-1", "trip-2", lineterm=""))[:40]:
                print("   " + line)

    if normalized and ok:
        import difflib
        print(f"\nNORMALIZED (stable): {', '.join(normalized)}")
        for rel in normalized:
            diff = list(difflib.unified_diff(before[rel].splitlines(), after[rel].splitlines(),
                                             "start", "canonical", lineterm=""))
            print(f"  {rel}: {sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))} "
                  f"line(s) rewritten to canonical spelling")

    print()
    if ok:
        how = "unchanged" if not normalized else "normalized to canonical spelling, stable on re-run"
        print(f"ROUND TRIP CLEAN: {' -> '.join(seq)} left the tree {how}.")
        return 0
    print("ROUND TRIP FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
