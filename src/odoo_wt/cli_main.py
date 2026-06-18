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
    from rich.console import Console
    console = Console()
    
    console.print(f"[bold cyan]Odoo Worktree Assistant[/bold cyan] ([bold green]odoo-wt[/bold green]) [cyan]v{VERSION}[/cyan]\n")
    console.print("A professional TUI-driven Git worktree manager for Odoo developers.\n")
    
    console.print("[bold yellow]Usage:[/bold yellow]")
    console.print("  [bold green]odoo-wt[/bold green]                       Launch the interactive TUI [dim](Recommended)[/dim]")
    console.print("  [bold green]odoo-wt status[/bold green] [dim](or runbot)[/dim]    Print worktree and Runbot status table directly")
    console.print("  [bold green]odoo-wt list[/bold green]                  Simply list existing worktree names, one per line")
    console.print("  [bold green]odoo-wt <branch>[/bold green]              Smart Switcher/Creator: opens TUI if new, shell if existing")
    
    console.print("\n[bold yellow]Primary Subcommands:[/bold yellow]")
    console.print("  [bold green]odoo-wt create[/bold green] [cyan]<branch>[/cyan]       Explicitly open TUI pre-filled in 'Creation' tab")
    console.print("  [bold green]odoo-wt open[/bold green] [cyan]<branch>[/cyan]         Directly open terminal shell in an existing worktree")
    console.print("  [bold green]odoo-wt code[/bold green] [cyan]<branch>[/cyan]         Directly open VS Code in an existing worktree")
    console.print("  [bold green]odoo-wt delete/rm[/bold green] [cyan]<branch>[/cyan]    Directly delete an existing worktree with CLI prompt")
    
    console.print("\n[bold yellow]Options & Flags:[/bold yellow]")
    console.print("  [bold cyan]-o, --open[/bold cyan] [cyan]<branch>[/cyan]          Alias for 'open <branch>'")
    console.print("  [bold cyan]-c, --code[/bold cyan] [cyan]<branch>[/cyan]          Alias for 'code <branch>'")
    console.print("  [bold cyan]-d, --delete[/bold cyan] [cyan]<branch>[/cyan]        Alias for 'delete <branch>'")
    console.print("  [bold cyan]--no-magic[/bold cyan]                    Disable automatic 'Magic Fix' branch decomposition")
    console.print("  [bold cyan]--verbose[/bold cyan]                     Enable detailed, verbose command output during CLI deployment")
    console.print("  [bold cyan]--config-path[/bold cyan]                 Print the active odoo-wt.json configuration path")
    console.print("  [bold cyan]--log-path[/bold cyan]                    Print the active odoo-wt-logs.jsonl path")
    console.print("  [bold cyan]-h, --help[/bold cyan]                    Show this help message")
    console.print("  [bold cyan]-v, --version[/bold cyan]                 Show the current version")
    
    console.print("\n[bold yellow]Environment Variables:[/bold yellow]")
    console.print("  [bold cyan]SHELL[/bold cyan]                         Target shell when opening terminal [dim](default: /bin/bash)[/dim]")
    
    console.print("\n[bold yellow]Documentation:[/bold yellow]")
    console.print("  [underline blue]https://github.com/nd-dew/odoo-wt[/underline blue]\n")

def check_dependencies():
    from rich.console import Console
    missing = []
    if not shutil.which("git"):
        missing.append("git")
    if not shutil.which("uv"):
        missing.append("uv")
    
    if missing:
        console = Console()
        console.print(f"❌ [bold red]Error: Required dependencies not found in PATH: {', '.join(missing)}[/bold red]")
        console.print("Please install them and try again.")
        console.print("  - [bold cyan]git[/bold cyan]: [underline blue]https://git-scm.com/[/underline blue]")
        console.print("  - [bold cyan]uv[/bold cyan]:  [underline blue]https://docs.astral.sh/uv/[/underline blue]")
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

async def run_cli_deployment(config, data, verbose=False):
    from .deployment_engine import DeployEngine
    from rich.console import Console
    import asyncio
    
    console = Console()
    console.print(f"🚀 [bold cyan]Starting Direct CLI Deployment for '{data['version']}-{data['desc']}-{data['suffix']}'...[/bold cyan]\n")
    
    engine = DeployEngine(config, data)
    engine.target_dir.mkdir(parents=True, exist_ok=True)
    
    base_odoo = engine.wt_root / "master" / engine.comm_dir
    base_ent = engine.wt_root / "master" / engine.ent_dir
    
    async def handle_updates(gen, label):
        async for update in gen:
            if update.log_line:
                line = update.log_line.strip()
                if line:
                    if not verbose:
                        # Filter out verbose progress/git details by default
                        skip_markers = [
                            "Updating files:", "From github.com", "FETCH_HEAD", 
                            "remote: ", "Receiving objects:", "Resolving deltas:",
                            "* branch", " branch '", "HEAD is now at"
                        ]
                        if any(marker in line for marker in skip_markers):
                            continue
                    console.print(f"[{label}] {line}")
                    
    # Run odoo, ent, and uv concurrently!
    await asyncio.gather(
        handle_updates(engine.deploy_repo(base_odoo, engine.comm_dir, "odoo"), "Community"),
        handle_updates(engine.deploy_repo(base_ent, engine.ent_dir, "ent"), "Enterprise"),
        handle_updates(engine.setup_uv(), "UV Env")
    )
    
    try:
        console.print("[VS Code] Generating VS Code launch configuration...")
        await engine.setup_vscode()
        console.print("[VS Code] ✅ VS Code launch configuration created.")
    except Exception as e:
        console.print(f"[VS Code] [bold red]Failed to create VS Code launch config: {e}[/bold red]")
        
    console.print(f"\n✨ [bold green]SUCCESS! Worktree ready at:[/bold green] [cyan]{engine.target_dir}[/cyan]")
    
    # Determine default exit action (terminal or VS Code)
    action = "terminal"
    # If VS Code code is selected in options, or if VS Code flag is passed, default to vscode.
    # In CLI mode, we can default to Terminal (os.execv), unless they explicitly configure vscode or pass a flag.
    return {"action": action, "path": str(engine.target_dir)}

def main():
    original_cwd = os.getcwd()
    
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

    # Command-line Status mode (supporting status, --status, and runbot)
    if "--status" in sys.argv or "status" in sys.argv or "runbot" in sys.argv:
        if "--status" in sys.argv: sys.argv.remove("--status")
        if "status" in sys.argv: sys.argv.remove("status")
        if "runbot" in sys.argv: sys.argv.remove("runbot")
        
        check_dependencies()
        print_cli_status(config)
        sys.exit(0)

    # Explicit direct action flags or subcommands
    # -o, --open <branch> or open <branch>
    open_branch = None
    if "open" in sys.argv or "--open" in sys.argv or "-o" in sys.argv:
        for marker in ("open", "--open", "-o"):
            if marker in sys.argv:
                idx = sys.argv.index(marker)
                if marker == "open" and idx != 1:
                    continue
                if idx + 1 < len(sys.argv):
                    open_branch = sys.argv[idx + 1]
                    sys.argv.pop(idx + 1)
                sys.argv.pop(idx)
                break

    # -c, --code <branch> or code <branch>
    code_branch = None
    if "code" in sys.argv or "--code" in sys.argv or "-c" in sys.argv:
        for marker in ("code", "--code", "-c"):
            if marker in sys.argv:
                idx = sys.argv.index(marker)
                if marker == "code" and idx != 1:
                    continue
                if idx + 1 < len(sys.argv):
                    code_branch = sys.argv[idx + 1]
                    sys.argv.pop(idx + 1)
                sys.argv.pop(idx)
                break

    # -d, --delete <branch> or delete/rm <branch>
    delete_branch = None
    if "delete" in sys.argv or "rm" in sys.argv or "--delete" in sys.argv or "-d" in sys.argv:
        for marker in ("delete", "rm", "--delete", "-d"):
            if marker in sys.argv:
                idx = sys.argv.index(marker)
                if marker in ("delete", "rm") and idx != 1:
                    continue
                if idx + 1 < len(sys.argv):
                    delete_branch = sys.argv[idx + 1]
                    sys.argv.pop(idx + 1)
                sys.argv.pop(idx)
                break

    # --no-magic flag
    no_magic = False
    if "--no-magic" in sys.argv:
        no_magic = True
        sys.argv.remove("--no-magic")

    # --verbose flag
    verbose = False
    if "--verbose" in sys.argv:
        verbose = True
        sys.argv.remove("--verbose")

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
            
            os.environ["OLDPWD"] = original_cwd
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
        # Check if the query is a typo of a reserved subcommand (e.g., "lis" -> "list")
        closest_cmd = None
        if not explicit_create:
            query = branch_arg.strip().lower()
            reserved_cmds = ["status", "create", "wizard", "runbot", "list"]
            if query not in reserved_cmds:
                for cmd in reserved_cmds:
                    max_dist = 1 if len(cmd) <= 4 else 2
                    if get_edit_distance(query, cmd) <= max_dist:
                        closest_cmd = cmd
                        break

        # Stateful multi-tiered progressive switcher loop
        current_tier = 1  # 1: Substring, 2: Fuzzy/Multi-Term, 3: Typo (Levenshtein)
        matched_wt = None
        
        # Version sort key for fallback sorting
        def local_version_sort_key(wt):
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
                
        matched_wt = None
        if not explicit_create:
            while True:
                matched_wts = []
                query = branch_arg.strip().lower()
                
                # --- TIER 1: Contiguous Substring Matches ---
                if current_tier >= 1:
                    for wt in worktrees:
                        if query in wt["name"].lower():
                            matched_wts.append(wt)
                            
                # --- TIER 2: Fuzzy Multi-Term Matches ---
                if current_tier >= 2:
                    terms = query.replace("-", " ").replace("_", " ").split()
                    for wt in worktrees:
                        if wt in matched_wts: continue
                        if all(t in wt["name"].lower() for t in terms):
                            matched_wts.append(wt)
                            
                # --- TIER 3: Typo Levenshtein Matches (Only if query length >= 5) ---
                if current_tier >= 3 and len(query) >= 5:
                    for wt in worktrees:
                        if wt in matched_wts: continue
                        tokens = wt["name"].lower().replace("-", " ").replace("_", " ").split()
                        if any(get_edit_distance(query, tok) <= 2 for tok in tokens):
                            matched_wts.append(wt)
                            
                # Sort matches consistently
                def recency_sort_key(wt_dict):
                    path_str = wt_dict["path"]
                    ts = config.get("worktree_recency", {}).get(path_str, "")
                    return (ts, local_version_sort_key(wt_dict), wt_dict["name"])
                    
                matched_wts = sorted(matched_wts, key=recency_sort_key, reverse=True)
                
                # Remove duplicate matches while preserving sorted order
                seen = set()
                unique_matches = []
                for wt in matched_wts:
                    if wt["path"] not in seen:
                        seen.add(wt["path"])
                        unique_matches.append(wt)
                matched_wts = unique_matches
                
                # If exactly 1 match on Tier 1 (on startup) and NO subcommand typo proposal exists, switch directly!
                if len(matched_wts) == 1 and current_tier == 1 and not closest_cmd:
                    matched_wt = matched_wts[0]
                    break
                    
                # If multiple matches or we've expanded tiers, prompt interactive selector
                if len(matched_wts) > 0 or current_tier < 3 or closest_cmd:
                    from rich.console import Console
                    console = Console()
                    
                    # 1. Propose Subcommand if any
                    if closest_cmd:
                        console.print(f"💡 [bold cyan]Proposing Subcommand[/bold cyan] for '[cyan]{branch_arg}[/cyan]':")
                        console.print(f"  [[green]{closest_cmd}[/green]] Run the '{closest_cmd}' subcommand\n")
                    
                    # 2. Print matches
                    tier_label = "Direct" if current_tier == 1 else ("Fuzzy" if current_tier == 2 else "Typo")
                    console.print(f"🔍 [bold cyan]{tier_label} Matches[/bold cyan] for '[cyan]{branch_arg}[/cyan]':")
                    if matched_wts:
                        for idx, wt in enumerate(matched_wts, 1):
                            console.print(f"  [[green]{idx}[/green]] {wt['name']}")
                    else:
                        console.print("  [dim](No matching worktrees found)[/dim]")
                        
                    print()
                    options = []
                    option_help = []
                    
                    if closest_cmd:
                        options.append(closest_cmd)
                    if matched_wts:
                        options.append(f"1-{len(matched_wts)}")
                        
                    if current_tier < 2:
                        options.append("f")
                        option_help.append("[[green]f[/green]] Search more (fuzzy substring / words)")
                    if current_tier < 3:
                        options.append("t")
                        option_help.append("[[green]t[/green]] Search more (typo / distance)")
                        
                    options.append("c")
                    option_help.append("[[green]c[/green]] Create brand new worktree")
                    
                    for opt in option_help:
                        console.print(f"  {opt}")
                        
                    print()
                    try:
                        ans = input(f"Select an option [{', '.join(options)}]: ").strip().lower()
                        if closest_cmd and ans == closest_cmd:
                            sys.argv.append(closest_cmd)
                            # Re-run main recursively to execute the corrected subcommand cleanly!
                            main()
                            sys.exit(0)
                        elif ans.isdigit() and 1 <= int(ans) <= len(matched_wts):
                            matched_wt = matched_wts[int(ans) - 1]
                            break
                        elif ans == 'f' and current_tier < 2:
                            current_tier = 2
                            console.print("\n✨ Running [bold yellow]Fuzzy Substring Matcher[/bold yellow]...")
                            continue
                        elif ans == 't' and current_tier < 3:
                            current_tier = 3
                            console.print("\n✨ Running [bold yellow]Levenshtein Typo Matcher[/bold yellow]...")
                            continue
                        elif ans == 'c':
                            matched_wt = None
                            break
                        else:
                            print("Aborted.")
                            sys.exit(0)
                    except (KeyboardInterrupt, EOFError):
                        print("\nAborted.")
                        sys.exit(1)
                else:
                    matched_wt = None
                    break
        else:
            matched_wt = None

        if matched_wt:
            from rich.console import Console
            from .runbot_client import query_branch_status
            
            console = Console()
            console.print(f"✨ Found worktree '[cyan]{matched_wt['name']}[/cyan]' locally!")
            
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
            
            console.print(f"🚀 Changing directory to [cyan]{matched_wt['path']}[/cyan]...\n")
            os.environ["OLDPWD"] = original_cwd
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

            # Deploy directly in pure CLI mode (stdout logs) with 0 extra clicks!
            import asyncio
            data = asyncio.run(run_cli_deployment(config, data, verbose=verbose))
    else:
        # Standard TUI App mode
        app = OdooWtApp(config, v_list, s_list, worktrees, VERSION)
        data = app.run()

    # Handle post-deployment completion actions (vscode, terminal)
    if data and isinstance(data, dict):
        action = data.get("action")
        if action == "terminal":
            target = data["path"]
            os.environ["OLDPWD"] = original_cwd
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
    comment_results = {}
    resolved_urls = {}
    resolved_odoo_prs = {}
    resolved_ent_prs = {}
    
    for wt in worktrees:
        if is_base_branch(wt["name"]):
            results[wt["name"]] = "⚪ Base Branch"
            comment_results[wt["name"]] = ""
            resolved_urls[wt["name"]] = "https://runbot.odoo.com/runbot"
            
    # Filter out base branches for concurrent checks
    to_check = [wt for wt in worktrees if not is_base_branch(wt["name"])]
    
    if to_check:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
            task_id = progress.add_task("[cyan]Polling Runbot CI & PR Comments...", total=len(to_check))
            
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
                    comment_cell = "-"
                    
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
                                
                            # Fetch PR comment!
                            from .runbot_client import get_latest_pr_comment
                            try:
                                comment_data = get_latest_pr_comment(odoo_pr, enterprise_pr)
                                if comment_data:
                                    user = comment_data["user"]
                                    relative = comment_data["relative"]
                                    link_url = comment_data["html_url"]
                                    prefix = "[bold green][Ent][/bold green]" if comment_data["is_ent"] else "[bold cyan][Comm][/bold cyan]"
                                    comment_cell = f"[link={link_url}]💬 {prefix} {user} ({relative})[/link]"
                                else:
                                    comment_cell = "-"
                            except Exception:
                                comment_cell = "-"
                        else:
                            status = "⚪ No batch"
                            comment_cell = "-"
                    except Exception:
                        status = "⚠️ Error"
                        comment_cell = "-"
                        
                    results[branch_name] = status
                    comment_results[branch_name] = comment_cell
                    progress.advance(task_id)
                     
    # 2. Render gorgeous Rich Table
    table = Table(title=f"Odoo Worktree Status (v{VERSION})", title_style="bold cyan", header_style="bold magenta", box=None)
    table.add_column("Branch Name", style="cyan")
    table.add_column("Runbot Status")
    table.add_column("Link")
    table.add_column("Last Review")
    
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
            
        comment_str = comment_results.get(name, "-")
        table.add_row(name, status, link_str, comment_str)
         
    console.print(table)

if __name__ == "__main__":
    main()
