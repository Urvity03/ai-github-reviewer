"""Unified diff parser and hunk analyzer."""

from __future__ import annotations

import re

from ai_reviewer.models.review import ChangedFile, DiffHunk

# Regex for diff header: @@ -12,4 +15,6 @@ optional function header
HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_lines>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_lines>\d+))?\s+@@(?P<header>.*)$"
)


def parse_unified_diff(diff_text: str) -> list[ChangedFile]:
    """Parse unified git diff text into structured ChangedFile instances."""
    if not diff_text or not diff_text.strip():
        return []

    files: list[ChangedFile] = []
    current_file: ChangedFile | None = None
    current_hunk: DiffHunk | None = None
    current_new_line_num = 0

    lines = diff_text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # Check for diff header: diff --git a/path b/path
        if line.startswith("diff --git "):
            if current_hunk and current_file:
                current_file.hunks.append(current_hunk)
                current_hunk = None
            if current_file:
                files.append(current_file)

            parts = line.split(" ")
            # standard format: diff --git a/foo b/bar
            old_path = parts[2][2:] if len(parts) > 2 and parts[2].startswith("a/") else ""
            new_path = parts[3][2:] if len(parts) > 3 and parts[3].startswith("b/") else ""

            current_file = ChangedFile(
                filename=new_path or old_path,
                old_filename=old_path if old_path != new_path else None,
                status="modified",
            )
            i += 1
            continue

        # Check for new/deleted/rename status lines
        if current_file:
            if line.startswith("new file mode"):
                current_file.status = "added"
            elif line.startswith("deleted file mode"):
                current_file.status = "deleted"
            elif line.startswith("similarity index"):
                current_file.status = "renamed"
            elif line.startswith("rename from "):
                current_file.old_filename = line[len("rename from "):].strip()
            elif line.startswith("rename to "):
                current_file.filename = line[len("rename to "):].strip()
            elif "Binary files " in line or "GIT binary patch" in line:
                current_file.is_binary = True

        # Check for hunk header
        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match and current_file:
            if current_hunk:
                current_file.hunks.append(current_hunk)

            old_start = int(hunk_match.group("old_start"))
            old_lines = int(hunk_match.group("old_lines") or 1)
            new_start = int(hunk_match.group("new_start"))
            new_lines = int(hunk_match.group("new_lines") or 1)
            header = hunk_match.group("header").strip()

            current_hunk = DiffHunk(
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
                header=header,
                lines=[line],
                added_new_lines=set(),
                valid_new_lines=set(),
            )
            current_new_line_num = new_start
            i += 1
            continue

        # Process lines within a hunk
        if current_hunk and current_file:
            if line.startswith("+"):
                current_file.additions += 1
                current_hunk.lines.append(line)
                current_hunk.added_new_lines.add(current_new_line_num)
                current_hunk.valid_new_lines.add(current_new_line_num)
                current_new_line_num += 1
            elif line.startswith("-"):
                current_file.deletions += 1
                current_hunk.lines.append(line)
                # Deletion line does not increment new file line counter
            elif line.startswith(" ") or line == "":
                current_hunk.lines.append(line)
                current_hunk.valid_new_lines.add(current_new_line_num)
                current_new_line_num += 1
            elif line.startswith(r"\ No newline at end of file"):
                current_hunk.lines.append(line)
            else:
                # Outside of hunk (e.g. metadata)
                pass

        i += 1

    if current_hunk and current_file:
        current_file.hunks.append(current_hunk)
    if current_file:
        files.append(current_file)

    return files


def parse_patch_to_hunks(patch: str) -> list[DiffHunk]:
    """Parse a single file patch string (as returned by GitHub API) into hunks."""
    if not patch:
        return []

    hunks: list[DiffHunk] = []
    current_hunk: DiffHunk | None = None
    current_new_line = 0

    for line in patch.splitlines():
        match = HUNK_HEADER_RE.match(line)
        if match:
            if current_hunk:
                hunks.append(current_hunk)
            old_start = int(match.group("old_start"))
            old_lines = int(match.group("old_lines") or 1)
            new_start = int(match.group("new_start"))
            new_lines = int(match.group("new_lines") or 1)
            header = match.group("header").strip()

            current_hunk = DiffHunk(
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
                header=header,
                lines=[line],
                added_new_lines=set(),
                valid_new_lines=set(),
            )
            current_new_line = new_start
            continue

        if current_hunk:
            if line.startswith("+"):
                current_hunk.lines.append(line)
                current_hunk.added_new_lines.add(current_new_line)
                current_hunk.valid_new_lines.add(current_new_line)
                current_new_line += 1
            elif line.startswith("-"):
                current_hunk.lines.append(line)
            elif line.startswith(" ") or line == "":
                current_hunk.lines.append(line)
                current_hunk.valid_new_lines.add(current_new_line)
                current_new_line += 1
            elif line.startswith(r"\ No newline at end of file"):
                current_hunk.lines.append(line)

    if current_hunk:
        hunks.append(current_hunk)

    return hunks


def is_line_in_diff(changed_file: ChangedFile, line_number: int, require_modified: bool = False) -> bool:
    """Check if a given line number exists in the diff hunks of the file."""
    if not changed_file.hunks:
        return False
    if require_modified:
        return line_number in changed_file.get_added_or_modified_lines()
    return line_number in changed_file.get_valid_lines()


def _build_hunk_line_content_map(hunk: DiffHunk) -> dict[int, str]:
    """Build a mapping from new-file line numbers to their raw content for a single hunk.

    Walks the hunk lines (including the @@ header), tracking the current new-file
    line counter for '+' and context (' '/empty) lines.  Deletion lines ('-') and
    metadata lines ('\\ No newline …') are skipped since they have no new-file number.
    """
    content_map: dict[int, str] = {}
    current_new_line = hunk.new_start
    for raw_line in hunk.lines:
        if HUNK_HEADER_RE.match(raw_line):
            continue
        if raw_line.startswith("+"):
            # Strip the leading '+' to get the actual source content
            content_map[current_new_line] = raw_line[1:]
            current_new_line += 1
        elif raw_line.startswith("-"):
            # Deletion – does not consume a new-file line number
            pass
        elif raw_line.startswith(r"\ No newline at end of file"):
            pass
        else:
            # Context line (starts with ' ') or empty string
            content_map[current_new_line] = raw_line[1:] if raw_line.startswith(" ") else raw_line
            current_new_line += 1
    return content_map


def snap_finding_line(changed_file: ChangedFile, line_number: int) -> int:
    """Snap a finding's target line to the nearest non-blank added line in the same hunk.

    If *line_number* points to a blank (whitespace-only) added line, search the same
    hunk for the closest non-blank added line and return it.  Preference is given to
    the nearest line *before* the target (since findings usually refer to code that
    precedes a trailing blank), then to the nearest line *after*.

    If the line is already non-blank, or is a context (unchanged) line, or if no
    suitable snap target exists, the original *line_number* is returned unchanged.
    """
    for hunk in changed_file.hunks:
        if line_number not in hunk.added_new_lines:
            continue

        content_map = _build_hunk_line_content_map(hunk)

        # Check whether the target line is actually blank
        target_content = content_map.get(line_number, "")
        if target_content.strip():
            # Target line has real content – no snapping needed
            return line_number

        # Target is blank; find the nearest non-blank *added* line in this hunk
        best_line: int | None = None
        best_distance = float("inf")

        for candidate in sorted(hunk.added_new_lines):
            candidate_content = content_map.get(candidate, "")
            if not candidate_content.strip():
                continue  # skip other blank lines
            distance = abs(candidate - line_number)
            # Prefer lines before the target (negative direction wins ties)
            if distance < best_distance or (
                distance == best_distance and best_line is not None and candidate < best_line
            ):
                best_distance = distance
                best_line = candidate

        if best_line is not None:
            return best_line

        # No non-blank added line found in the hunk – return original
        return line_number

    # line_number is not in any hunk's added_new_lines – return as-is
    return line_number
