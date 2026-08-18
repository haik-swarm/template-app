"""Unit checks for the two text helpers whose edge cases the round-trip harness cannot reach.

Run directly (`python -m backend.apps.drift.unit_check`). Standalone like roundtrip_check.py, so it
needs no pytest and no fixtures.

The harness proves the fixers round-trip against the workspaces that happen to exist today. These
two helpers are the ones whose failure modes are invisible there: a wrong answer from either shows
up as a *correct-looking* grade or a silently skipped edit, not as a diff. Both already shipped a
bug of exactly that shape, so the cases below are regressions, not hypotheticals.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))

from backend.apps.drift.checks import p_code_only  # noqa: E402
from backend.apps.drift.fixers import (  # noqa: E402
    P_UNSET_PP_STMTS,
    p_unset_pp_anchor,
)

FAILURES = []


def check(name, got, want):
    if got == want:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}\n          got:  {got!r}\n          want: {want!r}")
        FAILURES.append(name)


def test_code_only():
    print("p_code_only")

    # Dropped outright, not blanked in place. Line numbers are deliberately not preserved: every
    # consumer is a substring or regex search asking "does this script DO x", and none of them
    # reports a position back to the user.
    check("drops a whole-line comment",
          p_code_only("# a comment\ncode\n"), "code\n")

    check("drops an indented comment",
          p_code_only("    # indented\ncode\n"), "code\n")

    # The bug this helper was written for: after a to-Default conversion the venv_healthy helper and
    # every caller are gone, but a neighbouring comment still explains why it mattered. Grading the
    # raw text read that sentence and reported a stock file as Patched.
    leftover = '# the venv_healthy helper used to live here\nVENV_PY="$VENV_DIR/bin/python"\n'
    check("strips the leftover venv_healthy prose",
          "venv_healthy" in p_code_only(leftover), False)

    # Why this is line-based and not "cut from the first #". A `#` inside a quoted string is not a
    # comment, and cutting there would corrupt the exact shell being graded.
    quoted = 'echo "issue #42"\n'
    check("keeps a # inside a quoted string",
          p_code_only(quoted), quoted)

    check("keeps a trailing comment's code",
          p_code_only('code  # trailing\n'), 'code  # trailing\n')

    check("empty input", p_code_only(""), "")


def test_unset_pp_anchor():
    print("p_unset_pp_anchor")

    # Never fires while the statements are still present, in EITHER spelling. The one-line form is
    # the one that made 81654cd2 permanently mixed with both buttons dead.
    two_line = "#!/bin/bash\n# clear PYTHONPATH\nunset PYTHONPATH\nunset PYTHONHOME\n\ncode\n"
    check("no anchor when two-line form present",
          p_unset_pp_anchor(two_line), None)

    one_line = "#!/bin/bash\n# clear PYTHONPATH\nunset PYTHONPATH PYTHONHOME\n\ncode\n"
    check("no anchor when one-line form present",
          p_unset_pp_anchor(one_line), None)

    # The strip leg leaves the workspace's own comment behind as the breadcrumb. That orphaned
    # prose is the only surviving record that this workspace ever used the whole-script form.
    stripped = "#!/bin/bash\n# clear PYTHONPATH\n\ncode\n"
    anchor = p_unset_pp_anchor(stripped)
    check("finds the orphaned comment", anchor is not None, True)
    if anchor is not None:
        restored = stripped[:anchor] + P_UNSET_PP_STMTS + stripped[anchor:]
        check("restore reinstates the statements",
              restored, "#!/bin/bash\n# clear PYTHONPATH\nunset PYTHONPATH\nunset PYTHONHOME\n\ncode\n")
        check("restored text no longer anchors (idempotent)",
              p_unset_pp_anchor(restored), None)

    # Requiring the prose to actually name PYTHONPATH is what stops this firing on the Windows-layout
    # comment that follows it in every one of these scripts.
    unrelated = "#!/bin/bash\n# on Windows the venv layout differs\n\ncode\n"
    check("ignores a comment that never names PYTHONPATH",
          p_unset_pp_anchor(unrelated), None)

    check("no comment at all", p_unset_pp_anchor("#!/bin/bash\ncode\n"), None)


def main():
    test_code_only()
    test_unset_pp_anchor()
    print()
    if FAILURES:
        print(f"UNIT CHECK FAILED: {len(FAILURES)} case(s): {', '.join(FAILURES)}")
        return 1
    print("UNIT CHECK CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
