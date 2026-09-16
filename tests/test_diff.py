"""Tests for unified diff parser and hunk analysis."""

from ai_reviewer.diff import is_line_in_diff, parse_patch_to_hunks, parse_unified_diff

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
