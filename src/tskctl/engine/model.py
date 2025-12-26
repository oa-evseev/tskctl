# src/tskctl/engine/model.py

"""
Core domain models.

This module defines the in-memory representations of tasks, links,
and projects, along with their core invariants and default ordering
rules.

No filesystem access should happen here.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Iterable


# ---------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------

class Status(str, Enum):
    """
    Task lifecycle status.

    Ordering reflects UX priority:
    what you can act on *now* should appear first.

    active > waiting > paused > done
    """

    ACTIVE = "active"
    WAITING = "waiting"
    PAUSED = "paused"
    DONE = "done"

    @classmethod
    def sort_key(cls, status: "Status") -> int:
        """
        Return numeric rank for list ordering.

        Lower value = higher priority.
        """
        order = {
            cls.ACTIVE: 0,
            cls.WAITING: 1,
            cls.PAUSED: 2,
            cls.DONE: 3,
        }
        return order[status]


# ---------------------------------------------------------------------
# Link
# ---------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Link:
    """
    A single link entry stored in a task file.

    `kind` is intentionally kept as a free string
    (expected values: "file", "url", "note")
    for forward compatibility.
    """

    kind: str
    value: str


# ---------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------

@dataclass(slots=True)
class Task:
    """
    In-memory representation of a task case file.

    Notes:
    - task_id must match the task directory name.
    - created and last_touch are dates (ISO-8601 in storage).
    - next_action must be non-empty unless status == DONE.
    """

    # Identity / core metadata
    task_id: str
    title: str
    status: Status

    # Temporal fields
    created: date
    last_touch: date

    # Behavioural fields
    next_action: str

    # Optional content
    summary: str = ""
    log_lines: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)

    # File format versioning
    format_version: int = 1

    # -----------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------

    def validate(self) -> None:
        """
        Validate core invariants independent of filesystem context.

        YAML syntax, section presence, and IO-related checks belong
        to parse/validate layers, not here.
        """
        if not self.task_id or not self.task_id.strip():
            raise ValueError("task_id must be a non-empty string")

        if not self.title or not self.title.strip():
            raise ValueError("title must be a non-empty string")

        if self.created > self.last_touch:
            raise ValueError("created must be <= last_touch")

        na = self.next_action.strip()
        if self.status is Status.DONE:
            if na:
                raise ValueError("next_action must be empty when status is 'done'")
        else:
            if not na:
                raise ValueError("next_action must be non-empty unless status is 'done'")

    # -----------------------------------------------------------------
    # Convenience properties
    # -----------------------------------------------------------------

    @property
    def is_done(self) -> bool:
        return self.status is Status.DONE

    @property
    def status_rank(self) -> int:
        return Status.sort_key(self.status)


# ---------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Project:
    """
    A project directory containing a local `.tasks` store.
    """

    root_dir: str   # absolute or relative, as discovered by scan
    tasks_dir: str  # typically f"{root_dir}/.tasks"

    def __post_init__(self) -> None:
        if not self.root_dir or not self.root_dir.strip():
            raise ValueError("root_dir must be a non-empty string")

        if not self.tasks_dir or not self.tasks_dir.strip():
            raise ValueError("tasks_dir must be a non-empty string")


# ---------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------

def sort_tasks(tasks: Iterable[Task]) -> list[Task]:
    """
    Default ordering for tasks within a single project:

    1. Status priority (active > waiting > paused > done)
    2. last_touch (older first)
    3. task_id (stable tie-breaker)
    """
    return sorted(
        tasks,
        key=lambda t: (
            t.status_rank,
            t.last_touch,
            t.task_id,
        ),
    )
