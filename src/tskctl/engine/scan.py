# src/tskctl/engine/scan.py

"""
Filesystem scanning utilities.

This module is responsible for discovering:
- project directories (directories containing `.tasks`),
- task case files within a project.

It performs *no parsing* and *no rendering*.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .model import Project


# ---------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class TaskFile:
    project: Project
    task_id: str
    task_dir: Path


# ---------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------

def iter_projects(root: str | Path, level: int) -> Iterator[Project]:
    """
    Yield projects in the subtree rooted at `root`.

    Semantics follow `tree -L N`, with a key rule:
    - `.tasks` is treated as metadata and does NOT count as a depth level.
    - A directory D is considered a project if D/.tasks exists.

    Depth definition:
    - root directory is depth 0,
    - its direct children are depth 1, etc.

    If `level` is 0, only the root directory is considered.
    """
    if level < 0:
        return

    root_path = Path(root)

    def walk_dir(d: Path, depth: int) -> Iterator[Project]:
        # Include current directory if it is a project.
        tasks_dir = d / ".tasks"
        if tasks_dir.is_dir():
            yield Project(root_dir=str(d), tasks_dir=str(tasks_dir))

        # Stop recursion if depth limit reached.
        if depth >= level:
            return

        # Recurse into child directories, skipping `.tasks`.
        try:
            for child in d.iterdir():
                if not child.is_dir():
                    continue
                if child.name == ".tasks":
                    continue
                yield from walk_dir(child, depth + 1)
        except PermissionError:
            # Non-fatal: silently skip unreadable directories.
            return

    yield from walk_dir(root_path, 0)


# ---------------------------------------------------------------------
# Task discovery
# ---------------------------------------------------------------------

def iter_task_files(project: Project) -> Iterator[TaskFile]:
    """
    Yield task directories for a given project.

    Expected on-disk structure:

        <project_root>/
          .tasks/
            <task_id>/
              task.yml
              task.log
              summary.md      (optional)
    """
    tasks_dir = Path(project.tasks_dir)
    if not tasks_dir.is_dir():
        return

    try:
        for entry in tasks_dir.iterdir():
            if not entry.is_dir():
                continue

            task_id = entry.name

            task_yml = entry / "task.yml"
            task_log = entry / "task.log"

            # Both are required
            if task_yml.is_file() and task_log.is_file():
                yield TaskFile(
                    project=project,
                    task_id=task_id,
                    task_dir=entry,
                )
    except PermissionError:
        # Non-fatal: silently skip unreadable task directories.
        return
