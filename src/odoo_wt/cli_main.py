import sys
import os
import shutil
from importlib.metadata import version, PackageNotFoundError

try:
    VERSION = version("odoo-wt")
except PackageNotFoundError:
    VERSION = "dev"

from .app_config import config_mgr
from .system_discovery import discover_system_data, decompose_branch
from .setup_wizard import WizardApp
from .main_tui import OdooWtApp

def show_help():
    print(f"Odoo Worktree Assistant (odoo-wt) v{VERSION}")
    print("\nA professional TUI-driven Git worktree manager for Odoo developers.")
    print("\nUsage:")
    print("  odoo-wt                  Launch the interactive TUI (Recommended)")
    print("  odoo-wt <branch-name>    Open TUI with a specific branch name pre-filled")
    print("  odoo-wt --create         Force start in the 'Creation' tab")
    print("  odoo-wt --manage         Force start in the 'Existing / Removal' tab")
    print("  odoo-wt --no-magic       Disable automatic 'Magic Fix' for this session")
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
    
    if not config_mgr.config_file.exists():
        app = WizardApp()
        config = app.run()
        if not config:
            return
    else:
        config = config_mgr.load()

    if forced_tab:
        config["default_tab"] = forced_tab

    if "--no-magic" in sys.argv:
        config["auto_magic_fix"] = False
        sys.argv.remove("--no-magic")

    # CLI direct creation mode
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        branch_name = sys.argv[1]
        
        v_list, s_list, _ = discover_system_data(
            config["wt_root"], 
            config["suffix"], 
            config.get("known_versions", []), 
            config.get("known_suffixes", [])
        )
        
        remote, v, d, s = decompose_branch(branch_name, v_list, s_list)

        data = {
            "action": "create",
            "version": v,
            "desc": d,
            "suffix": s
        }

        from textual.app import App
        from .custom_screens import DeployScreen

        class FastModeApp(App):
            CSS_PATH = "stylesheet.tcss"
            def on_mount(self):
                self.push_screen(DeployScreen(data, config))

        app = FastModeApp()
        data = app.run()
    else:
        v_list, s_list, worktrees = discover_system_data(
            config["wt_root"], 
            config["suffix"], 
            config.get("known_versions", []), 
            config.get("known_suffixes", [])
        )
        app = OdooWtApp(config, v_list, s_list, worktrees, VERSION)
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
