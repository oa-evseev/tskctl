# src/tskctl/engine/ops.py

"""
Filesystem-level operations and storage rendering.

This module contains:
- task store initialisation (.tasks directory),
- task id / slug generation,
- creation of new task case directories,
- serialisation of Task objects back to disk (task.yml, task.log, summary.md).

No parsing is performed here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

from .model import Link, Status
from .parse import TASK_YML_NAME, TASK_LOG_NAME, SUMMARY_MD_NAME

if TYPE_CHECKING:
    from .model import Task


# ---------------------------------------------------------------------
# Public request objects
# ---------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class NewTaskRequest:
    """
    Parameters for creating a new task case directory.
    """

    title: str
    status: Status = Status.ACTIVE
    next_action: str = ""
    summary: str = ""
    links: tuple[str, ...] = ()


# ---------------------------------------------------------------------
# Slugging / ids
# ---------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def slugify(title: str) -> str:
    """
    Convert title text to a filesystem-friendly slug.

    The slug is intended to be stable and predictable.
    """
    s = title.strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = _SLUG_RE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "task"


def next_task_seq(tasks_dir: Path, created: date) -> int:
    """
    Compute the next sequence number for the given creation date.
    """
    prefix = created.isoformat() + "__"
    best = 0

    if not tasks_dir.is_dir():
        return 1

    for p in tasks_dir.iterdir():
        if not p.is_dir():
            continue

        name = p.name
        if not name.startswith(prefix):
            continue

        parts = name.split("__", 2)
        if len(parts) < 2:
            continue

        try:
            n = int(parts[1])
        except ValueError:
            continue

        if n > best:
            best = n

    return best + 1


# ---------------------------------------------------------------------
# Store initialisation
# ---------------------------------------------------------------------

def ensure_tasks_dir(cwd: Path, *, interactive: bool = True) -> Path:
    """
    Ensure a `.tasks` directory exists in the given project directory.

    If `interactive` is True, prompt before creating it.
    """
    tasks_dir = cwd / ".tasks"
    if tasks_dir.is_dir():
        return tasks_dir

    if not interactive:
        tasks_dir.mkdir(parents=True, exist_ok=True)
        return tasks_dir

    ans = input("No .tasks found in this directory. Create ./.tasks here? [Y/n] ").strip().lower()
    if ans in {"", "y", "yes"}:
        tasks_dir.mkdir(parents=True, exist_ok=True)
        return tasks_dir

    raise RuntimeError("Aborted (no .tasks created)")


# ---------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------

def create_task(cwd: Path, req: NewTaskRequest, *, interactive: bool = True) -> Path:
    """
    Create a new task directory and write initial files.

    Returns the absolute path to the created task directory.
    """
    tasks_dir = ensure_tasks_dir(cwd, interactive=interactive)

    created = date.today()
    seq = next_task_seq(tasks_dir, created)
    slug = slugify(req.title)

    task_id = f"{created.isoformat()}__{seq:03d}__{slug}"
    task_dir = tasks_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=False)

    status = req.status
    next_action = req.next_action.strip()
    if status is Status.DONE:
        next_action = ""

    created_s = created.isoformat()

    # task.yml
    (task_dir / TASK_YML_NAME).write_text(
        _render_task_yml(
            task_id=task_id,
            title=req.title,
            status=status,
            created_s=created_s,
            last_touch_s=created_s,
            next_action=next_action,
            links=_normalise_links(req.links),
            format_version=2,
        ),
        encoding="utf-8",
    )

    # task.log
    log_lines = [f"{created_s}: [created]"]
    if status is Status.DONE:
        log_lines.append(f"{created_s}: [done]")
    (task_dir / TASK_LOG_NAME).write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    # summary.md (optional)
    summary = (req.summary or "").rstrip()
    if summary:
        (task_dir / SUMMARY_MD_NAME).write_text(summary + "\n", encoding="utf-8")

    return task_dir


# ---------------------------------------------------------------------
# Serialisation (directory layout)
# ---------------------------------------------------------------------

def write_task(task_dir: Path, task: "Task") -> None:
    """
    Persist Task state to disk by fully re-rendering its storage files.

    Behaviour:
    - `task.yml` is always overwritten from the in-memory Task model.
    - `task.log` is always overwritten from `task.log_lines`
      (append-only is a logical policy, not a storage constraint).
    - `summary.md` handling:
        * if `task.summary` is non-empty: the file is written/overwritten;
        * if `task.summary` is empty and `summary.md` exists: the file is deleted;
        * if `task.summary` is empty and `summary.md` does not exist: nothing is created.

    The task directory must already exist.
    """
    d = Path(task_dir)
    if not d.is_dir():
        raise FileNotFoundError(f"Task directory not found: {d}")

    # task.yml
    (d / TASK_YML_NAME).write_text(
        _render_task_yml(
            task_id=task.task_id,
            title=task.title,
            status=task.status,
            created_s=task.created.isoformat(),
            last_touch_s=task.last_touch.isoformat(),
            next_action=task.next_action,
            links=[Link(kind=ln.kind, value=ln.value) for ln in task.links],
            format_version=2,
        ),
        encoding="utf-8",
    )

    # task.log
    log_text = "\n".join([ln.rstrip() for ln in task.log_lines if ln.strip()]).rstrip() + "\n"
    (d / TASK_LOG_NAME).write_text(log_text, encoding="utf-8")

    # summary.md (optional)
    summary_path = d / SUMMARY_MD_NAME
    summary = (task.summary or "").rstrip()
    if summary:
        summary_path.write_text(summary + "\n", encoding="utf-8")
    else:
        if summary_path.exists():
            summary_path.unlink()


def _render_task_yml(
    *,
    task_id: str,
    title: str,
    status: Status,
    created_s: str,
    last_touch_s: str,
    next_action: str,
    links: list[Link],
    format_version: int,
) -> str:
    data = {
        "id": task_id,
        "title": title,
        "status": status.value,
        "created": created_s,
        "last_touch": last_touch_s,
        "next_action": next_action,
        "format": int(format_version),
        "links": [{"kind": ln.kind, "value": ln.value} for ln in links],
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _normalise_links(raw_links: tuple[str, ...]) -> list[Link]:
    """
    Convert NewTaskRequest.links into Link objects.

    Accepts:
    - "kind: value" where kind is file/url/note (case-insensitive),
    - bare "value" (assumed kind=file).
    """
    out: list[Link] = []

    for raw in raw_links:
        s = (raw or "").strip()
        if not s:
            continue

        if ":" in s.split()[0]:
            kind, value = s.split(":", 1)
            kind = kind.strip().lower()
            value = value.strip()
        else:
            kind = "file"
            value = s

        if not kind:
            kind = "file"

        out.append(Link(kind=kind, value=value))

    return out
