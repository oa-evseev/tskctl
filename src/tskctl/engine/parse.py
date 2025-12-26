# src/tskctl/engine/parse.py

"""
Task case parser (v2 directory layout).

Parses a task directory into an in-memory Task model.

Directory structure (required unless stated otherwise):
- task.yml   (required)  : core metadata + links
- task.log   (required)  : append-only log (one entry per line, including "YYYY-MM-DD: [type] comment")
- summary.md (optional)  : free-form human-readable summary (stored as plain text)

This module performs *structural* parsing only and returns a Task model.
Model-level invariants are enforced via Task.validate().
"""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Optional

import yaml

from .model import Link, Status, Task


# ---------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------

TASK_YML_NAME: Final[str] = "task.yml"
TASK_LOG_NAME: Final[str] = "task.log"
SUMMARY_MD_NAME: Final[str] = "summary.md"

REQUIRED_FILES: Final[tuple[str, ...]] = (TASK_YML_NAME, TASK_LOG_NAME)
OPTIONAL_FILES: Final[tuple[str, ...]] = (SUMMARY_MD_NAME,)


# ---------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ParseError(Exception):
    """
    Raised when task directory contents are syntactically or structurally invalid.
    """

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------

def parse_task(task_dir: str | Path, expected_task_id: Optional[str] = None) -> Task:
    """
    Parse a task directory into a Task model.

    Parameters
    ----------
    task_dir:
        Directory containing task.yml and task.log (and optionally summary.md).

    expected_task_id:
        If provided, task.yml 'id' must match this value (usually directory name).
    """
    d = Path(task_dir)

    if not d.exists():
        raise ParseError(str(d), "Task directory does not exist")
    if not d.is_dir():
        raise ParseError(str(d), "Task path is not a directory")

    _require_files(d)

    meta = _parse_task_yml(d / TASK_YML_NAME)
    log_lines = _parse_task_log(d / TASK_LOG_NAME)
    summary = _read_optional_text(d / SUMMARY_MD_NAME)

    task_id = _require_str_field(str(d / TASK_YML_NAME), meta, "id")
    if expected_task_id is not None and task_id != expected_task_id:
        raise ParseError(
            str(d / TASK_YML_NAME),
            f"YAML id '{task_id}' does not match expected id '{expected_task_id}'",
        )

    title = _require_str_field(str(d / TASK_YML_NAME), meta, "title")
    status = _parse_status(str(d / TASK_YML_NAME), meta)
    created = _parse_date(str(d / TASK_YML_NAME), meta, "created")
    last_touch = _parse_date(str(d / TASK_YML_NAME), meta, "last_touch")
    next_action = _require_str_field(str(d / TASK_YML_NAME), meta, "next_action", allow_empty=True)

    links = _parse_links(str(d / TASK_YML_NAME), meta)

    format_version = _optional_int_field(meta, "format", default=2)

    task = Task(
        task_id=task_id,
        title=title,
        status=status,
        created=created,
        last_touch=last_touch,
        next_action=next_action,
        summary=(summary or "").strip(),
        log_lines=log_lines,
        links=links,
        format_version=format_version,
    )

    task.validate()
    return task


# ---------------------------------------------------------------------
# File presence
# ---------------------------------------------------------------------

def _require_files(task_dir: Path) -> None:
    missing: list[str] = []
    for name in REQUIRED_FILES:
        p = task_dir / name
        if not p.is_file():
            missing.append(name)

    if missing:
        raise ParseError(str(task_dir), f"Missing required file(s): {', '.join(missing)}")


# ---------------------------------------------------------------------
# task.yml
# ---------------------------------------------------------------------

def _parse_task_yml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ParseError(str(path), f"Cannot read file: {e}") from e

    try:
        data = yaml.safe_load(text) or {}
    except Exception as e:
        raise ParseError(str(path), f"Invalid YAML: {e}") from e

    if not isinstance(data, dict):
        raise ParseError(str(path), "YAML root must be a mapping/dictionary")

    return data


def _require_str_field(
    path: str,
    data: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    if key not in data:
        raise ParseError(path, f"Missing required YAML key: {key}")

    value = data[key]
    if not isinstance(value, str):
        raise ParseError(path, f"YAML key '{key}' must be a string")

    if not allow_empty and not value.strip():
        raise ParseError(path, f"YAML key '{key}' must be a non-empty string")

    return value


def _optional_int_field(data: dict[str, Any], key: str, *, default: int) -> int:
    value = data.get(key, default)
    return value if isinstance(value, int) else default


def _parse_status(path: str, data: dict[str, Any]) -> Status:
    raw = _require_str_field(path, data, "status")
    try:
        return Status(raw.strip().lower())
    except Exception as e:
        allowed = ", ".join([s.value for s in Status])
        raise ParseError(path, f"Invalid status '{raw}' (allowed: {allowed})") from e


def _parse_date(path: str, data: dict[str, Any], key: str) -> date:
    if key not in data:
        raise ParseError(path, f"Missing required YAML key: {key}")

    value = data[key]

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as e:
            raise ParseError(path, f"Invalid ISO date for '{key}': '{value}'") from e

    raise ParseError(path, f"YAML key '{key}' must be an ISO date string")


def _parse_links(path: str, data: dict[str, Any]) -> list[Link]:
    raw = data.get("links", [])
    if raw is None:
        return []

    if not isinstance(raw, list):
        raise ParseError(path, "YAML key 'links' must be a list")

    out: list[Link] = []
    for i, item in enumerate(raw, start=1):
        if isinstance(item, str):
            # Allow a minimal shorthand: "kind: value" (or bare value -> file).
            s = item.strip()
            if not s:
                continue
            if ":" in s.split()[0]:
                kind, value = s.split(":", 1)
                kind = kind.strip().lower()
                value = value.strip()
            else:
                kind = "file"
                value = s
            out.append(Link(kind=kind, value=value))
            continue

        if isinstance(item, dict):
            kind = item.get("kind")
            value = item.get("value")
            if not isinstance(kind, str) or not isinstance(value, str):
                raise ParseError(path, f"links[{i}] must have string 'kind' and 'value'")
            out.append(Link(kind=kind.strip().lower(), value=value.strip()))
            continue

        raise ParseError(path, f"links[{i}] must be a mapping {{kind, value}} or a string")

    return out


# ---------------------------------------------------------------------
# task.log
# ---------------------------------------------------------------------

def _parse_task_log(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ParseError(str(path), f"Cannot read file: {e}") from e

    lines: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        lines.append(raw.rstrip())

    if not lines:
        raise ParseError(str(path), "Log file is empty (at least one entry is required)")

    return lines


# ---------------------------------------------------------------------
# summary.md (optional)
# ---------------------------------------------------------------------

def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise ParseError(str(path), "summary.md exists but is not a file")

    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise ParseError(str(path), f"Cannot read file: {e}") from e
