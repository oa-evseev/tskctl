# tskctl

`tskctl` is a local, strict, tree-based CLI tool for managing tasks as case-files inside project directories.

The project is at a very early stage.  
At the moment this repository contains **concept and specification only**.

---

## Core idea

- Tasks are **local** and live next to the project they belong to.
- Each task is a **case-file**: history + current state + next action.
- No SaaS, no background services, no central database.
- Everything is stored in the filesystem.
- Strict format, explicit lifecycle, fail fast on errors.

---

## Design principles

- **KISS** — keep the system simple and predictable.
- **CLI-first** — terminal is the primary interface.
- **Read-only by default** — global scans are safe; modifications are local.
- **Strict validation** — broken state should fail early and loudly.
- **Local ownership** — task data is not meant to be committed or shared.

---

## Current status

- Specification written
- No implementation yet
- APIs, commands and file formats may change

This repository is not usable as a tool yet.

---

## License

MIT

