"""Tests for anti-hallucination validator and finding deduplication."""

from ai_reviewer.config import AppConfig
from ai_reviewer.models.review import CategoryEnum, ChangedFile, ReviewFinding, SeverityEnum
from ai_reviewer.validation import FindingValidator


def test_validator_rejects_hallucinated_file():
    cfg = AppConfig()
    changed_files = [
        ChangedFile(filename="src/valid.py", additions=5, deletions=0)
    ]
    validator = FindingValidator(cfg, changed_files)

    findings = [
        ReviewFinding(
            severity=SeverityEnum.HIGH,
            category=CategoryEnum.CORRECTNESS,
            title="Bug in fake file",
            description="Fake description",
            file="src/non_existent.py",
            line=10,
            confidence=0.95,
        )
    ]

    valid, rejections = validator.validate_and_filter(findings)
    assert len(valid) == 0
    assert len(rejections) == 1
    assert "not part of this pull request" in rejections[0]


def test_validator_rejects_low_confidence():
    cfg = AppConfig()
    cfg.review.confidence_threshold = 0.80
    changed_files = [
        ChangedFile(filename="src/valid.py", additions=5, deletions=0)
    ]
    validator = FindingValidator(cfg, changed_files)

    findings = [
        ReviewFinding(
            severity=SeverityEnum.MEDIUM,
            category=CategoryEnum.MAINTAINABILITY,
            title="Speculative code smell",
            description="Maybe improve this?",
            file="src/valid.py",
            line=1,
            confidence=0.60,
        )
    ]

    valid, rejections = validator.validate_and_filter(findings)
    assert len(valid) == 0
    assert "below threshold" in rejections[0]


def test_validator_deduplicates_identical_findings():
    cfg = AppConfig()
    changed_files = [
        ChangedFile(filename="src/valid.py", additions=5, deletions=0)
    ]
    validator = FindingValidator(cfg, changed_files)

    f1 = ReviewFinding(
        severity=SeverityEnum.HIGH,
        category=CategoryEnum.SECURITY,
        title="Command injection",
        description="Dangerous exec call",
        file="src/valid.py",
        line=12,
        confidence=0.95,
    )
    f2 = ReviewFinding(
        severity=SeverityEnum.HIGH,
        category=CategoryEnum.SECURITY,
        title="Command injection!",
        description="Dangerous exec call duplicate",
        file="src/valid.py",
        line=12,
        confidence=0.95,
    )

    valid, rejections = validator.validate_and_filter([f1, f2])
    assert len(valid) == 1
    assert len(rejections) == 1
    assert "duplicate fingerprint" in rejections[0]
