# src/tskctl/cli.py

"""
Command-line interface for tskctl.

This module:
- defines argument parsing and subcommands,
- delegates filesystem and domain logic to engine modules,
- keeps user interaction (prompts, selection) here.

KISS rule: keep commands small and predictable.
"""

import argparse
import shutil
import subprocess
from pathlib import Path

from tskctl.engine.actions import set_next_action, set_status, touch_task
from tskctl.engine.model import Status, Task
from tskctl.engine.ops import NewTaskRequest, create_task
from tskctl.engine.parse import ParseError, parse_task
from tskctl.engine.render import attach_tasks, build_project_tree, render_task_detail, render_tree
from tskctl.engine.scan import iter_projects, iter_task_files
from tskctl.engine.validate import ValidationError, validate_task_file


# ---------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tskctl")
    sub = parser.add_subparsers(dest="command", required=True)

    # ------------------------------------------------------------------
    # Read-only commands
    # ------------------------------------------------------------------

    p_validate = sub.add_parser(
        "validate",
        help="Validate task files in the subtree",
    )
    p_validate.add_argument(
        "-L",
        "--level",
        type=int,
        default=2,
        help="Scan depth (tree -L semantics; .tasks does not count as a level)",
    )
    p_validate.add_argument(
        "-C",
        "--cd",
        type=str,
        default=".",
        help="Work as if current directory is this path (default: .)",
    )
    p_validate.add_argument(
        "--check-links",
        action="store_true",
        help="Check existence of linked files (project-root-relative)",
    )
    p_validate.set_defaults(func=cmd_validate)

    p_list = sub.add_parser(
        "list",
        help="List tasks as a project tree",
    )
    p_list.add_argument(
        "-L",
        "--level",
        type=int,
        default=2,
        help="Scan depth (tree -L semantics; .tasks does not count as a level)",
    )
    p_list.add_argument(
        "-C",
        "--cd",
        type=str,
        default=".",
        help="Work as if current directory is this path (default: .)",
    )
    p_list.set_defaults(func=cmd_list)

    p_here = sub.add_parser(
        "here",
        help="List tasks only for the current directory",
    )
    p_here.add_argument(
        "-C",
        "--cd",
        type=str,
        default=".",
        help="Work as if current directory is this path (default: .)",
    )
    p_here.set_defaults(func=cmd_here)

    p_show = sub.add_parser(
        "show",
        help="Show a single task (structured view)",
    )
    p_show.add_argument(
        "task_id",
        nargs="?",
        default="",
        help="Task id (directory name under .tasks)",
    )
    p_show.add_argument(
        "--no-color",
        action="store_true",
        help="Disable coloured output",
    )
    p_show.add_argument(
        "-C",
        "--cd",
        type=str,
        default=".",
        help="Work as if current directory is this path (default: .)",
    )
    p_show.set_defaults(func=cmd_show)

    # ------------------------------------------------------------------
    # Create command
    # ------------------------------------------------------------------

    p_new = sub.add_parser(
        "new",
        help="Create a new task in the current project",
    )
    p_new.add_argument("--title", type=str, default="", help="Task title")
    p_new.add_argument(
        "--status",
        type=str,
        default="active",
        choices=["active", "waiting", "paused", "done"],
        help="Initial status",
    )
    p_new.add_argument(
        "--next-action",
        type=str,
        default="",
        help="Required unless status=done",
    )
    p_new.add_argument("--summary", type=str, default="", help="Short summary text")
    p_new.add_argument(
        "--link",
        action="append",
        default=[],
        help=(
            "Link entry (repeatable). "
            "Accepts 'file: x', 'url: x', 'note: x' or bare path (assumed file)."
        ),
    )
    p_new.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt; create .tasks automatically if missing",
    )
    p_new.add_argument(
        "-C",
        "--cd",
        type=str,
        default=".",
        help="Work as if current directory is this path (default: .)",
    )
    p_new.set_defaults(func=cmd_new)

    # ------------------------------------------------------------------
    # Write commands
    # ------------------------------------------------------------------

    p_status = sub.add_parser(
        "status",
        help="Change task status",
    )
    p_status.add_argument(
        "status",
        choices=["active", "waiting", "paused", "done"],
        help="New task status",
    )
    p_status.add_argument(
        "task_id",
        nargs="?",
        help="Task id (optional if only one task exists)",
    )
    p_status.add_argument(
        "-m",
        "--message",
        type=str,
        help="Commit message (required)",
    )
    p_status.add_argument(
        "--next",
        dest="next_action",
        type=str,
        help="Next action (required if status is not done)",
    )
    p_status.add_argument(
        "-C",
        "--cd",
        type=str,
        default=".",
        help="Work as if current directory is this path (default: .)",
    )
    p_status.set_defaults(func=cmd_status)

    p_done = sub.add_parser(
        "done",
        help="Mark task as done",
    )
    p_done.add_argument(
        "task_id",
        nargs="?",
        help="Task id (optional if only one task exists)",
    )
    p_done.add_argument(
        "-m",
        "--message",
        type=str,
        help="Commit message (required)",
    )
    p_done.add_argument(
        "-C",
        "--cd",
        type=str,
        default=".",
        help="Work as if current directory is this path (default: .)",
    )
    p_done.set_defaults(func=cmd_done)

    p_next = sub.add_parser(
        "next",
        help="Set next action for task",
    )
    p_next.add_argument(
        "task_id",
        nargs="?",
        help="Task id (optional if only one task exists)",
    )
    p_next.add_argument(
        "--next",
        dest="next_action",
        type=str,
        help="Next action (required)",
    )
    p_next.add_argument(
        "-m",
        "--message",
        type=str,
        help="Commit message (required)",
    )
    p_next.add_argument(
        "-C",
        "--cd",
        type=str,
        default=".",
        help="Work as if current directory is this path (default: .)",
    )
    p_next.set_defaults(func=cmd_next)

    p_touch = sub.add_parser(
        "touch",
        help="Touch task without changing its state",
    )
    p_touch.add_argument(
        "task_id",
        nargs="?",
        help="Task id (optional if only one task exists)",
    )
    p_touch.add_argument(
        "-m",
        "--message",
        type=str,
        help="Commit message (required)",
    )
    p_touch.add_argument(
        "-C",
        "--cd",
        type=str,
        default=".",
        help="Work as if current directory is this path (default: .)",
    )
    p_touch.set_defaults(func=cmd_touch)

    return parser


# ---------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------

def cmd_validate(args: argparse.Namespace) -> int:
    base = Path.cwd()
    root = (base / (args.cd or ".")).resolve()
    level = args.level
    check_links = bool(args.check_links)

    had_errors = False

    for project in iter_projects(root, level=level):
        project_root = Path(project.root_dir)

        for tf in iter_task_files(project):
            try:
                task = parse_task(tf.task_dir, expected_task_id=tf.task_id)
            except ParseError as e:
                had_errors = True
                print(str(e))
                continue

            res = validate_task_file(
                task,
                tf.task_dir,
                expected_task_id=tf.task_id,
                check_links=check_links,
                project_root=project_root,
            )

            if not res.ok:
                had_errors = True
                print(f"{res.path}")
                for issue in res.issues:
                    print(f"  - {issue.code}: {issue.message}")

    return 1 if had_errors else 0


def cmd_list(args: argparse.Namespace) -> int:
    base = Path.cwd()
    root = (base / (args.cd or ".")).resolve()
    level = args.level

    projects = list(iter_projects(root, level=level))
    if not projects:
        return 0

    tree = build_project_tree(root, projects)
    attach_tasks(tree)
    render_tree(tree)

    return 0


def cmd_here(args: argparse.Namespace) -> int:
    import copy

    a = copy.copy(args)
    a.level = 0
    return cmd_list(a)


def cmd_new(args: argparse.Namespace) -> int:
    title = (args.title or "").strip()
    interactive = not bool(args.non_interactive)

    base = Path.cwd()
    cwd = (base / (args.cd or ".")).resolve()

    if not title:
        if not interactive:
            print("Error: --title is required in --non-interactive mode")
            return 1

        title = input("Title: ").strip()
        if not title:
            print("Error: title is required")
            return 1

    try:
        status = Status((args.status or "active").strip().lower())
    except Exception:
        print("Error: invalid --status (allowed: active, waiting, paused, done)")
        return 1

    next_action = (args.next_action or "").strip()
    if status is not Status.DONE and not next_action:
        if not interactive:
            print("Error: --next-action is required unless status=done")
            return 1

        next_action = input("Next action: ").strip()
        if not next_action:
            print("Error: next action is required unless status=done")
            return 1

    summary = (args.summary or "").strip()
    if interactive and not summary:
        summary = input("Summary (optional): ").strip()

    links = tuple(args.link or [])
    if interactive:
        while True:
            s = input("Link (optional, blank to finish): ").strip()
            if not s:
                break
            links = links + (s,)

    req = NewTaskRequest(
        title=title,
        status=status,
        next_action=next_action,
        summary=summary,
        links=links,
    )

    try:
        task_dir = create_task(cwd, req, interactive=interactive)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    print(task_dir)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    base = Path.cwd()
    cwd = (base / (args.cd or ".")).resolve()

    try:
        task_dir, task = _choose_task(cwd, (args.task_id or "").strip() or None)
    except ValidationError as e:
        print(e)
        return 1

    color = not bool(args.no_color)
    render_task_detail(task, color=color)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cwd = (Path.cwd() / args.cd).resolve()
    task_dir, task = _choose_task(cwd, (args.task_id or "").strip() or None)

    try:
        set_status(
            task,
            task_dir,
            status=args.status,
            message=args.message,
            next_action=args.next_action,
        )
    except ValidationError as e:
        print(e)
        return 1

    return 0


def cmd_done(args: argparse.Namespace) -> int:
    import copy

    a = copy.copy(args)
    a.status = "done"
    a.next_action = None
    return cmd_status(a)


def cmd_next(args: argparse.Namespace) -> int:
    cwd = (Path.cwd() / args.cd).resolve()
    task_dir, task = _choose_task(cwd, (args.task_id or "").strip() or None)

    try:
        set_next_action(
            task,
            task_dir,
            next_action=args.next_action,
            message=args.message,
        )
    except ValidationError as e:
        print(e)
        return 1

    return 0


def cmd_touch(args: argparse.Namespace) -> int:
    cwd = (Path.cwd() / args.cd).resolve()
    task_dir, task = _choose_task(cwd, (args.task_id or "").strip() or None)

    try:
        touch_task(task, task_dir, message=args.message)
    except ValidationError as e:
        print(e)
        return 1

    return 0


# ---------------------------------------------------------------------
# Task selection helpers
# ---------------------------------------------------------------------

def _select_task_id(items: list[tuple[str, str]]) -> str:
    """
    items: list of (task_id, label)
    Returns selected task_id or empty string if cancelled.
    """
    if not items:
        return ""

    if len(items) == 1:
        return items[0][0]

    if shutil.which("fzf"):
        text = "\n".join([f"{tid}\t{label}" for tid, label in items]) + "\n"
        p = subprocess.run(
            ["fzf", "--with-nth=2..", "--delimiter=\t"],
            input=text,
            text=True,
            capture_output=True,
        )
        if p.returncode != 0:
            return ""
        line = (p.stdout or "").strip()
        if not line:
            return ""
        return line.split("\t", 1)[0].strip()

    for i, (tid, label) in enumerate(items, start=1):
        print(f"{i}) {label} [{tid}]")

    s = input("Select task number (blank to cancel): ").strip()
    if not s:
        return ""

    try:
        n = int(s)
    except ValueError:
        return ""

    if n < 1 or n > len(items):
        return ""

    return items[n - 1][0]


def _resolve_task_dir(cwd: Path, task_id: str) -> Path:
    task_dir = cwd / ".tasks" / task_id
    if not task_dir.is_dir():
        raise ValidationError(f"Task not found: {task_id}")
    return task_dir


def _choose_task(cwd: Path, task_id: str | None) -> tuple[Path, Task]:
    """
    Resolve a task in cwd/.tasks and return (task_dir, parsed_task).

    Rules:
    - If task_id is provided: resolve directly, then parse (strict).
    - If task_id is not provided: build an index of valid tasks and let the user choose.
    - Invalid tasks are ignored for interactive selection.
    """
    tasks_dir = cwd / ".tasks"
    if not tasks_dir.is_dir():
        raise ValidationError(f"No .tasks found in: {cwd}")

    if task_id:
        task_dir = _resolve_task_dir(cwd, task_id)
        task = parse_task(task_dir, expected_task_id=task_id)
        return task_dir, task

    items: list[tuple[str, str]] = []
    parsed: dict[str, Task] = {}

    for p in tasks_dir.iterdir():
        if not p.is_dir():
            continue

        tid = p.name
        try:
            task = parse_task(p, expected_task_id=tid)
        except Exception:
            continue

        parsed[tid] = task
        items.append((tid, f"{task.title} ({task.status.value})"))

    if not items:
        raise ValidationError("No tasks found")

    items.sort(key=lambda x: x[1].lower())

    chosen = _select_task_id(items)
    if not chosen:
        raise ValidationError("Cancelled")

    return _resolve_task_dir(cwd, chosen), parsed[chosen]


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2

    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
