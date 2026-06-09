# Odoo Worktree Assistant (odoo-wt)

A professional, modern TUI-driven Git worktree manager explicitly designed for Odoo developers. Built with Python, Textual, and uv.

## The Pitch

I work with Odoo using Git Worktrees every single day. Every time I start a new feature or need to check out a colleague's code, I find myself doing the same tedious dance: creating a new folder, fetching branches from the remote, adding the community worktree, adding the enterprise worktree, and then setting up the Python environment.

If you also work like this, I built this tool for you. It handles that entire handshake between Git and your virtual environments in seconds through a fast Terminal UI, so you can just focus on the code.

### The Structure

The tool creates and manages a standardized folder structure that looks like this:

```text
~/repos/Odoo/wt/                    <-- Your Worktree Root
│
├── master/                         <-- Your base repositories
│   ├── odoo/                       (Main clone of community)
│   └── enterprise/                 (Main clone of enterprise)
│
├── 17.0-fix-account-bug-pian/      <-- A new task
│   ├── .venv/                      <-- Auto-linked shared UV environment
│   ├── odoo/                       <-- Checked out to the task branch
│   └── enterprise/                 <-- Checked out to the task branch
│
└── saas-17.4-feature-xyz-mate/    <-- Checking a colleague's code
    ├── .venv/
    ├── odoo/
    └── enterprise/
```

### Key Features

- **Modern TUI:** A sleek, reactive All-in-One form built with Textual.
- **Smart Branching:** Follows the Odoo standard: `[VERSION]-[description]-[SUFFIX]`.
- **Magic Fix ✨:** Intelligently parses pasted branch names (e.g., `odoo-dev:master-fix-bug-pian`) and automatically cleans up dropdowns and inputs.
- **Dual Repo Support:** Simultaneously creates worktrees for both `odoo` (Community) and `enterprise`.
- **Automated UV Environments:**
    - Centralizes environments in `~/.envs/[VERSION]`.
    - Automatically runs `uv venv` and `uv pip install` if the environment is missing.
    - Instantly symlinks `.venv` into your new worktree folder for automatic VS Code detection.
- **Advanced Management:** 
    - Search, Open, and Delete worktrees directly from the TUI.
    - Protected `master` worktrees and triple-confirmation "nuke" safety for deletions.
- **Proactive Status Checks:** Parallelized checks across local and remote repositories to detect existing branches before creation.

## Installation

### 1. From PyPI (Recommended)
`odoo-wt` is officially published on PyPI. The easiest way to install it globally is using `uv tool`:

```bash
uv tool install odoo-wt
```

To update to the latest release:
```bash
uv tool upgrade odoo-wt
```

### 2. From Source (For Contributors)
If you want to run the latest unreleased version or contribute to the project:

```bash
git clone https://github.com/nd-dew/odoo-wt.git
cd odoo-wt
uv tool install . --force
```

*(Tip: For active development, use `uv tool install --editable . --force` to see code changes instantly without re-installing.)*

## Configuration

The tool saves its configuration to `~/.config/odoo-wt.json`. You can edit paths directly in the Settings tab within the application.

- wt_root: Where your worktree folders live (e.g., ~/repos/Odoo/wt).
- env_root: Where your centralized global Python environments are stored (e.g., ~/.envs).
- suffix: Your default developer quadrigram (e.g., pian).

## Usage

### Interactive Mode
Simply run the command with no arguments:
```bash
odoo-wt
```
- Use Tab to switch between Version, Description, and Suffix.
- Type custom... in any dropdown to reveal a custom input field.
- Press Ctrl+S to instantly submit and deploy.
- Press Esc to cancel and exit.

### Fast Mode
If you already have a full branch name ready:
```bash
odoo-wt 17.0-fix-account-bug-pian
```

## Development Guide

### Running Tests
We use `pytest` for our modern test suite. It covers core logic, file management, and UI rendering via Textual's headless pilot.

```bash
# Run all tests
uv run pytest

# Run tests with detailed output
uv run pytest -v
```

### Applying Changes
If you modify the source code, make sure to bump the version in `pyproject.toml` so that `uv` registers the newly compiled files. Then, apply your changes to your local installation using:
```bash
uv tool install . --force
```

## Known Limitations

- Clipboard Interactions (Copy/Paste): Because odoo-wt uses mouse-capture to enable clickable buttons and scrollbars in the terminal, your terminal emulator's native click-to-highlight features are disabled by default.
    - To copy text manually: Hold the Shift key while clicking and dragging over the text to bypass the app and use your terminal's native selection, then use Ctrl+Shift+C.
    - To paste text: Sometimes native terminal paste (Ctrl+Shift+V or middle-click) events are intercepted unreliably by the underlying framework. If pasting into an input field fails, you may need to type the branch name manually.

## TODO

- **Config Reset Bug:** The `wt_root` sometimes resets itself to `/tmp`. We need to investigate why this field is being overwritten in the configuration. solved no? it was tests?
- **Action Selection:** Add flags to directly trigger 'terminal' or 'vscode' actions from the command line after deployment.
- **Improved Logging:** Add more granular log levels for troubleshooting.
- add cli option to --list existing wt
- opening the directory in terminal is very slow (like 10s)


## Development

To apply changes made to the source:
```bash
uv tool install . --force
```

## License
MIT
