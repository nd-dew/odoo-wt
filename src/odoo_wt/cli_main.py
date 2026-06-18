import sys
import os
import shutil
import subprocess
from pathlib import Path
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
    print("  odoo-wt                      Launch the interactive TUI (Recommended)")
    print("  odoo-wt status               Print the worktree and Runbot status table directly")
    print("  odoo-wt //runbot             Fast, dash-free alias to print status table directly")
    print("  odoo-wt list                 Simply list existing worktree names, one per line (no formatting)")
    print("  odoo-wt <branch>             Smart Switcher/Creator: opens TUI if new, opens shell if existing")
    print("  odoo-wt create <branch>      Explicitly open TUI pre-filled in 'Creation' tab")
    print("\nOptions & Actions:")
    print("  -o, --open <branch>          Directly open terminal shell in an existing worktree")
    print("  -c, --code <branch>          Directly open VS Code in an existing worktree")
    print("  -d, --delete <branch>        Directly delete an existing worktree with CLI prompt")
    print("  --no-magic                   Disable automatic 'Magic Fix' branch decomposition")
    print("  --config-path                Print the active odoo-wt.json configuration path")
    print("  --log-path                   Print the active odoo-wt-logs.jsonl path")
    print("  --create                     Force start TUI in the 'Creation' tab")
    print("  --manage                     Force start TUI in the 'Existing / Removal' tab")
    print("  -h, --help                   Show this help message")
    print("  -v, --version                Show the current version")
    print("\nEnvironment Variables:")
    print("  SHELL                    Target shell when opening 'Terminal' from the app (default: /bin/bash)")
    print("\nDocumentation: https://github.com/nd-dew/odoo-wt")

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

    # Initialize configuration first (required for all CLI commands)
    if not config_mgr.config_file.exists():
        check_dependencies()
        app = WizardApp()
        config = app.run()
        if not config:
            sys.exit(1)
    else:
        config = config_mgr.load()

    # Simple list command (one branch name per line, no formatting, no titles, sorted by recency)
    if "list" in sys.argv:
        check_dependencies()
        _, _, worktrees = discover_system_data(
            config["wt_root"], 
            config["suffix"],
            known_versions=config.get("known_versions", []),
            known_suffixes=config.get("known_suffixes", [])
        )
        
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
                
        def recency_sort_key(wt_dict):
            path_str = wt_dict["path"]
            ts = config.get("worktree_recency", {}).get(path_str, "")
            return (ts, version_sort_key(wt_dict), wt_dict["name"])
            
        sorted_wts = sorted(worktrees, key=recency_sort_key, reverse=True)
        for wt in sorted_wts:
            print(wt["name"])
        sys.exit(0)

    # Command-line Status mode
    if "--status" in sys.argv or "status" in sys.argv:
        if "--status" in sys.argv: sys.argv.remove("--status")
        if "status" in sys.argv: sys.argv.remove("status")
        
        check_dependencies()
        print_cli_status(config)
        sys.exit(0)

    # Check for status command typos (like 'statu', 'stats', 'stat')
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        arg = sys.argv[1]
        if arg not in ("status", "create", "wizard", "//runbot", "list") and get_edit_distance(arg, "status") <= 2:
            check_dependencies()
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

    # Utility metadata commands
    if "--config-path" in sys.argv:
        print(config_mgr.config_file.absolute())
        sys.exit(0)
        
    if "--log-path" in sys.argv:
        print(config_mgr.log_file.absolute())
        sys.exit(0)

    # Wizard command
    if "wizard" in sys.argv:
        check_dependencies()
        app = WizardApp()
        config = app.run()
        sys.exit(0)

    # Command-line Status mode (supporting status, --status, and //runbot)
    if "--status" in sys.argv or "status" in sys.argv or "//runbot" in sys.argv:
        if "--status" in sys.argv: sys.argv.remove("--status")
        if "status" in sys.argv: sys.argv.remove("status")
        if "//runbot" in sys.argv: sys.argv.remove("//runbot")
        
        check_dependencies()
        print_cli_status(config)
        sys.exit(0)

    # Check for status command typos (like 'statu', 'stats', 'stat')
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        arg = sys.argv[1]
        # Skip checking recognized subcommands
        if arg not in ("status", "create", "wizard", "//runbot"):
            if get_edit_distance(arg, "status") <= 2:
                check_dependencies()
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

    # Explicit direct action flags
    # -o, --open <branch>
    open_branch = None
    if "--open" in sys.argv or "-o" in sys.argv:
        idx = sys.argv.index("--open") if "--open" in sys.argv else sys.argv.index("-o")
        if idx + 1 < len(sys.argv):
            open_branch = sys.argv[idx + 1]
            sys.argv.pop(idx + 1)
        sys.argv.pop(idx)

    # -c, --code <branch>
    code_branch = None
    if "--code" in sys.argv or "-c" in sys.argv:
        idx = sys.argv.index("--code") if "--code" in sys.argv else sys.argv.index("-c")
        if idx + 1 < len(sys.argv):
            code_branch = sys.argv[idx + 1]
            sys.argv.pop(idx + 1)
        sys.argv.pop(idx)

    # -d, --delete <branch>
    delete_branch = None
    if "--delete" in sys.argv or "-d" in sys.argv:
        idx = sys.argv.index("--delete") if "--delete" in sys.argv else sys.argv.index("-d")
        if idx + 1 < len(sys.argv):
            delete_branch = sys.argv[idx + 1]
            sys.argv.pop(idx + 1)
        sys.argv.pop(idx)

    # --no-magic flag
    no_magic = False
    if "--no-magic" in sys.argv:
        no_magic = True
        sys.argv.remove("--no-magic")

    # Simple flag parsing for tab selection
    forced_tab = None
    if "--create" in sys.argv:
        forced_tab = "tab-create"
        sys.argv.remove("--create")
    elif "--manage" in sys.argv:
        forced_tab = "tab-manage"
        sys.argv.remove("--manage")

    check_dependencies()

    # Discover local worktrees to check for existing switcher/actions
    v_list, s_list, worktrees = discover_system_data(
        config["wt_root"], 
        config["suffix"], 
        config.get("known_versions", []), 
        config.get("known_suffixes", [])
    )

    # Handle direct commands (open, code, delete)
    if open_branch:
        match = next((w for w in worktrees if w["name"] == open_branch), None)
        if match:
            if "worktree_recency" not in config: config["worktree_recency"] = {}
            import datetime
            config["worktree_recency"][match["path"]] = datetime.datetime.utcnow().isoformat()
            config_mgr.save(config)
            
            os.chdir(match["path"])
            shell = os.environ.get("SHELL", "/bin/bash")
            os.execv(shell, [shell])
        else:
            print(f"❌ Error: Worktree '{open_branch}' does not exist locally.")
            sys.exit(1)

    if code_branch:
        match = next((w for w in worktrees if w["name"] == code_branch), None)
        if match:
            if "worktree_recency" not in config: config["worktree_recency"] = {}
            import datetime
            config["worktree_recency"][match["path"]] = datetime.datetime.utcnow().isoformat()
            config_mgr.save(config)
            
            if shutil.which("code"):
                os.system(f"code {match['path']}")
                sys.exit(0)
            else:
                print("❌ VS Code ('code' command) not found in PATH.")
                sys.exit(1)
        else:
            print(f"❌ Error: Worktree '{code_branch}' does not exist locally.")
            sys.exit(1)

    if delete_branch:
        match = next((w for w in worktrees if w["name"] == delete_branch), None)
        if match:
            ans = "n"
            if sys.stdout.isatty():
                try:
                    ans = input(f"⚠️ Are you sure you want to delete worktree '{delete_branch}'? [y/N]: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print("\nAborted.")
                    sys.exit(1)
            else:
                ans = "y"
                
            if ans in ("y", "yes"):
                print(f"🧹 Deleting worktree '{delete_branch}'...")
                target_path = match["path"]
                subprocess.run(["git", "worktree", "remove", "--force", "odoo"], cwd=target_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if (Path(target_path) / "enterprise").exists():
                    subprocess.run(["git", "worktree", "remove", "--force", "enterprise"], cwd=target_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                subprocess.run(["git", "worktree", "prune"], cwd=os.path.expanduser(config["wt_root"]), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    shutil.rmtree(target_path)
                except Exception:
                    pass
                print("✨ Deleted successfully.")
                sys.exit(0)
            else:
                print("Aborted.")
                sys.exit(0)
        else:
            print(f"❌ Error: Worktree '{delete_branch}' does not exist locally.")
            sys.exit(1)

    # Handle explicit 'create <branch>' command or Smart Switcher/Creator odoo-wt <branch>
    explicit_create = False
    branch_arg = None

    if len(sys.argv) > 1 and sys.argv[1] == "create":
        explicit_create = True
        if len(sys.argv) > 2:
            branch_arg = sys.argv[2]
            sys.argv.pop(2)
        sys.argv.pop(1)
    elif len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        branch_arg = sys.argv[1]
        sys.argv.pop(1)

    if branch_arg:
        # Determine fuzzy matched worktrees (prioritize switcher over creator)
        matched_wts = []
        if not explicit_create:
            query = branch_arg.strip().lower()
            for wt in worktrees:
                name = wt["name"].lower()
                # 1. Direct substring match!
                if query in name:
                    matched_wts.append(wt)
                    continue
                # 2. Token-based Levenshtein match (distance <= 2)!
                tokens = name.replace("-", " ").replace("_", " ").split()
                if any(get_edit_distance(query, tok) <= 2 for tok in tokens):
                    matched_wts.append(wt)
                    
        # Let's handle the decision routing:
        matched_wt = None
        if len(matched_wts) == 1:
            matched_wt = matched_wts[0]
        elif len(matched_wts) > 1:
            from rich.console import Console
            console = Console()
            console.print(f"🔍 Multiple worktrees matched '[cyan]{branch_arg}[/cyan]':")
            for idx, wt in enumerate(matched_wts, 1):
                console.print(f"  [[green]{idx}[/green]] {wt['name']}")
                
            print()
            try:
                ans = input(f"Select a worktree to switch to [1-{len(matched_wts)}, or 'c' to create new]: ").strip().lower()
                if ans.isdigit() and 1 <= int(ans) <= len(matched_wts):
                    matched_wt = matched_wts[int(ans) - 1]
                elif ans == 'c':
                    # Explicitly trigger creator mode
                    pass
                else:
                    print("Aborted.")
                    sys.exit(0)
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                sys.exit(1)

        if matched_wt:
            from rich.console import Console
            from .runbot_client import query_branch_status
            
            console = Console()
            console.print(f"✨ Worktree for '[cyan]{matched_wt['name']}[/cyan]' already exists locally!")
            
            with console.status("[cyan]Fetching live Runbot status..."):
                res = query_branch_status(matched_wt["name"])
                
            if res:
                batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr = res
                warn_str = f"[yellow]{warning}w[/yellow]" if warning > 0 else "0w"
                fail_str = f"[red]{failed}f[/red]" if failed > 0 else "0f"
                
                # Fetch relative time function local reference
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
                
                time_suffix = f" {relative_time(ts_str)}" if ts_str else ""
                
                if running > 0:
                    status = f"⏳ Running {warn_str} {fail_str}{time_suffix}"
                elif failed > 0:
                    status = f"🔴 Failed {fail_str}{time_suffix}"
                elif warning > 0:
                    status = f"🟡 Warning {warn_str}{time_suffix}"
                else:
                    status = f"🟢 Passed{time_suffix}"
                    
                console.print(f"  [bold]Runbot Status:[/bold] {status}")
                console.print(f"  [bold]Batch URL:[/bold]     {batch_url}")
            else:
                console.print("  [bold]Runbot Status:[/bold] ⚪ No batch")

            # Touch worktree recency
            if "worktree_recency" not in config: config["worktree_recency"] = {}
            import datetime
            config["worktree_recency"][matched_wt["path"]] = datetime.datetime.utcnow().isoformat()
            config_mgr.save(config)
            
            console.print(f"🚀 Dropping you into [cyan]{matched_wt['path']}[/cyan]...\n")
            os.chdir(matched_wt["path"])
            shell = os.environ.get("SHELL", "/bin/bash")
            os.execv(shell, [shell])

        else:
            # Creator Mode!
            if not no_magic:
                remote, v, d, s = decompose_branch(branch_arg, v_list, s_list)
                
                from rich.console import Console
                console = Console()
                console.print("🪄 [bold cyan]Magic Detection Active:[/bold cyan]")
                console.print(f"  - Target Version: [cyan]{v or 'none'}[/cyan]")
                console.print(f"  - Description:    [cyan]{d or 'none'}[/cyan]")
                console.print(f"  - Suffix:         [cyan]{s or 'none'}[/cyan]\n")
            else:
                if branch_arg[0].isdigit():
                    parts = branch_arg.split("-")
                    v = parts[0]
                    d = "-".join(parts[1:])
                else:
                    v = "master"
                    d = branch_arg
                s = config["suffix"]
                
                from rich.console import Console
                Console().print("⚠️ [bold yellow]Magic Detection Disabled. Using raw branch values.[/bold yellow]\n")

            data = {
                "action": "create",
                "version": v,
                "desc": d,
                "suffix": s
            }

            from textual.app import App
            from .custom_screens import DeployScreen

            # Automatically trigger touch on create
            parts = []
            if v: parts.append(str(v))
            if d: parts.append(str(d))
            if s: parts.append(str(s))
            folder_name = "-".join(parts)
            target_path = str(Path(config["wt_root"]).expanduser().absolute() / folder_name)
            
            if "worktree_recency" not in config: config["worktree_recency"] = {}
            import datetime
            config["worktree_recency"][target_path] = datetime.datetime.utcnow().isoformat()
            config_mgr.save(config)

            # Deploy directly in TUI progress bar with 0 extra clicks!
            class FastModeApp(App):
                CSS_PATH = "stylesheet.tcss"
                def on_mount(self):
                    self.push_screen(DeployScreen(data, config))

            app = FastModeApp()
            data = app.run()
    else:
        # Standard TUI App mode
        app = OdooWtApp(config, v_list, s_list, worktrees, VERSION)
        data = app.run()

    # Handle post-deployment completion actions (vscode, terminal)
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
             
    # Sort by recency timestamp first (descending), falling back to version and name
    def recency_sort_key(wt_dict):
        path_str = wt_dict["path"]
        ts = config.get("worktree_recency", {}).get(path_str, "")
        return (ts, version_sort_key(wt_dict), wt_dict["name"])
             
    sorted_wts = sorted(worktrees, key=recency_sort_key, reverse=True)
    
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
