# src/tskctl/engine/actions.py

"""
Task mutation actions.

This module contains *all* state-changing operations on Task objects:
status transitions, next-action updates, and touch events.

Design principles:
- No direct file parsing here (handled elsewhere).
- All mutations must append a log entry and update last_touch.
- Validation errors are raised early and explicitly.
"""

from datetime import date
from pathlib import Path
from typing import Optional

from .model import Status, Task
from .ops import write_task
from .validate import ValidationError


# ---------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------

def _today() -> date:
    """Return today's date (isolated for testability)."""
    return date.today()


def _require_non_empty(value: Optional[str], prompt: str) -> str:
    """
    Ensure a non-empty string value.

    If `value` is empty or None, prompt interactively.
    Raises ValidationError on EOF or empty input.
    """
    if value and value.strip():
        return value.strip()

    try:
        value = input(f"{prompt}: ").strip()
    except EOFError as e:
        raise ValidationError(f"{prompt} is required") from e

    if not value:
        raise ValidationError(f"{prompt} is required")

    return value


def _append_log(task: Task, entry: str) -> None:
    """
    Append a dated log entry and update last_touch.
    """
    today = _today()
    task.log_lines.append(f"{today.isoformat()}: {entry}")
    task.last_touch = today


def _write(task: Task, task_dir: Path) -> None:
    """
    Persist task state to disk.
    """
    write_task(task_dir, task)


def _parse_status(raw: str) -> Status:
    """
    Parse and validate status string.
    """
    try:
        return Status(raw)
    except ValueError as e:
        raise ValidationError(f"Unknown status: {raw}") from e


# ---------------------------------------------------------------------
# Public actions
# ---------------------------------------------------------------------

def set_status(
    task: Task,
    task_dir: Path,
    *,
    status: str,
    message: Optional[str],
    next_action: Optional[str],
) -> None:
    """
    Change task status.

    - Message is always required.
    - next_action is required unless status is 'done'.
    """
    msg = _require_non_empty(message, "Message")

    if status != Status.DONE.value:
        task.next_action = _require_non_empty(next_action, "Next action")
    else:
        task.next_action = ""

    task.status = _parse_status(status)

    if status != Status.DONE.value:
        _append_log(task, f"[status] {status} - {msg}")
    else:
        _append_log(task, f"[done] {msg}")
    _write(task, task_dir)


def set_next_action(
    task: Task,
    task_dir: Path,
    *,
    next_action: Optional[str],
    message: Optional[str],
) -> None:
    """
    Update next_action for an active task.

    Forbidden for done tasks.
    """
    if task.status is Status.DONE:
        raise ValidationError("Cannot set next action on done task")

    msg = _require_non_empty(message, "Message")
    na = _require_non_empty(next_action, "Next action")

    task.next_action = na

    _append_log(task, f"[next] {na} - {msg}")
    _write(task, task_dir)


def touch_task(
    task: Task,
    task_dir: Path,
    *,
    message: Optional[str],
) -> None:
    """
    Touch task without changing its semantic state.

    Requires a message; updates last_touch and log.
    """
    msg = _require_non_empty(message, "Message")

    _append_log(task, f"[touch] - {msg}")
    _write(task, task_dir)
