# tskctl

`tskctl` is a local, strict, tree-based CLI tool for managing tasks as **case directories**
inside project trees.

Each task is stored as a small, explicit filesystem structure and manipulated
via a predictable command-line interface.

This project is in early active development but already usable.

---

## Core idea

- Tasks are **local** and live next to the project they belong to.
- Each task is a **case**: current state + history + next action.
- No SaaS, no background services, no central database.
- Everything is stored in plain files and directories.
- Strict structure and validation; fail fast on inconsistencies.

---

## Task model

Each task is a directory under `.tasks/`:

```
.tasks/
2025-12-25__003__my_task/
task.yml # required: core metadata
task.log # required: append-only log
summary.md # optional: free-form description
```

### `task.yml`
Contains:
- task id
- title
- status
- created / last_touch dates
- next_action
- links
- format version

### `task.log`
Append-only, one entry per line:
```
YYYY-MM-DD: [type] comment
```

The log is treated as authoritative history.

### `summary.md`
Optional human-readable description.
Not parsed semantically.

---

## Design principles

- **KISS** — predictable behaviour over cleverness.
- **CLI-first** — terminal is the primary interface.
- **Filesystem as source of truth** — no hidden state.
- **Strict validation** — broken state is an error, not a warning.
- **Local ownership** — task data is local by design.

---

## Current status

- Core engine implemented (parse / ops / actions / validation)
- CLI commands implemented (`new`, `list`, `show`, `status`, `done`, `next`, `touch`, `validate`)
- Stable on-disk layout (v2)
- Internal APIs may still evolve

This is an **early usable release**.

Versioning follows semantic intent, not stability guarantees.

---

## Versioning

- `0.x.y` — active development, formats mostly stable, APIs may evolve
- `0.1.0` — first usable public version

---

## License

MIT
