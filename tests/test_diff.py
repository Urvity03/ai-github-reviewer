"""Tests for unified diff parser and hunk analysis."""

from ai_reviewer.diff import (
    is_line_in_diff,
    parse_patch_to_hunks,
    parse_unified_diff,
    snap_finding_line,
)
from ai_reviewer.models.review import ChangedFile

SAMPLE_DIFF = """diff --git a/src/calc.py b/src/calc.py
index 83a45b1..91f13b2 100644
--- a/src/calc.py
+++ b/src/calc.py
@@ -10,6 +10,8 @@ def divide(a, b):
     if b == 0:
         raise ValueError("Zero division")
     return a / b
+
+def multiply(a, b):
+    return a * b
diff --git a/docs/old.txt b/docs/old.txt
deleted file mode 100644
--- a/docs/old.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-line1
-line2
diff --git a/legacy.py b/modern.py
similarity index 100%
rename from legacy.py
rename to modern.py
diff --git a/assets/logo.png b/assets/logo.png
index e69de29..4b825dc 100644
Binary files a/assets/logo.png and b/assets/logo.png differ
"""


def test_parse_unified_diff_multiple_files():
    files = parse_unified_diff(SAMPLE_DIFF)
    assert len(files) == 4

    # 1. Modified file
    calc_file = files[0]
    assert calc_file.filename == "src/calc.py"
    assert calc_file.status == "modified"
    assert calc_file.additions == 3
    assert len(calc_file.hunks) == 1
    hunk = calc_file.hunks[0]
    assert hunk.new_start == 10
    # Added lines in new file: lines 13, 14, 15
    assert 13 in hunk.added_new_lines
    assert 14 in hunk.added_new_lines
    assert 15 in hunk.added_new_lines
    # Context lines: lines 10..12
    assert 11 in hunk.valid_new_lines
    assert is_line_in_diff(calc_file, 14) is True
    assert is_line_in_diff(calc_file, 14, require_modified=True) is True
    assert is_line_in_diff(calc_file, 11, require_modified=True) is False
    assert is_line_in_diff(calc_file, 999) is False

    # 2. Deleted file
    del_file = files[1]
    assert del_file.filename == "docs/old.txt"
    assert del_file.status == "deleted"
    assert del_file.deletions == 2

    # 3. Renamed file
    ren_file = files[2]
    assert ren_file.filename == "modern.py"
    assert ren_file.old_filename == "legacy.py"
    assert ren_file.status == "renamed"

    # 4. Binary file
    bin_file = files[3]
    assert bin_file.filename == "assets/logo.png"
    assert bin_file.is_binary is True


def test_parse_patch_to_hunks():
    patch = (
        "@@ -1,4 +1,5 @@\n"
        " import os\n"
        "+import sys\n"
        " \n"
        " def main():\n"
        "     pass\n"
    )
    hunks = parse_patch_to_hunks(patch)
    assert len(hunks) == 1
    hunk = hunks[0]
    assert hunk.new_start == 1
    assert 2 in hunk.added_new_lines
    assert 1 in hunk.valid_new_lines
    assert 3 in hunk.valid_new_lines


# ═══════════════════════════════════════════════
# snap_finding_line regression tests
# ═══════════════════════════════════════════════


def _build_jian_live_bug_file() -> ChangedFile:
    """Build the exact ChangedFile from the live JIAN bug on Urvity03/jian-external-test#1.

    Diff:
        @@ -12,3 +12,8 @@ def format_summary(items=[]):
             for item in items:
                 summary_text += str(item) + ", "
             return summary_text
        +
        +
        +def get_ratio(value, divisor):
        +    return value / divisor
        +

    New-file lines: 12-19.
    Added lines: 15 (blank), 16 (blank), 17 (def), 18 (return), 19 (blank).
    """
    patch = (
        '@@ -12,3 +12,8 @@ def format_summary(items=[]):\n'
        '     for item in items:\n'
        '         summary_text += str(item) + ", "\n'
        '     return summary_text\n'
        '+\n'
        '+\n'
        '+def get_ratio(value, divisor):\n'
        '+    return value / divisor\n'
        '+\n'
    )
    hunks = parse_patch_to_hunks(patch)
    return ChangedFile(
        filename="src/app.py",
        status="modified",
        additions=5,
        deletions=0,
        patch=patch,
        hunks=hunks,
    )


def test_snap_finding_line_exact_jian_live_bug():
    """Regression: JIAN posted comment at line 19 (trailing blank) instead of line 18
    (return value / divisor).  snap_finding_line must correct 19 → 18."""
    cf = _build_jian_live_bug_file()
    assert snap_finding_line(cf, 19) == 18


def test_snap_finding_line_exact_added_line_no_change():
    """A finding on an exact non-blank added line must not be moved."""
    cf = _build_jian_live_bug_file()
    assert snap_finding_line(cf, 18) == 18  # return value / divisor
    assert snap_finding_line(cf, 17) == 17  # def get_ratio(...)


def test_snap_finding_line_last_code_before_trailing_blank():
    """The last code line (18) before trailing blank (19) stays at 18."""
    cf = _build_jian_live_bug_file()
    # Line 18 is non-blank → returned as-is
    assert snap_finding_line(cf, 18) == 18


def test_snap_finding_line_blank_between_code_lines_snaps_to_nearest():
    """Blank lines between two code lines should snap to the nearest (before preferred)."""
    cf = _build_jian_live_bug_file()
    # Line 16 is blank. Nearest added code lines: 17 (distance 1) and 18 (distance 2).
    assert snap_finding_line(cf, 16) == 17
    # Line 15 is blank. Nearest added code lines: 17 (distance 2) and 18 (distance 3).
    assert snap_finding_line(cf, 15) == 17


def test_snap_finding_line_multiple_hunks():
    """Findings in multi-hunk diffs should snap within their own hunk."""
    patch = (
        '@@ -1,3 +1,4 @@\n'
        ' line1\n'
        '+added_line_A\n'
        '+\n'
        ' line3\n'
        '@@ -10,2 +11,4 @@\n'
        ' context10\n'
        '+code_B\n'
        '+\n'
        ' context12\n'
    )
    hunks = parse_patch_to_hunks(patch)
    cf = ChangedFile(
        filename="multi.py", status="modified",
        additions=4, deletions=0, patch=patch, hunks=hunks,
    )
    # Hunk 1: line 3 is blank added → snap to line 2 (added_line_A)
    assert snap_finding_line(cf, 3) == 2
    # Hunk 2: line 13 is blank added → snap to line 12 (code_B)
    assert snap_finding_line(cf, 13) == 12


def test_snap_finding_line_none_passthrough():
    """snap_finding_line only receives int line numbers; the caller handles None.
    When line is not in any hunk, it should return unchanged."""
    cf = _build_jian_live_bug_file()
    # Line 999 is not in any hunk
    assert snap_finding_line(cf, 999) == 999


def test_snap_finding_line_context_line_unchanged():
    """Context (unchanged) lines are not in added_new_lines, so snap returns them as-is."""
    cf = _build_jian_live_bug_file()
    # Lines 12-14 are context lines
    assert snap_finding_line(cf, 12) == 12
    assert snap_finding_line(cf, 14) == 14


def test_snap_finding_line_all_blank_hunk_returns_original():
    """If a hunk contains only blank added lines, snap returns the original line."""
    patch = (
        '@@ -5,2 +5,4 @@\n'
        ' context\n'
        '+\n'
        '+\n'
        ' end\n'
    )
    hunks = parse_patch_to_hunks(patch)
    cf = ChangedFile(
        filename="blanks.py", status="modified",
        additions=2, deletions=0, patch=patch, hunks=hunks,
    )
    # Line 6 is blank added, line 7 is blank added — no non-blank candidate
    assert snap_finding_line(cf, 6) == 6
    assert snap_finding_line(cf, 7) == 7
