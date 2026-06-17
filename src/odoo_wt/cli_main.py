import sys
import os
import shutil
from importlib.metadata import version, PackageNotFoundError

try:
    VERSION = version("odoo-wt")
except PackageNotFoundError:
    VERSION = "dev"

from .app_config import config_mgr
from .system_discovery import discover_system_data, decompose_branch, is_base_branch
from .setup_wizard import WizardApp
from .main_tui import OdooWtApp

def show_help():
    print(f"Odoo Worktree Assistant (odoo-wt) v{VERSION}")
    print("\nA professional TUI-driven Git worktree manager for Odoo developers.")
    print("\nUsage:")
    print("  odoo-wt                  Launch the interactive TUI (Recommended)")
    print("  odoo-wt status           Print the worktree and Runbot status table directly")
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

def get_edit_distance(s1: str, s2: str) -> int:
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2+1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]

def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        show_help()
        sys.exit(0)
    
    if "--version" in sys.argv:
        print(f"odoo-wt v{VERSION}")
        sys.exit(0)

    # Command-line Status mode
    if "--status" in sys.argv or "status" in sys.argv:
        if "--status" in sys.argv: sys.argv.remove("--status")
        if "status" in sys.argv: sys.argv.remove("status")
        
        check_dependencies()
        if not config_mgr.config_file.exists():
            print("❌ Error: No configuration file found. Please run odoo-wt once to initialize settings.")
            sys.exit(1)
            
        config = config_mgr.load()
        print_cli_status(config)
        sys.exit(0)

    # Check for status command typos (like 'statu', 'stats', 'stat')
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        arg = sys.argv[1]
        if arg != "status" and arg != "create" and get_edit_distance(arg, "status") <= 2:
            check_dependencies()
            if not config_mgr.config_file.exists():
                print(f"❌ Error: Unknown command '{arg}'. Please run odoo-wt once to initialize settings.")
                sys.exit(1)
                
            config = config_mgr.load()
            
            # If interactive TTY, offer prompt
            if sys.stdout.isatty():
                try:
                    ans = input(f"❌ Unknown command '{arg}'. Did you mean 'status'? [y/N]: ").strip().lower()
                    if ans in ("y", "yes"):
                        print_cli_status(config)
                        sys.exit(0)
                    else:
                        print("Aborted.")
                        sys.exit(1)
                except (KeyboardInterrupt, EOFError):
                    print("\nAborted.")
                    sys.exit(1)
            else:
                print(f"❌ Error: Unknown command '{arg}'. Did you mean 'status'?")
                sys.exit(1)

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

def print_cli_status(config):
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .runbot_client import query_branch_status
    import datetime
    
    console = Console()
    
    # 1. Discover system worktrees
    _, _, worktrees = discover_system_data(
        config["wt_root"], 
        config["suffix"],
        known_versions=config.get("known_versions", []),
        known_suffixes=config.get("known_suffixes", [])
    )
    
    if not worktrees:
        console.print("[yellow]No active worktrees found in your root path.[/yellow]")
        return
        
    def relative_time(ts_str: str) -> str:
        if not ts_str: return ""
        try:
            dt = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            now = datetime.datetime.utcnow()
            delta = now - dt
            total_seconds = int(delta.total_seconds())
            if total_seconds < 0: total_seconds = 0
            if total_seconds < 60: return "just now"
            elif total_seconds < 3600: return f"{total_seconds // 60}m ago"
            elif total_seconds < 86400: return f"{total_seconds // 3600}h ago"
            else: return f"{total_seconds // 86400}d ago"
        except Exception: return ""
         
    # 1. Initialize all base branches immediately (doesn't need network CI polling)
    results = {}
    resolved_urls = {}
    resolved_odoo_prs = {}
    resolved_ent_prs = {}
    
    for wt in worktrees:
        if is_base_branch(wt["name"]):
            results[wt["name"]] = "⚪ Base Branch"
            resolved_urls[wt["name"]] = "https://runbot.odoo.com/runbot"
            
    # Filter out base branches for concurrent checks
    to_check = [wt for wt in worktrees if not is_base_branch(wt["name"])]
    
    if to_check:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
            task_id = progress.add_task("[cyan]Polling Runbot CI...", total=len(to_check))
            
            with ThreadPoolExecutor(max_workers=6) as executor:
                future_to_wt = {
                    executor.submit(query_branch_status, wt["name"]): wt 
                    for wt in to_check
                }
                
                for future in as_completed(future_to_wt):
                    wt = future_to_wt[future]
                    branch_name = wt["name"]
                    
                    status = "⚪ No batch"
                    link_url = f"https://runbot.odoo.com/runbot?search={branch_name}"
                    
                    try:
                        res = future.result()
                        if res:
                            batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr = res
                            link_url = batch_url
                            resolved_urls[branch_name] = batch_url
                            
                            if odoo_pr:
                                resolved_odoo_prs[branch_name] = odoo_pr
                            if enterprise_pr:
                                resolved_ent_prs[branch_name] = enterprise_pr
                            
                            time_suffix = f" {relative_time(ts_str)}" if ts_str else ""
                            warn_str = f" [yellow]{warning}w[/yellow]" if warning > 0 else " 0w"
                            fail_str = f" [red]{failed}f[/red]" if failed > 0 else " 0f"
                            
                            if running > 0:
                                status = f"⏳ Running{warn_str}{fail_str}{time_suffix}"
                            elif failed > 0:
                                status = f"🔴 Failed{fail_str}{time_suffix}"
                            elif warning > 0:
                                status = f"🟡 Warning{warn_str}{time_suffix}"
                            else:
                                status = f"🟢 Passed{time_suffix}"
                        else:
                            status = "⚪ No batch"
                    except Exception:
                        status = "⚠️ Error"
                        
                    results[branch_name] = status
                    progress.advance(task_id)
                     
    # 2. Render gorgeous Rich Table
    table = Table(title=f"Odoo Worktree Status (v{VERSION})", title_style="bold cyan", header_style="bold magenta", box=None)
    table.add_column("Branch Name", style="cyan")
    table.add_column("Runbot Status")
    table.add_column("Link")
    
    def version_sort_key(wt):
        v = wt["version"] or ""
        try:
            num_part = v.replace("saas-", "")
            parts = num_part.split(".")
            major = int(parts[0]) if parts else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            is_saas = 1 if "saas-" in v else 0
            return (major, minor, is_saas)
        except Exception:
            return (0, 0, 0)
             
    sorted_wts = sorted(worktrees, key=lambda x: (version_sort_key(x), x["name"]), reverse=True)
    
    for wt in sorted_wts:
        name = wt["name"]
        status = results.get(name, "⚪ No batch")
        
        if is_base_branch(name):
            link_str = "[link=https://runbot.odoo.com/runbot]Board[/link]"
        elif name in resolved_urls:
            batch_url = resolved_urls[name]
            parts = [f"[link={batch_url}]CI[/link]"]
            
            odoo_pr = resolved_odoo_prs.get(name)
            if odoo_pr:
                parts.append(f"[link={odoo_pr}]Com[/link]")
                
            ent_pr = resolved_ent_prs.get(name)
            if ent_pr:
                parts.append(f"[link={ent_pr}]Ent[/link]")
                
            link_str = "  ".join(parts)
        else:
            link_str = f"[link=https://runbot.odoo.com/runbot?search={name}]Search[/link]"
            
        table.add_row(name, status, link_str)
         
    console.print(table)

if __name__ == "__main__":
    main()
