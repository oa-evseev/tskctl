# src/tskctl/engine/validate.py

"""
Task validation rules.

This module validates parsed Task objects against repository-wide
conventions and semantic rules.

Responsibilities:
- high-level invariants (beyond parsing),
- log structure and conventions,
- link sanity checks.

It does NOT perform parsing or filesystem scanning.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .model import Link, Status, Task


# ---------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------

class ValidationError(Exception):
    """
    Fatal validation error used for command flow control.

    Raised when validation must immediately abort an operation
    (e.g. missing required user input).
    """


# ---------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """
    A single validation problem.

    `code` is a stable identifier suitable for tests and future filtering.
    """

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """
    Aggregated validation result for a single task file.
    """

    path: str
    issues: Sequence[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not self.issues


# ---------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------

_LOG_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}:\s+\[[a-z_]+\](?:\s+.+)?$")


def validate_task_file(
    task: Task,
    task_dir: str | Path,
    *,
    expected_task_id: Optional[str] = None,
    check_links: bool = False,
    project_root: Optional[str | Path] = None,
) -> ValidationResult:
    """
    Validate a parsed Task against repository rules.

    Notes:
    - YAML syntax and section presence are parse-layer responsibilities.
    - This function validates higher-level invariants and conventions.
    - `expected_task_id` is typically the task directory name.
    - When `check_links` is True, file links are checked for existence.
      `project_root` is required for resolving relative file links.
    """
    p = Path(task_dir)
    issues: list[ValidationIssue] = []

    # -----------------------------------------------------------------
    # Identity checks
    # -----------------------------------------------------------------

    if expected_task_id is not None and task.task_id != expected_task_id:
        issues.append(
            ValidationIssue(
                code="id_mismatch",
                message=(
                    f"Task id '{task.task_id}' does not match "
                    f"expected id '{expected_task_id}'"
                ),
            )
        )

    # Model-level invariants (strict by design)
    try:
        task.validate()
    except ValueError as e:
        issues.append(
            ValidationIssue(
                code="model_invariant",
                message=str(e),
            )
        )

    # -----------------------------------------------------------------
    # Log rules (strict, XHTML-like discipline)
    # -----------------------------------------------------------------

    if not task.log_lines:
        issues.append(
            ValidationIssue(
                code="log_empty",
                message="Log section is empty (at least one entry is required)",
            )
        )
    else:
        for i, line in enumerate(task.log_lines, start=1):
            s = line.strip()
            if not s:
                continue

            if not _LOG_LINE_RE.match(s):
                issues.append(
                    ValidationIssue(
                        code="log_bad_format",
                        message=f"Log line {i} must match 'YYYY-MM-DD: [type] comment'",
                    )
                )

    # Done tasks must have an explicit closing marker.
    if task.status is Status.DONE and task.log_lines:
        if not _has_done_marker(task.log_lines):
            issues.append(
                ValidationIssue(
                    code="done_no_marker",
                    message=(
                        "Done tasks must include a closing log entry "
                        "containing '[done]'"
                    ),
                )
            )

    # -----------------------------------------------------------------
    # Links rules
    # -----------------------------------------------------------------

    for i, link in enumerate(task.links, start=1):
        _validate_link_basic(link, issues, i)

    if check_links:
        if project_root is None:
            issues.append(
                ValidationIssue(
                    code="links_need_project_root",
                    message=(
                        "check_links requires project_root "
                        "to resolve relative file links"
                    ),
                )
            )
        else:
            _check_file_links_exist(task.links, Path(project_root), issues)

    return ValidationResult(path=str(p), issues=tuple(issues))


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _has_done_marker(log_lines: Iterable[str]) -> bool:
    """
    Return True if log contains a '[done]' marker (searching from the end).
    """
    for line in reversed(list(log_lines)):
        s = line.strip().lower()
        if not s:
            continue
        if "[done]" in s:
            return True
    return False


def _validate_link_basic(
    link: Link,
    issues: list[ValidationIssue],
    idx: int,
) -> None:
    """
    Validate basic link invariants without filesystem access.
    """
    kind = (link.kind or "").strip().lower()
    value = (link.value or "").strip()

    if kind not in {"file", "url", "note"}:
        issues.append(
            ValidationIssue(
                code="link_kind_invalid",
                message=(
                    f"Link {idx}: invalid kind '{link.kind}' "
                    "(allowed: file, url, note)"
                ),
            )
        )

    if not value:
        issues.append(
            ValidationIssue(
                code="link_value_empty",
                message=f"Link {idx}: empty value",
            )
        )


def _check_file_links_exist(
    links: Sequence[Link],
    project_root: Path,
    issues: list[ValidationIssue],
) -> None:
    """
    Check that file links exist and stay within project_root.
    """
    root = project_root.resolve()

    for link in links:
        if link.kind.strip().lower() != "file":
            continue

        rel = link.value.strip()
        target = (root / rel).resolve()

        try:
            target.relative_to(root)
        except Exception:
            issues.append(
                ValidationIssue(
                    code="link_file_outside_project",
                    message=f"File link points outside project root: {rel}",
                )
            )
            continue

        if not target.exists():
            issues.append(
                ValidationIssue(
                    code="link_file_missing",
                    message=f"Missing linked file: {rel}",
                )
            )
