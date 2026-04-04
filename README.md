# Odoo Worktree Assistant (`odoo-wt`)

A professional, modern TUI-driven Git worktree manager explicitly designed for Odoo developers. Built with Python, [Textual](https://textual.textualize.io/), and [uv](https://github.com/astral-sh/uv).

![Python](https://img.shields.io/badge/Language-Python-blue) ![TUI](https://img.shields.io/badge/UI-Textual-green) ![Package Manager](https://img.shields.io/badge/Manager-uv-orange)

## 🚀 Overview

`odoo-wt` streamlines the process of spinning up new Odoo development environments. It handles the complex "handshake" between Git worktrees and Python virtual environments so you can focus on code.

### Key Features

-   **Modern TUI:** A sleek, reactive "All-in-One" form built with Textual.
-   **Smart Branching:** Follows the Odoo standard: `[VERSION]-[description]-[SUFFIX]`.
-   **Dual Repo Support:** Simultaneously creates worktrees for both `odoo` (Community) and `enterprise`.
-   **Automated UV Environments:** 
    -   Centralizes environments in `~/.envs/[VERSION]`.
    -   Automatically runs `uv venv` and `uv pip install` if the environment is missing.
    -   Instantly symlinks `.venv` into your new worktree folder for automatic VS Code detection.
-   **Proactive Status Checks:** Checks `odoo-dev` and local remotes to detect if branches already exist before creation.

## 🛠️ Installation

The recommended way to install `odoo-wt` is using `uv tool`:

```bash
# From the project directory
uv tool install . --force
```

This creates an isolated environment for the tool and places an `odoo-wt` executable in your `~/.local/bin/`.

## ⚙️ Configuration

The tool saves its configuration to `~/.config/odoo-wt.json`. You can edit paths directly in the **Settings** tab within the application.

-   **`wt_root`**: Where your worktree folders live (e.g., `~/repos/Odoo/wt`).
-   **`env_root`**: Where your centralized global Python environments are stored (e.g., `~/.envs`).
-   **`suffix`**: Your default developer quadrigram (e.g., `pian`).

## 📖 Usage

### Interactive Mode (The Guide)
Simply run the command with no arguments:
```bash
odoo-wt
```
-   Use **`Tab`** to switch between Version, Description, and Suffix.
-   Type **`custom...`** in any dropdown to reveal a custom input field.
-   Press **`Ctrl+S`** to instantly submit and deploy.
-   Press **`Esc`** to cancel and exit.

### Fast Mode
If you already have a full branch name ready:
```bash
odoo-wt 17.0-fix-account-bug-pian
```

## ⚠️ Known Limitations

- **Clipboard Interactions (Copy/Paste):** Because `odoo-wt` uses mouse-capture to enable clickable buttons and scrollbars in the terminal, your terminal emulator's native click-to-highlight features are disabled by default. 
    - **To copy text manually:** Hold the `Shift` key while clicking and dragging over the text to bypass the app and use your terminal's native selection, then use `Ctrl+Shift+C`.
    - **To paste text:** Sometimes native terminal paste (`Ctrl+Shift+V` or middle-click) events are intercepted unreliably by the underlying framework. If pasting into an input field fails, you may need to type the branch name manually.

## 📝 Development

The source code is located at `/home/odoo/repos/Scripts/odoo-wt/`.

To apply changes made to the source:
```bash
uv tool install . --force
```

## 📜 License
MIT
