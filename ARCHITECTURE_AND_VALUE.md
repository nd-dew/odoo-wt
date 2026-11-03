# Odoo Worktree Assistant (odoo-wt)
## Engineering Architecture, Specifications, and Technical Report

---

## 1. Overview & Core Specifications

`odoo-wt` is a terminal-based utility designed to manage Git worktrees across multiple repositories in Odoo development environments. 

### Core Tech Stack:
* **Language**: Python >= 3.11
* **TUI Library**: Textual (event-loop driven terminal library)
* **CLI Library**: Rich (terminal rendering)
* **Package/Env Manager**: Astral `uv`
* **Test Suite**: Pytest with Pytest-Asyncio (81 unit/integration tests)
* **Configuration**: `~/.config/odoo-wt.json`
* **Logging**: `~/.config/odoo-wt-logs.jsonl`

---

## 2. The Odoo Workspace Problem Space

Development inside Odoo SA requires coordinating several operational variables across multiple filesystem locations.

### A. Multi-Repository Structure
The codebase consists of three separate Git repositories:
1. **`odoo` (Community)**: Open-source core.
2. **`enterprise` (Enterprise)**: Commercial extension modules.
3. **`upgrade` (Upgrade)**: Database migration scripts.

When a developer switches to or creates a feature branch for a specific Odoo version (e.g., `saas-19.4`), they must coordinate matching checkouts across these three directories. Performing these checkouts manually requires navigating to each directory, verifying local state, and executing multiple Git commands.

### B. Conflicting Dependencies
Odoo release versions (e.g., `15.0`, `17.0`, `saas-19.4`, `master`) run on different Python versions and require specific, sometimes conflicting, pip dependencies. Developers must maintain distinct virtual environments per version to prevent dependency pollution.

### C. Workspace Navigation
Developers often maintain multiple local feature branches concurrently. To avoid stashing changes or corrupting local build artifacts, Git worktrees are used to create dedicated directories per branch. This increases the number of local directories on disk, requiring a fast navigation and search mechanism.

### D. Multi-Platform Diagnostics
Before starting, developers must verify system dependencies (Git installation, SSH keys, GitHub CLI presence, Odoo base repository clones). A failure in any of these components blocks subsequent branch deployments.

---

## 3. Systems Architecture & Engineering Implementations

```
                  ┌──────────────────────────────────────────────┐
                  │                 CLI Entrypoint               │
                  │              (odoo_wt/cli_main.py)           │
                  └──────┬──────────────────────────────┬────────┘
                         │                              │
        [Pre-flight Checks & Wizard]             [Direct Switching/Open]
                         │                              │
                         ▼                              ▼
            ┌──────────────────────────┐    ┌───────────────────────────┐
            │   Textual UI Launcher    │    │  Terminal Sub-Shell Spawner│
            │  (odoo_wt/main_tui.py)   │    │      (os.execv Spawning)  │
            └────────────┬─────────────┘    └─────────────┬─────────────┘
                         │                                │
            [Async Background Workers]           [Git Worktree Mounting]
                         ▼                                ▼
            ┌──────────────────────────┐    ┌───────────────────────────┐
            │ Concurrent Runbot Poller │    │     Deployment Engine     │
            │ (odoo_wt/runbot_client.py)│   │(odoo_wt/deployment_engine)│
            └──────────────────────────┘    └───────────────────────────┘
```

### A. Asynchronous Event Loop
The TUI uses Textual's async event loop. Filesystem I/O and network operations (Runbot CI/CD and GitHub API requests) are run in background coroutines or thread pools to keep the interface responsive during long-running operations.

### B. Progressive Matcher (Smart Switcher)
When a user executes `odoo-wt <branch_query>`, the application queries local worktrees using a three-tier matcher:
1. **Tier 1 (Contiguous Substring)**: Direct substring check of query in worktree names.
2. **Tier 2 (Fuzzy Multi-Term)**: Splits query into space-separated terms and matches them regardless of order.
3. **Tier 3 (Levenshtein Distance)**: Calculates edit distance to identify matching worktrees or correct command typos (e.g., `lis` -> `list`).

### C. Terminal Sub-Shell Spawning
Python processes cannot alter the working directory of the parent shell that invoked them. To teleport the terminal to a selected worktree, `odoo-wt` replaces the current Python process with a new sub-shell (resolved via `$SHELL`) initialized inside the target directory using:
```python
os.execv(shell, [shell])
```

### D. Reusable Central Virtual Environments
To optimize disk usage, `odoo-wt` maintains centralized Python virtual environments grouped by Odoo version (e.g., in `~/.envs/`). When deploying a worktree, `odoo-wt` creates a symbolic link from the worktree's `.venv` folder to the centralized version-specific virtual environment. This prevents redownloading and reinstalling packages for every single worktree.

### E. Robust Git Fetch Refspecs
Under limited, single-branch, or shallow Git configurations, explicit fetches can fail to write local remote-tracking branches. To resolve this, the deployment engine maps remote branches directly to local tracking references during fetch:
```bash
git fetch remote branch:refs/remotes/remote/branch --force
```
This guarantees that `refs/remotes/remote/branch` is written to disk, preventing subsequent `invalid reference` errors in `git worktree add`.

### F. Symmetrical Terminal Teardown & Snappy Exit
Due to background threads running blocking network requests (Runbot status checks), standard Python/asyncio cleanups can hang on exit. `odoo-wt` uses a two-step termination approach:
1. **Graceful UI Teardown**: Calling Textual's `self.exit()` ensures widgets are released and terminal cooked mode, echo, and cursor are restored.
2. **Forceful OS Termination**: After the terminal is restored, the CLI layer immediately executes a low-level `os._exit(0)` to forcefully terminate the process and all hanging thread pools.

---

## 4. Operational Features

* **Welcome Setup Wizard**: Guides the user through initial configuration (discovering roots, virtualenv paths, and default suffix).
* **On-the-Fly Path Validation**: Validates paths as the user types. If the directory doesn't exist, it displays an info notice (`📁 Path does not exist (will be created automatically)`) and creates it on finish. If base clones are missing under `master/`, it prints explicit `git clone` commands pre-filled with the exact path.
* **Smart Paste (Magic Fix)**: Decomposes pasted GitHub branch handles (e.g. `odoo-dev:saas-19.4-ai-preserve_list-bso`) into version, description, and suffix, and maps them to a clean local name (`saas-19.4-ai-preserve_list-bso`).
* **CI/CD Runbot & Reviews Integration**: Queries the Runbot API and GitHub PR reviews concurrently. It displays batch build statuses (⚪ Running, 🟢 Passed, 🔴 Failed), logs specific failing test methods, and parses inline PR comments.

---

## 5. Professional & Quantitative Value

* **Friction Reduction**: Reduces matching repository checkout, virtualenv activation, and configuration setup from several manual steps to a single command.
* **Multi-Repo Synchronization**: Enforces branch name consistency across Community, Enterprise, and Upgrade repositories during checkout.
* **Software Engineering Standards**: Verified by 81 automated tests covering UI mounting, CLI argument parsers, async network polling, and error handling.
