import sys
import os
from .app_config import load_config, CONFIG_FILE
from .system_discovery import discover_system_data
from .setup_wizard import WizardApp
from .main_tui import OdooWtApp

def main():
    if not CONFIG_FILE.exists():
        app = WizardApp()
        config = app.run()
        if not config:
            return
    else:
        config = load_config()

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
        # We don't have an easy way to auto-start deployment from CLI yet, 
        # let's just open the app for now. 
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
            os.system(f"code {target}")

if __name__ == "__main__":
    main()
