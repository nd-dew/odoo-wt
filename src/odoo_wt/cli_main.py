import sys
import os
import shutil
from .app_config import load_config, CONFIG_FILE
from .system_discovery import discover_system_data
from .setup_wizard import WizardApp
from .main_tui import OdooWtApp

VERSION = "1.1.0"

def show_help():
    print(f"Odoo Worktree Assistant (odoo-wt) v{VERSION}")
    print("\nA professional TUI-driven Git worktree manager for Odoo developers.")
    print("\nUsage:")
    print("  odoo-wt                  Launch the interactive TUI (Recommended)")
    print("  odoo-wt <branch-name>    Open TUI with a specific branch name pre-filled")
    print("  odoo-wt --create         Force start in the 'Creation' tab")
    print("  odoo-wt --manage         Force start in the 'Existing / Removal' tab")
    print("  odoo-wt --help, -h       Show this help message")
    print("  odoo-wt --version        Show the current version")
    print("\nEnvironment Variables:")
    print("  SHELL                    Target shell when opening 'Terminal' from the app (default: /bin/bash)")
    print("\nDocumentation: https://github.com/AndrzejPietrusiak/odoo-wt")

def check_dependencies():
    missing = []
    if not shutil.which("git"):
        missing.append("git")
    if not shutil.which("uv"):
        missing.append("uv")
    
    if missing:
        print(f"❌ Error: Required dependencies not found in PATH: {', '.join(missing)}")
        print("Please install them and try again.")
        print("  - git: https://git-scm.com/")
        print("  - uv:  https://docs.astral.sh/uv/")
        sys.exit(1)

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        show_help()
        sys.exit(0)
    
    if "--version" in sys.argv:
        print(f"odoo-wt v{VERSION}")
        sys.exit(0)

    # Simple flag parsing for tab selection
    forced_tab = None
    if "--create" in sys.argv:
        forced_tab = "tab-create"
        sys.argv.remove("--create")
    elif "--manage" in sys.argv:
        forced_tab = "tab-manage"
        sys.argv.remove("--manage")

    check_dependencies()
    
    if not CONFIG_FILE.exists():
        app = WizardApp()
        config = app.run()
        if not config:
            return
    else:
        config = load_config()

    if forced_tab:
        config["default_tab"] = forced_tab

    # CLI direct creation mode
    if len(sys.argv) > 1:
        branch = sys.argv[1]
        v = branch.split("-")[0] if "-" in branch else "master"
        # We manually build the data for DeployScreen
        data = {"action": "create", "version": v, "desc": branch, "suffix": ""}
        # In CLI mode, we still need to boot OdooWtApp to push the DeployScreen
        # or we just boot a minimal app to host the DeployScreen.
        # For now, let's just launch the full app and it will handle it if we modify init.
        # But easier: just boot the app normally.
        v_list, s_list, worktrees = discover_system_data(config["wt_root"], config["suffix"])
        app = OdooWtApp(config, v_list, s_list, worktrees)
        # We don't have an easy way to auto-start deployment from CLI yet, let's just open the app for now. 
        app.run()
    else:
        v_list, s_list, worktrees = discover_system_data(config["wt_root"], config["suffix"])
        app = OdooWtApp(config, v_list, s_list, worktrees)
        data = app.run()

    # Handle deployment completion actions
    if data and isinstance(data, dict):
        action = data.get("action")
        if action == "terminal":
            target = data["path"]
            os.chdir(target)
            shell = os.environ.get("SHELL", "/bin/bash")
            os.execv(shell, [shell])
        elif action == "vscode":
            target = data["path"]
            if shutil.which("code"):
                os.system(f"code {target}")
            else:
                print("❌ VS Code ('code' command) not found in PATH.")
                print(f"Directory is ready at: {target}")

if __name__ == "__main__":
    main()
