# src/tskctl/engine/render.py

"""
Rendering helpers for CLI output.

This module is responsible for:
- project tree rendering (list / here),
- structured task detail view (show).

It is presentation-only: it may call parsing functions to load tasks, but
should not mutate task state or write files.
"""

from __future__ import annotations

import re
import shutil
import textwrap
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from .model import Project, Status, Task, sort_tasks
from .parse import parse_task
from .scan import iter_task_files


# ---------------------------------------------------------------------
# ANSI / terminal helpers
# ---------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_RESET = "\033[0m"
_DIM = "\033[90m"

_COLOR = {
    Status.ACTIVE: "\033[32m",   # green
    Status.WAITING: "\033[33m",  # yellow
    Status.PAUSED: "\033[34m",   # blue
    Status.DONE: "\033[90m",     # grey
}


def _supports_color() -> bool:
    """Return True if stdout is a TTY."""
    import sys

    return sys.stdout.isatty()


def _visible_len(s: str) -> int:
    """Return string length without ANSI colour escapes."""
    return len(_ANSI_RE.sub("", s))


# ---------------------------------------------------------------------
# Task list helpers
# ---------------------------------------------------------------------

def _print_project_block(node: "ProjectNode", *, prefix: str, color: bool) -> None:
    """
    Print tasks for a single project node.

    Tasks always come BEFORE subdirectories.

    Format:
      - Title (status: next action, Nd)
    """
    today = date.today()

    sep = "=" * 6
    print(f"{prefix}{sep}")

    for task in node.tasks:
        status = task.status.value
        status_col = status
        if color and _supports_color():
            c = _COLOR.get(task.status, "")
            status_col = f"{c}{status}{_RESET}"

        action = task.next_action.strip()
        if action:
            action = action.splitlines()[0].strip()
        else:
            action = "–"

        age_days = (today - task.last_touch).days
        age = f"{age_days}d"

        meta = f"{status_col}: {action}, {age}"
        print(f"{prefix}- {task.title} ({meta}) id: {task.task_id}")

    print(f"{prefix}{sep}")


# ---------------------------------------------------------------------
# Task detail view (show)
# ---------------------------------------------------------------------

def render_task_detail(task: Task, *, color: bool = True) -> None:
    """
    Render a structured task detail view.

    Width is capped at 80 characters (by design).
    """
    width = min(80, shutil.get_terminal_size(fallback=(80, 24)).columns)
    inner_w = max(20, width - 4)  # borders + padding

    def cdim(s: str) -> str:
        return f"{_DIM}{s}{_RESET}" if color and _supports_color() else s

    def cstat(s: str) -> str:
        if not (color and _supports_color()):
            return s
        c = _COLOR.get(task.status, "")
        return f"{c}{s}{_RESET}"

    def wrap_lines(s: str, *, indent: str = "") -> list[str]:
        if not s:
            return []

        out: list[str] = []
        for ln in s.rstrip().splitlines() or [""]:
            if not ln.strip():
                out.append(indent.rstrip())
                continue

            wrapped = textwrap.wrap(
                ln,
                width=inner_w - len(indent),
                break_long_words=False,
                break_on_hyphens=False,
            ) or [""]

            out.extend([indent + x for x in wrapped])

        return out

    def box_rule(ch: str = "-") -> None:
        print(f"+{ch * (width - 2)}+")

    def box_sep() -> None:
        print(f"+{'-' * (width - 2)}+")

    def box_line(content: str = "") -> None:
        raw = content[:inner_w]
        pad = inner_w - _visible_len(raw)
        if pad > 0:
            raw = raw + (" " * pad)
        print(f"| {raw} |")

    def box_title(left: str, right: str = "") -> None:
        if right:
            space = inner_w - len(left) - len(right) - 1
            if space >= 0:
                box_line(f"{left}{' ' * space} {right}")
                return
        box_line(left)

    status_text = cstat(task.status.value)
    title = f"{task.title} ({status_text})"

    today = date.today()
    age_days = (today - task.last_touch).days

    created_s = task.created.isoformat()
    touch_s = task.last_touch.isoformat()

    if color and _supports_color():
        created_s = cdim(created_s)
        touch_s = cstat(touch_s)

    print()
    box_rule("=")
    box_title(title)
    box_rule("=")

    box_title(f"id: {task.task_id}")
    box_title(f"created: {created_s}")
    box_title(f"last_touch: {touch_s} ({age_days} days)")

    if task.next_action.strip():
        box_sep()
        box_line("Next action:")
        for ln in wrap_lines(task.next_action, indent="  "):
            box_line(ln)

    if task.summary.strip():
        box_sep()
        box_line("Summary:")
        for ln in wrap_lines(task.summary, indent="  "):
            box_line(ln)

    if task.log_lines:
        box_sep()
        box_line("Log:")
        for raw in task.log_lines:
            s = raw.rstrip()
            if not s:
                continue
            for ln in wrap_lines(s, indent="  "):
                box_line(ln)

    if task.links:
        box_sep()
        box_line("Links:")
        for link in task.links:
            line = f"{link.kind}: {link.value}"
            for ln in wrap_lines(line, indent="  "):
                box_line(ln)

    box_rule("=")
    print()


# ---------------------------------------------------------------------
# Project tree model (render-only)
# ---------------------------------------------------------------------

@dataclass(slots=True)
class ProjectNode:
    """
    A directory node used for rendering a project tree.
    """

    name: str
    path: Path
    is_project: bool = False
    tasks: list[Task] = field(default_factory=list)
    children: dict[str, "ProjectNode"] = field(default_factory=dict)


# ---------------------------------------------------------------------
# Tree build / attach
# ---------------------------------------------------------------------

def build_project_tree(root: Path, projects: Iterable[Project]) -> ProjectNode:
    """
    Build a directory tree rooted at `root` from a flat list of projects.

    A node becomes a project if it has a `.tasks` directory (i.e. appears in
    `projects`).
    """
    root = root.resolve()
    tree = ProjectNode(name=str(root), path=root, is_project=False)

    by_path: dict[Path, Project] = {}
    for p in projects:
        by_path[Path(p.root_dir).resolve()] = p

    for proj_path in sorted(by_path.keys(), key=lambda x: len(x.parts)):
        try:
            rel = proj_path.relative_to(root)
        except ValueError:
            continue

        cur = tree
        cur_path = root
        for part in rel.parts:
            cur_path = cur_path / part
            nxt = cur.children.get(part)
            if nxt is None:
                nxt = ProjectNode(name=part, path=cur_path, is_project=False)
                cur.children[part] = nxt
            cur = nxt

        cur.is_project = True

    return tree


def attach_tasks(tree: ProjectNode) -> None:
    """
    Load tasks for every project node in the tree.

    Non-fatal: parse errors are ignored in list mode.
    """

    def walk(node: ProjectNode) -> None:
        if node.is_project:
            tasks_dir = node.path / ".tasks"
            project = Project(root_dir=str(node.path), tasks_dir=str(tasks_dir))

            tasks: list[Task] = []
            for tf in iter_task_files(project):
                try:
                    task = parse_task(tf.task_dir, expected_task_id=tf.task_id)
                except Exception:
                    continue
                tasks.append(task)

            node.tasks = sort_tasks(tasks)

        for child in node.children.values():
            walk(child)

    walk(tree)


# ---------------------------------------------------------------------
# Tree rendering
# ---------------------------------------------------------------------

def render_tree(tree: ProjectNode, *, color: bool = True) -> None:
    """
    Render the directory tree.

    Within each directory:
    - if it is a project: tasks first,
    - then subdirectories.
    """
    print(tree.path)

    if tree.is_project and tree.tasks:
        _print_project_block(tree, prefix="", color=color)

    _render_children(tree, prefix="", color=color)


def _render_children(node: ProjectNode, *, prefix: str, color: bool) -> None:
    items = sorted(node.children.values(), key=lambda n: n.name.lower())
    for i, child in enumerate(items):
        is_last = i == (len(items) - 1)
        branch = "└── " if is_last else "├── "
        next_prefix = prefix + ("    " if is_last else "│   ")

        print(f"{prefix}{branch}{child.name}")

        if child.is_project and child.tasks:
            _print_project_block(child, prefix=next_prefix, color=color)

        _render_children(child, prefix=next_prefix, color=color)
