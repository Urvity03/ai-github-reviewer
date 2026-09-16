"""Anti-hallucination finding validator and deduplication engine."""

from __future__ import annotations

from pathlib import Path

from ai_reviewer.config import AppConfig
from ai_reviewer.diff import is_line_in_diff
from ai_reviewer.models.review import ChangedFile, ReviewFinding


class FindingValidator:
    """Validates AI findings against actual files and git diffs to eliminate hallucinations."""

    def __init__(self, config: AppConfig, changed_files: list[ChangedFile], repo_root: Path | None = None):
        self.config = config
        self.changed_files_map: dict[str, ChangedFile] = {
            f.filename.replace("\\", "/"): f for f in changed_files
        }
        self.repo_root = repo_root or Path.cwd()

    def validate_and_filter(
        self, findings: list[ReviewFinding]
    ) -> tuple[list[ReviewFinding], list[str]]:
        """
        Validate findings against diff hunks and confidence thresholds.
        Returns: (valid_findings, rejection_reasons)
        """
        valid_findings: list[ReviewFinding] = []
        rejection_reasons: list[str] = []
        seen_fingerprints: set[str] = set()

        for finding in findings:
            norm_file = finding.file.replace("\\", "/").lstrip("./")

            # 1. Confidence threshold
            if finding.confidence < self.config.review.confidence_threshold:
                rejection_reasons.append(
                    f"Rejected '{finding.title}' in {norm_file}: confidence {finding.confidence:.2f} "
                    f"is below threshold {self.config.review.confidence_threshold:.2f}."
                )
                continue

            # 2. File verification
            changed_file = self.changed_files_map.get(norm_file)
            if not changed_file:
                # Check if it matches any changed file case-insensitively
                for cf_name, cf_obj in self.changed_files_map.items():
                    if cf_name.lower() == norm_file.lower():
                        changed_file = cf_obj
                        norm_file = cf_name
                        finding.file = cf_name
                        break

            if not changed_file:
                rejection_reasons.append(
                    f"Rejected '{finding.title}': file '{norm_file}' is not part of this pull request."
                )
                continue

            if changed_file.status == "deleted":
                rejection_reasons.append(
                    f"Rejected '{finding.title}': file '{norm_file}' was deleted in this pull request."
                )
                continue

            # 3. Line verification
            if finding.line is not None:
                # Check if the line is valid in the diff
                if not is_line_in_diff(changed_file, finding.line):
                    # If line is not in the diff, check if file exists on disk and line is within file bounds
                    local_path = self.repo_root / norm_file
                    if local_path.is_file():
                        try:
                            line_count = len(local_path.read_text(encoding="utf-8", errors="replace").splitlines())
                            if finding.line > line_count:
                                rejection_reasons.append(
                                    f"Rejected '{finding.title}': line {finding.line} exceeds total lines ({line_count}) in {norm_file}."
                                )
                                continue
                            else:
                                # Line exists in file, but not modified in diff -> demote from inline diff comment
                                # We keep finding but set line to None or preserve for summary
                                pass
                        except Exception:
                            pass
                    else:
                        # File not on disk or line completely invalid
                        finding.line = None

            # 4. Deduplication
            fp = finding.fingerprint
            if fp in seen_fingerprints:
                rejection_reasons.append(
                    f"Deduplicated '{finding.title}' on {norm_file}:{finding.line} (duplicate fingerprint {fp})."
                )
                continue

            seen_fingerprints.add(fp)
            valid_findings.append(finding)

        return valid_findings, rejection_reasons
