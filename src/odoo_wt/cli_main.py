import os
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    VERSION = version("odoo-wt")
except PackageNotFoundError:
    VERSION = "dev"

from .app_config import config_mgr, debug_log
from .constants.help_text import SUBCOMMAND_HELP
from .system_discovery import decompose_branch, discover_system_data, is_base_branch


def show_help():
    from rich.console import Console
    console = Console()
    console.print(SUBCOMMAND_HELP["menu"].format(version=VERSION))

def check_dependencies():
    from rich.console import Console
    from .preflight_checker import run_preflight_checks
    
    console = Console()
    
    # 1. If we are starting the setup wizard or explicitly editing settings, 
    # we ONLY block if Git is missing from the system entirely.
    is_config_mode = "settings" in sys.argv or "wizard" in sys.argv or not config_mgr.config_file.exists()
    if is_config_mode:
        if not shutil.which("git"):
            console.print("\n[bold red]❌ ERROR: Git is not installed on your system![/bold red]")
            console.print("Please install Git and try again.\n")
            sys.exit(1)
        return
        
    active_config = config_mgr.config if config_mgr.config_file.exists() else {}
    results = run_preflight_checks(active_config)
    
    # 2. To prevent catch-22 deadlocks, we ONLY treat missing Git as an absolute exit blocker.
    # Other issues (missing UV, missing GH, or invalid Odoo base clones) are printed as highly informative
    # warnings, but we let the user continue so they can run 'settings' or launch the TUI to resolve them.
    git_result = next((r for r in results if r.key == "git"), None)
    if git_result and git_result.status == "error":
        console.print("\n[bold red]❌ CRITICAL SYSTEM FAILURE:[/bold red]")
        console.print(f"  [bold red]• {git_result.title}:[/bold red] {git_result.value}")
        console.print(f"    [dim]{git_result.advice}[/dim]\n")
        sys.exit(1)
        
    # Print all other errors/warnings as pretty, informative pre-flight warning cards
    other_issues = [r for r in results if r.status in ("error", "warn") and r.key != "git"]
    if other_issues:
        console.print("\n[bold yellow]⚠️  PRE-FLIGHT DIAGNOSTICS WARNINGS:[/bold yellow]")
        for r in other_issues:
            level_str = "ERROR" if r.status == "error" else "WARNING"
            console.print(f"  [bold yellow]• {r.title} ({level_str}):[/bold yellow] {r.value}")
            console.print(f"    [dim]{r.advice}[/dim]")
        console.print()

    has_error = any(r.status == "error" for r in results if r.key != "git")
    if has_error:
        console.print("[bold red]❌ CRITICAL ERRORS DETECTED. Please resolve the errors above or run 'odoo-wt wizard' to reconfigure.[/bold red]\n")
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
    import asyncio
    from rich.console import Console
    from .deployment_engine import DeployEngine
    
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

def _main_impl():
    try:
        original_cwd = os.getcwd()
    except FileNotFoundError:
        original_cwd = os.path.expanduser("~")
    
    # Symmetrically parse verbose_level by counting --verbose and v occurrences
    verbose_level = 0
    to_remove = []
    for arg in sys.argv[1:]:
        if arg == "--verbose":
            verbose_level += 1
            to_remove.append(arg)
        elif arg.startswith("-"):
            stripped = arg.lstrip("-")
            if all(char == "v" for char in stripped) and len(stripped) > 0:
                verbose_level += len(stripped)
                to_remove.append(arg)
            elif not arg.startswith("--"):
                v_count = arg.count("v")
                if v_count > 0:
                    verbose_level += v_count
                    clean_arg = "-" + "".join(char for char in arg[1:] if char != "v")
                    to_remove.append((arg, clean_arg))
                
    for item in to_remove:
        if isinstance(item, tuple):
            old, new = item
            if old in sys.argv:
                idx = sys.argv.index(old)
                if new == "-":
                    sys.argv.pop(idx)
                else:
                    sys.argv[idx] = new
        else:
            if item in sys.argv:
                sys.argv.remove(item)
                
    verbose = (verbose_level > 0)
    
    # Check for subcommand-specific help first!
    if "--help" in sys.argv or "-h" in sys.argv:
        # Check if there is a subcommand keyword in sys.argv
        reserved_cmds = ["status", "runbot", "reviews", "list", "create", "open", "code", "delete", "rm"]
        target_cmd = None
        for cmd in reserved_cmds:
            if cmd in sys.argv:
                target_cmd = cmd
                break
                
        if target_cmd:
            show_subcommand_help(target_cmd)
        else:
            show_help()
        sys.exit(0)
    
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"odoo-wt v{VERSION}")
        sys.exit(0)

    # --sort or -s flag
    sort_mode = "recency"
    if "--sort" in sys.argv or "-s" in sys.argv:
        for marker in ("--sort", "-s"):
            if marker in sys.argv:
                idx = sys.argv.index(marker)
                if idx + 1 < len(sys.argv):
                    val = sys.argv[idx + 1].strip().lower()
                    if val in ("recency", "recent"):
                        sort_mode = "recency"
                    elif val in ("version", "ver"):
                        sort_mode = "version"
                    elif val in ("name", "alphabetical", "alpha"):
                        sort_mode = "name"
                    elif val in ("runbot", "ci", "status"):
                        sort_mode = "runbot"
                    elif val in ("comments", "reviews", "comment"):
                        sort_mode = "reviews"
                    sys.argv.pop(idx + 1)
                sys.argv.pop(idx)
                break

    # Initialize configuration first (required for all CLI commands)
    if not config_mgr.config_file.exists():
        check_dependencies()
        from .setup_wizard import WizardApp
        app = WizardApp()
        config = app.run()
        if not config:
            from rich.console import Console
            Console().print("\n[bold red]❌ Setup was cancelled before it finished, so odoo-wt has no configuration yet.[/bold red]\n[dim]Run 'odoo-wt' again to restart the setup wizard.[/dim]\n")
            sys.exit(1)
    else:
        config = config_mgr.load()

    # Tab autocomplete generation command for Bash and Zsh
    if "autocomplete" in sys.argv:
        shell = "instructions"
        if "bash" in sys.argv:
            shell = "bash"
        elif "zsh" in sys.argv:
            shell = "zsh"
            
        if shell == "bash":
            print("""_odoo_wt_autocomplete() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        opts="status runbot reviews list create open code delete rm help autocomplete"
        COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
        return 0
    fi
    
    if [[ ${COMP_CWORD} -eq 2 ]]; then
        case "${prev}" in
            status|runbot|reviews|open|code|delete|rm)
                local branches=$(odoo-wt list 2>/dev/null)
                COMPREPLY=( $(compgen -W "${branches}" -- ${cur}) )
                return 0
                ;;
        esac
    fi
}
complete -F _odoo_wt_autocomplete odoo-wt""")
            sys.exit(0)
            
        elif shell == "zsh":
            print("""_odoo_wt_zsh_autocomplete() {
    local -a subcommands
    subcommands=(status runbot reviews list create open code delete rm help autocomplete)
    
    if (( CURRENT == 2 )); then
        _describe -t subcommands 'subcommands' subcommands
    elif (( CURRENT == 3 )); then
        case "$words[2]" in
            status|runbot|reviews|open|code|delete|rm)
                local -a branches
                branches=(${(f)"$(odoo-wt list 2>/dev/null)"})
                _describe -t branches 'branch names' branches
                ;;
        esac
    fi
}
compdef _odoo_wt_zsh_autocomplete odoo-wt""")
            sys.exit(0)
            
        else:
            print("# odoo-wt Autocomplete Shell Integration")
            print("# To enable, run this command or add it to your shell configuration file:")
            print("#")
            print("# For Bash:")
            print("#   echo 'source <(odoo-wt autocomplete bash)' >> ~/.bashrc")
            print("#   source ~/.bashrc")
            print("#")
            print("# For Zsh:")
            print("#   echo 'source <(odoo-wt autocomplete zsh)' >> ~/.zshrc")
            print("#   source ~/.zshrc")
            sys.exit(0)

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

    # Command-line Status, Runbot, and Reviews modes
    target_branch = None
    explicit_all = False
    
    if "status" in sys.argv or "runbot" in sys.argv or "reviews" in sys.argv:
        mode = "combined"
        # Determine if there's an explicit branch or "all" after the command
        for cmd in ("status", "runbot", "reviews"):
            if cmd in sys.argv:
                if cmd == "status":
                    mode = "combined"
                else:
                    mode = cmd
                idx = sys.argv.index(cmd)
                if cmd == "status" and idx + 1 < len(sys.argv) and sys.argv[idx + 1] in ("runbot", "reviews"):
                    mode = sys.argv[idx + 1]
                    sys.argv.pop(idx + 1)
                elif idx + 1 < len(sys.argv):
                    val = sys.argv[idx + 1]
                    if val in ("all", "-a", "--all"):
                        explicit_all = True
                        sys.argv.pop(idx + 1)
                    elif not val.startswith("-"):
                        target_branch = val
                        sys.argv.pop(idx + 1)
                
                if cmd == "status":
                    sys.argv.pop(idx)
                else:
                    sys.argv.remove(cmd)
                break
                
        check_dependencies()
        
        # Symmetrical context-aware resolution of current worktree branch if none specified
        if not target_branch and not explicit_all:
            cwd = Path(os.getcwd()).absolute()
            _, _, worktrees = discover_system_data(
                config["wt_root"], 
                config["suffix"],
                known_versions=config.get("known_versions", []),
                known_suffixes=config.get("known_suffixes", [])
            )
            for wt in worktrees:
                wt_path = Path(wt["path"]).expanduser().absolute()
                if cwd == wt_path or wt_path in cwd.parents:
                    target_branch = wt["name"]
                    break
                    
        if target_branch:
            print_single_branch_detailed_status(config, target_branch, verbose_level=verbose_level, mode=mode)
        else:
            print_cli_status(config, mode=mode, sort_mode=sort_mode, verbose_level=verbose_level)
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
        from .setup_wizard import WizardApp
        app = WizardApp()
        config = app.run()
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

    def apply_magic_fix_if_needed(branch_name):
        if not branch_name:
            return branch_name
        remote, v, d, s = decompose_branch(branch_name, v_list, s_list)
        parts = []
        if v: parts.append(v)
        if d: parts.append(d)
        if s and s != "none": parts.append(s)
        cleaned = "-".join(parts)
        if cleaned and cleaned != branch_name:
            from rich.console import Console
            Console().print(f"🪄 [bold cyan]Magic Fix applied to input:[/bold cyan] [yellow]{branch_name}[/yellow] ➡️ [green]{cleaned}[/green]\n")
            return cleaned
        return branch_name

    if not no_magic:
        if open_branch:
            open_branch = apply_magic_fix_if_needed(open_branch)
        if code_branch:
            code_branch = apply_magic_fix_if_needed(code_branch)
        if delete_branch:
            delete_branch = apply_magic_fix_if_needed(delete_branch)

    # Handle direct commands (open, code, delete)
    if open_branch:
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
                os.environ["PWD"] = match["path"]
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
                    ans = input(f"Are you sure you want to delete worktree '{delete_branch}'? [y/N]: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print("\nAborted.")
                    sys.exit(1)
            else:
                ans = "y"
                
            if ans in ("y", "yes"):
                print(f"Deleting worktree '{delete_branch}'...")
                target_path = match["path"]
                
                # Resolve base directories dynamically
                wt_root = Path(config.get("wt_root", "~/repos/Odoo/wt")).expanduser().absolute()
                base_odoo = wt_root / "master" / config.get("community_dir", "odoo")
                base_ent = wt_root / "master" / config.get("enterprise_dir", "enterprise")
                base_upg = wt_root / "master" / config.get("upgrade_dir", "upgrade")
                
                # Symmetrically remove community, enterprise, and upgrade worktrees from git metadata
                if (Path(target_path) / "odoo").exists():
                    subprocess.run(["git", "worktree", "remove", "-f", str(Path(target_path) / "odoo")], cwd=base_odoo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if (Path(target_path) / "enterprise").exists():
                    subprocess.run(["git", "worktree", "remove", "-f", str(Path(target_path) / "enterprise")], cwd=base_ent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if (Path(target_path) / "upgrade").exists():
                    subprocess.run(["git", "worktree", "remove", "-f", str(Path(target_path) / "upgrade")], cwd=base_upg, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                # Clean up and prune orphaned git references
                for repo in (base_odoo, base_ent, base_upg):
                    if repo.exists():
                        subprocess.run(["git", "worktree", "prune"], cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        
                try:
                    shutil.rmtree(target_path)
                except Exception:
                    pass
                print("Success: Deleted successfully.")
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

    if branch_arg and not no_magic:
        branch_arg = apply_magic_fix_if_needed(branch_arg)

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
                        console.print(f"[bold cyan]Proposing Subcommand[/bold cyan] for '[cyan]{branch_arg}[/cyan]':")
                        console.print(f"  [[green]y[/green]] Run the '{closest_cmd}' subcommand\n")
                    
                    # 2. Print matches
                    tier_label = "Direct" if current_tier == 1 else ("Fuzzy" if current_tier == 2 else "Typo")
                    console.print(f"[bold cyan]{tier_label} Matches[/bold cyan] for '[cyan]{branch_arg}[/cyan]':")
                    if matched_wts:
                        for idx, wt in enumerate(matched_wts, 1):
                            console.print(f"  [[green]{idx}[/green]] {wt['name']}")
                    else:
                        console.print("  [dim](No matching worktrees found)[/dim]")
                        
                    print()
                    options = []
                    option_help = []
                    
                    if closest_cmd:
                        options.append("y")
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
                        if closest_cmd and (ans == closest_cmd or ans in ("y", "yes")):
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
            debug_log(f"Smart Switcher active. Match found: '{matched_wt['name']}' at path '{matched_wt['path']}'")
            from rich.console import Console
            console = Console()
            console.print(f"🚀 Changing directory to [cyan]{matched_wt['path']}[/cyan]...\n")
            
            # Touch worktree recency
            debug_log("Updating worktree recency in configuration...")
            if "worktree_recency" not in config: config["worktree_recency"] = {}
            import datetime
            config["worktree_recency"][matched_wt["path"]] = datetime.datetime.utcnow().isoformat()
            config_mgr.save(config)
            
            debug_log(f"Preparing to spawn sub-shell inside target path (shell: {os.environ.get('SHELL', '/bin/bash')})...")
            os.environ["OLDPWD"] = original_cwd
            os.chdir(matched_wt["path"])
            os.environ["PWD"] = matched_wt["path"]
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
        debug_log("Preparing to launch standard TUI App mode...")
        from .main_tui import OdooWtApp
        debug_log("Instantiating OdooWtApp...")
        app = OdooWtApp(config, v_list, s_list, worktrees, VERSION)
        debug_log("Launching OdooWtApp.run()...")
        data = app.run()
        debug_log("OdooWtApp.run() completed successfully.")

    # Handle post-deployment completion actions (vscode, terminal)
    if data and isinstance(data, dict):
        action = data.get("action")
        if action == "terminal":
            target = data["path"]
            os.environ["OLDPWD"] = original_cwd
            os.chdir(target)
            os.environ["PWD"] = target
            shell = os.environ.get("SHELL", "/bin/bash")
            os.execv(shell, [shell])
        elif action == "vscode":
            target = data["path"]
            if shutil.which("code"):
                os.system(f"code {target}")
            else:
                print("❌ VS Code ('code' command) not found in PATH.")
                print(f"Directory is ready at: {target}")
            os._exit(0)

    # Forcefully terminate to bypass any blocked background thread pools hanging on exit
    os._exit(0)

def main():
    try:
        _main_impl()
    except KeyboardInterrupt:
        print("\nAborted.")
        os._exit(1)

def print_cli_status(config, mode="combined", sort_mode="recency", verbose_level=0):
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .runbot_client import check_branch_status_and_comments
    import datetime
    
    verbose = (verbose_level > 0)
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
    
    for wt in worktrees:
        if is_base_branch(wt["name"]):
            results[wt["name"]] = {
                "status_label": "base",
                "success": 0, "failed": 0, "warning": 0, "running": 0,
                "time_str": "",
                "batch_url": "https://runbot.odoo.com/runbot",
                "odoo_pr": None, "enterprise_pr": None
            }
            comment_results[wt["name"]] = None
            
    # Filter out base branches for concurrent checks
    to_check = [wt for wt in worktrees if not is_base_branch(wt["name"])]
    
    if to_check:
        if mode == "runbot":
            task_desc = "[cyan]Polling Runbot CI..."
        elif mode == "reviews":
            task_desc = "[cyan]Polling PR Comments..."
        else:
            task_desc = "[cyan]Polling Runbot CI & PR Comments..."

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
            task_id = progress.add_task(task_desc, total=len(to_check))
            
            with ThreadPoolExecutor(max_workers=6) as executor:
                future_to_wt = {
                    executor.submit(check_branch_status_and_comments, wt["name"], mode == "runbot", verbose_level): wt 
                    for wt in to_check
                }
                
                for future in as_completed(future_to_wt):
                    wt = future_to_wt[future]
                    branch_name = wt["name"]
                    
                    try:
                        res = future.result()
                        if res:
                            time_suffix = relative_time(res["ts_str"]) if res["ts_str"] else ""
                            
                            if res["running"] > 0:
                                label = "running"
                            elif res["failed"] > 0:
                                label = "failed"
                            elif res["warning"] > 0:
                                label = "warning"
                            else:
                                label = "passed"
                                
                            results[branch_name] = {
                                "status_label": label,
                                "success": res["success"], "failed": res["failed"], "warning": res["warning"], "running": res["running"],
                                "time_str": time_suffix,
                                "batch_url": res["batch_url"],
                                "odoo_pr": res["odoo_pr"], "enterprise_pr": res["enterprise_pr"], "upgrade_pr": res["upgrade_pr"]
                            }
                            
                            if res["comment_data"]:
                                comment_results[branch_name] = res["comment_data"]
                        else:
                            results[branch_name] = {
                                "status_label": "no_batch",
                                "success": 0, "failed": 0, "warning": 0, "running": 0,
                                "time_str": "",
                                "batch_url": f"https://runbot.odoo.com/runbot?search={branch_name}",
                                "odoo_pr": None, "enterprise_pr": None
                            }
                    except Exception:
                        results[branch_name] = {
                            "status_label": "error",
                            "success": 0, "failed": 0, "warning": 0, "running": 0,
                            "time_str": "",
                            "batch_url": f"https://runbot.odoo.com/runbot?search={branch_name}",
                            "odoo_pr": None, "enterprise_pr": None
                        }
                        
                    progress.advance(task_id)
                     
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
             
    # Symmetrical multi-mode sorting
    if sort_mode == "version":
        sorted_wts = sorted(worktrees, key=version_sort_key, reverse=True)
    elif sort_mode == "name":
        # Alphabetical sort ascending
        sorted_wts = sorted(worktrees, key=lambda wt: wt["name"].lower())
    elif sort_mode == "runbot":
        # Sort by Runbot build timestamp descending (newest builds first!)
        def runbot_sort_key(wt_dict):
            name = wt_dict["name"]
            res = results.get(name)
            # Extracted ts_str inside results
            return res.get("ts_str", "") if res else ""
        sorted_wts = sorted(worktrees, key=runbot_sort_key, reverse=True)
    elif sort_mode == "reviews":
        # Sort by last human PR comment timestamp descending (active reviews first!)
        def comment_sort_key(wt_dict):
            name = wt_dict["name"]
            comment_data = comment_results.get(name)
            return comment_data.get("created_at", "") if comment_data else ""
        sorted_wts = sorted(worktrees, key=comment_sort_key, reverse=True)
    else: # sort_mode == "recency"
        def recency_sort_key(wt_dict):
            path_str = wt_dict["path"]
            ts = config.get("worktree_recency", {}).get(path_str, "")
            return (ts, version_sort_key(wt_dict), wt_dict["name"])
        sorted_wts = sorted(worktrees, key=recency_sort_key, reverse=True)
    
    # Calculate target column widths dynamically based on config and terminal width
    max_w = config.get("status_max_width", 200)
    try:
        terminal_width = console.width
        tbl_width = min(max_w, terminal_width)
    except Exception:
        tbl_width = max_v = 120

    # 2. Render Table depending on chosen Mode!
    if mode == "runbot":
        table = Table(title=f"Odoo Runbot Details (v{VERSION})", title_style="bold green", header_style="bold yellow", box=None, width=tbl_width if tbl_width > 40 else None)
        table.add_column("Branch Name", style="cyan", no_wrap=True)
        table.add_column("Status", no_wrap=True, min_width=12)
        table.add_column("Success", style="green", justify="right", no_wrap=True, min_width=8)
        table.add_column("Failed", style="red", justify="right", no_wrap=True, min_width=8)
        table.add_column("Warning", style="yellow", justify="right", no_wrap=True, min_width=8)
        table.add_column("Running", style="cyan", justify="right", no_wrap=True, min_width=8)
        table.add_column("Age", no_wrap=True, min_width=10)
        table.add_column("CI Link", no_wrap=True, min_width=12)
        
        for wt in sorted_wts:
            name = wt["name"]
            res = results.get(name, {
                "status_label": "no_batch",
                "success": 0, "failed": 0, "warning": 0, "running": 0,
                "time_str": "",
                "batch_url": f"https://runbot.odoo.com/runbot?search={name}",
                "odoo_pr": None, "enterprise_pr": None, "upgrade_pr": None
            })
            
            label = res["status_label"]
            time_str = res["time_str"] or "-"
            
            if label == "passed":
                status_str = "🟢 Passed"
            elif label == "failed":
                status_str = "🔴 Failed"
            elif label == "warning":
                status_str = "🟡 Warning"
            elif label == "running":
                status_str = "🏃 Running"
            elif label == "base":
                status_str = "⚪ Base"
                time_str = "-"
            elif label == "error":
                status_str = "⚠️ Error"
            else:
                status_str = "⚪ No batch"
                
            success_str = str(res["success"]) if label not in ("base", "no_batch", "error") else "-"
            failed_str = str(res["failed"]) if label not in ("base", "no_batch", "error") else "-"
            warning_str = str(res["warning"]) if label not in ("base", "no_batch", "error") else "-"
            running_str = str(res["running"]) if label not in ("base", "no_batch", "error") else "-"
            
            link_str = f"[link={res['batch_url']}]Open CI[/link]" if "batch" in res.get("batch_url", "") else "-"
            if is_base_branch(name):
                link_str = "[link=https://runbot.odoo.com/runbot]Open Board[/link]"
                
            table.add_row(name, status_str, success_str, failed_str, warning_str, running_str, time_str, link_str)
            
    elif mode == "reviews":
        table = Table(title=f"Odoo PR Reviews Dashboard (v{VERSION})", title_style="bold magenta", header_style="bold cyan", box=None, width=tbl_width if tbl_width > 40 else None)
        table.add_column("Branch Name", style="cyan", no_wrap=True)
        table.add_column("Pull Requests", no_wrap=True, min_width=18)
        table.add_column("Last Comment", no_wrap=True)
        
        for wt in sorted_wts:
            name = wt["name"]
            res = results.get(name, {
                "status_label": "no_batch",
                "success": 0, "failed": 0, "warning": 0, "running": 0,
                "time_str": "",
                "batch_url": f"https://runbot.odoo.com/runbot?search={name}",
                "odoo_pr": None, "enterprise_pr": None, "upgrade_pr": None
            })
            
            odoo_pr = res.get("odoo_pr")
            ent_pr = res.get("enterprise_pr")
            upg_pr = res.get("upgrade_pr")
            
            # Combine PR links into a single, compact column
            parts = []
            if odoo_pr: parts.append(f"[link={odoo_pr}]Comm[/link]")
            if ent_pr: parts.append(f"[link={ent_pr}]Ent[/link]")
            if upg_pr: parts.append(f"[link={upg_pr}]Upg[/link]")
            pr_str = " | ".join(parts) if parts else "-"
            
            comment_data = comment_results.get(name)
            comment_str = "-"
            if comment_data:
                user = comment_data["user"]
                relative = comment_data["relative"]
                link_url = comment_data["html_url"]
                body_clean = comment_data.get("body_clean", "")
                
                # Symmetrical adaptive layout truncation
                is_ent = comment_data.get("is_ent", False)
                is_upg = comment_data.get("is_upg", False)
                prefix_plain = "[Ent]" if is_ent else ("[Upg]" if is_upg else "[Comm]")
                prefix = "[bold green][Ent][/bold green]" if is_ent else ("[bold yellow][Upg][/bold yellow]" if is_upg else "[bold cyan][Comm][/bold cyan]")
                
                # Symmetrical dynamic column overhead to prevent Branch Name from ever being squeezed/collapsed
                comment_col_max = tbl_width - len(name) - 26
                meta_len = len(prefix_plain) + len(user) + len(relative) + 8
                allowed_body_len = comment_col_max - meta_len
                
                if allowed_body_len >= 10:
                    max_len = min(allowed_body_len, 120)
                    if len(body_clean) > max_len:
                        body_clean = body_clean[:max_len].strip() + "..."
                else:
                    body_clean = "" # Hide body to prevent wrapping
                    
                comment_text = f"{prefix} {user}"
                if body_clean:
                    comment_text += f": {body_clean}"
                comment_text += f" ({relative})"
                comment_str = f"[link={link_url}]{comment_text}[/link]"
                
            table.add_row(name, pr_str, comment_str)
            
    else: # mode == "combined"
        table = Table(title=f"Odoo Worktree Status (v{VERSION})", title_style="bold cyan", header_style="bold magenta", box=None, width=tbl_width if tbl_width > 40 else None)
        table.add_column("Branch Name", style="cyan", no_wrap=True)
        table.add_column("Runbot", no_wrap=True, min_width=12)
        table.add_column("Links", no_wrap=True, min_width=15)
        table.add_column("Last Comment", no_wrap=True)
        
        for wt in sorted_wts:
            name = wt["name"]
            res = results.get(name, {
                "status_label": "no_batch",
                "success": 0, "failed": 0, "warning": 0, "running": 0,
                "time_str": "",
                "batch_url": f"https://runbot.odoo.com/runbot?search={name}",
                "odoo_pr": None, "enterprise_pr": None, "upgrade_pr": None
            })
            
            label = res["status_label"]
            time_str = f" {res['time_str']}" if res["time_str"] else ""
            
            if label == "passed":
                status_str = f"🟢{time_str}"
            elif label == "failed":
                status_str = f"🔴{time_str}"
            elif label == "warning":
                status_str = f"🟡{time_str}"
            elif label == "running":
                status_str = f"🏃{time_str}"
            elif label == "base":
                status_str = "⚪"
            elif label == "error":
                status_str = "⚠️ Error"
            else:
                status_str = "⚪"
                
            parts = []
            if label == "base":
                parts.append("[link=https://runbot.odoo.com/runbot]Board[/link]")
            else:
                batch_url = res.get("batch_url")
                if batch_url and "search=" not in batch_url:
                    parts.append(f"[link={batch_url}]CI[/link]")
                odoo_pr = res.get("odoo_pr")
                if odoo_pr:
                    parts.append(f"[link={odoo_pr}]Com[/link]")
                ent_pr = res.get("enterprise_pr")
                if ent_pr:
                    parts.append(f"[link={ent_pr}]Ent[/link]")
                upg_pr = res.get("upgrade_pr")
                if upg_pr:
                    parts.append(f"[link={upg_pr}]Upg[/link]")
                    
            link_str = "|".join(parts) if parts else f"[link=https://runbot.odoo.com/runbot?search={name}]Search[/link]"
            
            comment_data = comment_results.get(name)
            comment_str = "-"
            if comment_data:
                user = comment_data["user"]
                relative = comment_data["relative"]
                link_url = comment_data["html_url"]
                body_clean = comment_data.get("body_clean", "")
                
                # Symmetrical dynamic column overhead to prevent Branch Name from ever being squeezed/collapsed
                comment_col_max = tbl_width - len(name) - 39
                meta_len = len(user) + len(relative) + 6
                allowed_body_len = comment_col_max - meta_len
                
                if allowed_body_len >= 10:
                    max_len = min(allowed_body_len, 120)
                    if len(body_clean) > max_len:
                        body_clean = body_clean[:max_len].strip() + "..."
                else:
                    body_clean = "" # Hide body to prevent wrapping
                    
                comment_text = f"{user} ({relative})"
                if body_clean:
                    comment_text += f": {body_clean}"
                comment_str = f"[link={link_url}]{comment_text}[/link]"
                
            table.add_row(name, status_str, link_str, comment_str)
            
    console.print(table)
    
    # Print the explanatory footnote
    sort_labels = {
        "recency": "most recently deployed, opened, or accessed worktrees first (Default)",
        "version": "Odoo release version descending",
        "name": "alphabetical branch name ascending",
        "runbot": "most recently triggered Runbot builds first",
        "reviews": "most recently active human PR comments first"
    }
    console.print(f"[dim]Sorted by: {sort_labels.get(sort_mode, sort_mode)}[/dim]")

def print_single_branch_detailed_status(config, branch_name, verbose_level=0, mode="combined"):
    from rich.console import Console
    from .runbot_client import check_branch_status_and_comments
    from .system_discovery import is_base_branch
    import datetime
    import textwrap
    
    verbose = (verbose_level > 0)
    console = Console()
    
    # Symmetrically resolve full branch name from worktrees list if possible
    _, _, worktrees = discover_system_data(
        config["wt_root"], 
        config["suffix"],
        known_versions=config.get("known_versions", []),
        known_suffixes=config.get("known_suffixes", [])
    )
    
    exact_match = None
    for wt in worktrees:
        if wt["name"].lower() == branch_name.lower():
            exact_match = wt
            break
            
    if exact_match:
        branch_name = exact_match["name"]
    else:
        for wt in worktrees:
            if branch_name.lower() in wt["name"].lower():
                branch_name = wt["name"]
                break
            
    is_base = is_base_branch(branch_name)
    title_label = "Base Branch" if is_base else "Detailed Status"
    if mode == "runbot":
        title_label = "Runbot CI Status"
    elif mode == "reviews":
        title_label = "PR Reviews Status"
        
    console.print(f"📊 [bold cyan]{title_label} for[/bold cyan] '[cyan]{branch_name}[/cyan]':\n")
    
    skip_comments = is_base or mode == "runbot"
    with console.status("[cyan]Fetching live Runbot details..."):
        res = check_branch_status_and_comments(branch_name, skip_comments=skip_comments, verbose_level=verbose_level)
        
    if not res:
        console.print("  [bold]Runbot Status:[/bold] ⚪ No batch (not found on Runbot)")
        print()
        return
        
    if is_base:
        res["odoo_pr"] = None
        res["enterprise_pr"] = None
        res["upgrade_pr"] = None
        res["comment_data"] = None
        
    success = res["success"]
    failed = res["failed"]
    warning = res["warning"]
    running = res["running"]
    
    warn_str = f"[bold yellow]{warning}w[/bold yellow]" if warning > 0 else "0w"
    fail_str = f"[bold red]{failed}f[/bold red]" if failed > 0 else "0f"
    run_str = f"[bold cyan]{running}r[/bold cyan]" if running > 0 else "0r"
    
    status_suffix = f"({warn_str}, {fail_str}, {run_str})"
    ts_str = res["ts_str"]
    
    def relative_time(ts):
        if not ts: return ""
        try:
            dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
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
    failing_tests = res.get("failing_tests", [])
    
    if running > 0:
        status_line = f"⏳ [bold cyan]Running[/bold cyan] {status_suffix}{time_suffix}"
    elif failed > 0:
        status_line = f"🔴 [bold red]Failed[/bold red] {status_suffix}{time_suffix}"
        if failing_tests:
            status_line += f"  ➔  [bold red]{len(failing_tests)} failing tests[/bold red]"
        if is_base:
            status_line += "\n  [bold red]⚠️  Note: Some upstream builds are currently FAILING on this base branch![/bold red]"
    elif warning > 0:
        status_line = f"🟡 [bold yellow]Warning[/bold yellow] {status_suffix}{time_suffix}"
    else:
        status_line = f"🟢 [bold green]Passed[/bold green] {status_suffix}{time_suffix}"
        
    if mode != "reviews":
        console.print(f"  [bold]Runbot Status:[/bold] {status_line}")
        console.print(f"  [bold]Batch URL:[/bold]     [link={res['batch_url']}]{res['batch_url']}[/link]")
        
        # Failing tests summary if any (only on dedicated runbot subcommand cards)
        if mode == "runbot":
            failing_tests = res.get("failing_tests", [])
            if failing_tests:
                if verbose:
                    # Group by module/addon
                    grouped = {}
                    for t in failing_tests:
                        addon = "core/base"
                        raw_test = t.split("  ➔  ")[0].strip()
                        if "addons." in raw_test:
                            parts = raw_test.split("addons.")[1].split(".")
                            if parts: addon = parts[0]
                        elif "addons/" in raw_test:
                            parts = raw_test.split("addons/")[1].split("/")
                            if parts: addon = parts[0]
                        elif "." in raw_test:
                            parts = raw_test.split(".")
                            if parts[0] not in ("odoo", "src"):
                                addon = parts[0]
                                
                        if addon not in grouped:
                            grouped[addon] = []
                        grouped[addon].append(t)
                        
                    console.print("\n  [bold red]❌ Failing Tests by Module:[/bold red]")
                    for addon, tests in sorted(grouped.items()):
                        console.print(f"    [bold cyan]{addon}[/bold cyan]:")
                        for t in tests:
                            # Print cleanly with no hyphens/bullets, indented with exactly 6 spaces for easy double-click copying!
                            console.print(f"      [red]{t}[/red]")
                else:
                    # Symmetrical non-verbose Top 5 failure summary
                    console.print("\n  [bold red]❌ Failing Tests (top 5):[/bold red]")
                    for t in failing_tests[:5]:
                        # Print cleanly with no hyphens/bullets, indented with exactly 4 spaces for easy double-click copying!
                        console.print(f"    [red]{t}[/red]")
                    if len(failing_tests) > 5:
                        console.print(f"    - [dim]... and {len(failing_tests) - 5} more (Check the Batch URL or run with --verbose)[/dim]")
    
    if mode != "runbot" and not is_base:
        odoo_pr = res["odoo_pr"]
        ent_pr = res["enterprise_pr"]
        upg_pr = res["upgrade_pr"]
        
        console.print("\n  [bold yellow]Pull Requests:[/bold yellow]")
        if not odoo_pr and not ent_pr and not upg_pr:
            console.print("    [dim]No linked pull requests found on Runbot.[/dim]")
        else:
            if odoo_pr:
                console.print(f"    - Community:  [link={odoo_pr}]{odoo_pr}[/link]")
            if ent_pr:
                console.print(f"    - Enterprise: [link={ent_pr}]{ent_pr}[/link]")
            if upg_pr:
                console.print(f"    - Upgrade:    [link={upg_pr}]{upg_pr}[/link]")
                
        comment_data = res["comment_data"]
        if comment_data:
            history = comment_data.get("history", [])
            if verbose and history:
                console.print("\n  [bold yellow]PR Reviews History (last 10 comments):[/bold yellow]")
                # Print oldest first (chronological order)
                for c in reversed(history):
                    prefix = "[bold green][Ent][/bold green]" if c["is_ent"] else ("[bold yellow][Upg][/bold yellow]" if c["is_upg"] else "[bold cyan][Comm][/bold cyan]")
                    console.print(f"    👤 {prefix} [bold cyan]@{c['user']}[/bold cyan] [dim]({c['relative']}):[/dim]")
                    wrapped_body = textwrap.indent(textwrap.fill(c["body"], width=80), "      ")
                    console.print(f"      [italic]{wrapped_body}[/italic]")
                    console.print(f"    🔗 [underline blue]{c['html_url']}[/underline blue]\n")
            else:
                console.print("\n  [bold yellow]Latest Review/Comment:[/bold yellow]")
                user = comment_data["user"]
                relative = comment_data["relative"]
                body = comment_data["body"]
                link_url = comment_data["html_url"]
                
                console.print(f"    👤 [bold cyan]@{user}[/bold cyan] [dim]({relative}):[/dim]")
                wrapped_body = textwrap.indent(textwrap.fill(body, width=80), "      ")
                console.print(f"    [italic]{wrapped_body}[/italic]")
                console.print(f"    🔗 [underline blue]{link_url}[/underline blue]")
        else:
            console.print("\n  [bold yellow]Latest Review/Comment:[/bold yellow]")
            console.print("    [dim]No review comments found or GitHub authentication not active.[/dim]")
    print()

def show_subcommand_help(subcommand):
    from rich.console import Console
    console = Console()
    
    if (subcmd:=subcommand.lower()) in SUBCOMMAND_HELP:
        console.print(f"[bold cyan]Odoo Worktree Assistant[/bold cyan] ([bold green]odoo-wt[/bold green]) - Subcommand Help: [cyan]'{subcmd}'[/cyan]\n")
        console.print(SUBCOMMAND_HELP[subcmd].format(subcommand=subcmd))
    else:
        console.print(f"[bold red]Error:[/bold red] Unknown subcommand '{subcmd}'. Run [bold green]odoo-wt --help[/bold green] for a list of valid commands.")

if __name__ == "__main__":
    main()
