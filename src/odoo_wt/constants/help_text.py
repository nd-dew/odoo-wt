# constants/help_text.py

SUBCOMMAND_HELP = {
    "menu": """\
[bold cyan]Odoo Worktree Assistant[/bold cyan] ([bold green]odoo-wt[/bold green]) [cyan]v{version}[/cyan]

A premium terminal tool to manage, deploy, and monitor Odoo developer worktrees.

[bold yellow]Usage:[/bold yellow]
  [bold green]odoo-wt[/bold green] [cyan]\\[subcommand][/cyan] [cyan]\\[options][/cyan]
  (If no subcommand is passed, launches the full-screen interactive TUI)

[bold yellow]Subcommands:[/bold yellow]
  [bold green]status[/bold green] [cyan]\\[all/-a/branch][/cyan]    Show Runbot build status & GitHub PR reviews [dim](Combined)[/dim]
  [bold green]runbot[/bold green] [cyan]\\[all/-a/branch][/cyan]    Show Runbot build details & failing tests [dim](CI-focused)[/dim]
  [bold green]reviews[/bold green] [cyan]\\[all/-a/branch][/cyan]   Show linked Pull Requests & latest peer comments [dim](PR-focused)[/dim]
  [bold green]list[/bold green]                         Simply list all local worktree branch names
  [bold green]create[/bold green] [cyan]<branch>[/cyan]          Open the TUI pre-filled in the 'Creation' tab
  [bold green]open[/bold green] [cyan]<branch>[/cyan]            Directly change your shell directory into a worktree
  [bold green]code[/bold green] [cyan]<branch>[/cyan]            Directly open VS Code in a worktree
  [bold green]delete/rm[/bold green] [cyan]<branch>[/cyan]       Directly delete a worktree with a safety prompt
  [bold green]<branch>[/bold green]                  [bold cyan]The Smart Switcher:[/bold cyan] opens shell if existing, TUI if new

[bold yellow]Options & Flags:[/bold yellow]
  [bold cyan]-o, --open[/bold cyan] [cyan]<branch>[/cyan]          Alias for 'open <branch>'
  [bold cyan]-c, --code[/bold cyan] [cyan]<branch>[/cyan]          Alias for 'code <branch>'
  [bold cyan]-d, --delete[/bold cyan] [cyan]<branch>[/cyan]        Alias for 'delete <branch>'
  [bold cyan]-s, --sort[/bold cyan] [cyan]<mode>[/cyan]           Sort status tables by: recency, version, name, runbot, reviews
  [bold cyan]-v, --verbose[/bold cyan]                 Show all failing tests (grouped by module) / verbose deployment logs
  [bold cyan]-vv, --verbose --verbose[/bold cyan]     Verboser Verbose: Shows actual failed test traceback/error messages
  [bold cyan]--no-magic[/bold cyan]                    Disable automatic 'Magic Fix' branch decomposition
  [bold cyan]--config-path[/bold cyan]                 Print the active odoo-wt.json configuration path
  [bold cyan]--log-path[/bold cyan]                    Print the active odoo-wt-logs.jsonl path
  [bold cyan]-h, --help[/bold cyan]                    Show this help message
  [bold cyan]-V, --version[/bold cyan]                 Show the current version

[bold yellow]Detailed Explanations:[/bold yellow]

  [bold cyan]1. The Smart Switcher: odoo-wt <branch>[/bold cyan]
     If you run odoo-wt with just a branch name (no subcommand):
     - [bold]If it exists:[/bold] Instantly changes your terminal directory ('cd') into it,
       launches your target shell, and displays its live Runbot & GitHub reviews.
     - [bold]If new:[/bold] Opens the TUI Creation tab pre-filled with that branch name.

  [bold cyan]2. Context-Aware status: odoo-wt status/runbot/reviews[/bold cyan]
     These status commands dynamically adapt to where your terminal is standing:
     - [bold]Inside a worktree folder:[/bold] Displays a deeply detailed diagnostic card
       specifically for your active branch (failed tests, PR reviewers, last human feedback).
     - [bold]Outside any worktree:[/bold] Displays a high-level summary table of ALL your branches.
     - You can force the full table inside a worktree by running 'status -a', or query
       any specific branch from anywhere by running 'status <branch>'.

  [bold cyan]3. Symmetrical Diagnostics:[/bold cyan]
     - [bold]status[/bold]: Combined CI build stats + Latest GitHub Reviews/Comments.
     - [bold]runbot[/bold]: CI-only (build counts + failing tests). [bold green]Skips GitHub PR calls for speed![/bold green]
     - [bold]reviews[/bold]: Reviews-only (Pull Requests + latest peer comments). Skips Runbot counts.

[bold yellow]Recency Sorting:[/bold yellow]
  Worktrees are sorted by default by recency. Any action that deploys, opens,
  or accesses a worktree (e.g. create, open, code, selecting in TUI) updates
  its local access timestamp and makes it most recent.

[bold yellow]Environment Variables:[/bold yellow]
  [bold cyan]SHELL[/bold cyan]                         Target shell when opening terminal [dim](default: /bin/bash)[/dim]

[bold yellow]Documentation:[/bold yellow]
  [underline blue]https://github.com/nd-dew/odoo-wt[/underline blue]
""",
    "status": """\
The [bold green]status[/bold green] command displays the live Runbot CI build status and peer reviews [bold cyan](Combined View)[/bold cyan].

[bold yellow]Usage:[/bold yellow]
  [bold green]odoo-wt status[/bold green]                       Show combined status of the active branch (if inside a worktree)
  [bold green]odoo-wt status[/bold green] [cyan]<branch_name>[/cyan]          Show combined status of a specific branch from anywhere
  [bold green]odoo-wt status[/bold green] [cyan]\\[all/-a][/cyan]             Show combined overview table of all local branches

[bold yellow]Description:[/bold yellow]
  Fetches both the Runbot CI build status (including failed/warned build counts)
  and the latest GitHub PR comments/reviews in a single, comprehensive diagnostic view.
  
  By default, if run inside any worktree directory, it displays a detailed single-branch card.
  To bypass this and force-display the global table of all branches, use the [bold cyan]'all'[/bold cyan] or [bold cyan]'-a'[/bold cyan] parameter.

[bold yellow]Context-Aware Directory Sensing:[/bold yellow]
  If you run this command inside any subdirectory of an active worktree folder (including 'odoo' or 'enterprise'),
  it automatically detects your path, resolves the full branch name, and prints its dedicated detailed diagnostic card.
  This saves you from constantly viewing the full global table or typing out long branch names!

[bold yellow]⚠️  GitHub CLI Authentication Required:[/bold yellow]
  This command relies on the GitHub CLI ('gh' tool) being installed, alive, and
  authenticated ('gh auth status') to fetch Pull Request links and human review comments.
  If you are not logged in, reviews and comments will be skipped gracefully.

[bold yellow]Examples:[/bold yellow]
  [bold green]odoo-wt status[/bold green]                    [dim]# Show combined card of current worktree branch[/dim]
  [bold green]odoo-wt status[/bold green] [cyan]-a[/cyan]                 [dim]# Force display the high-level combined table of all branches[/dim]
""",

    "runbot": """\
The [bold green]runbot[/bold green] command displays the live Runbot CI build status and failing tests [bold cyan](CI-Focused View)[/bold cyan].

[bold yellow]Usage:[/bold yellow]
  [bold green]odoo-wt runbot[/bold green]                       Show CI status of the active branch (if inside a worktree)
  [bold green]odoo-wt runbot[/bold green] [cyan]<branch_name>[/cyan]          Show CI status of a specific branch from anywhere
  [bold green]odoo-wt runbot[/bold green] [cyan]\\[all/-a][/cyan]             Show CI overview table of all local branches

[bold yellow]Description:[/bold yellow]
  A high-performance diagnostic command that focuses exclusively on Runbot CI build counts,
  batch URLs, and failing test lists.
  
  By default, if run inside any worktree directory, it displays a detailed single-branch CI card.
  To bypass this and force-display the global table of all branches, use the [bold cyan]'all'[/bold cyan] or [bold cyan]'-a'[/bold cyan] parameter.
  
  This command skips all GitHub PR reviews and comments lookups to maximize performance.

[bold yellow]Context-Aware Directory Sensing:[/bold yellow]
  If you run this command inside any subdirectory of an active worktree folder (including 'odoo' or 'enterprise'),
  it automatically detects your path, resolves the full branch name, and prints its dedicated detailed CI diagnostic card.

[bold yellow]Failing Tests & Linter Scraper:[/bold yellow]
  If there are failing builds on the branch, odoo-wt automatically downloads the batch pages and detailed static logs,
  extracting the exact names of failing unittests or linter checks (like 'check_semgrep_security') and listing them.
  - Default: Shows the top 5 failing tests on clean, hyphen-free lines for [bold cyan]easy double-click copying[/bold cyan].
  - `--verbose` or `-v`: Displays all failing tests [bold cyan]grouped by their Odoo module/addon[/bold cyan] under bold headers.
  - `-vv` (Verboser Verbose): Displays failing test names [bold cyan]alongside their actual error messages or traceback summaries[/bold cyan] extracted from the logs!

[bold yellow]Examples:[/bold yellow]
  [bold green]odoo-wt runbot[/bold green]                    [dim]# Show CI card of current worktree branch[/dim]
  [bold green]odoo-wt runbot[/bold green] [cyan]-a[/cyan]                 [dim]# Force display the high-level CI table of all branches[/dim]
  [bold green]odoo-wt runbot[/bold green] [cyan]fix-paymob --verbose[/cyan]  [dim]# Show all failing tests of 'fix-paymob' grouped by module[/dim]
  [bold green]odoo-wt runbot[/bold green] [cyan]fix-paymob -vv[/cyan]        [dim]# Show all failing tests with their real traceback errors![/dim]
""",

    "reviews": """\
The [bold green]reviews[/bold green] command displays the linked Pull Requests and latest peer comments [bold cyan](PR-Focused View)[/bold cyan].

[bold yellow]Usage:[/bold yellow]
  [bold green]odoo-wt reviews[/bold green]                      Show PR reviews of the active branch (if inside a worktree)
  [bold green]odoo-wt reviews[/bold green] [cyan]<branch_name>[/cyan]         Show PR reviews of a specific branch from anywhere
  [bold green]odoo-wt reviews[/bold green] [cyan]\\[all/-a][/cyan]            Show PR reviews table of all local branches

[bold yellow]Description:[/bold yellow]
  A focused PR diagnostic command that displays linked community, enterprise, and upgrade
  Pull Requests on GitHub, alongside the last human review comment/approvals.
  
  By default, if run inside any worktree directory, it displays a detailed single-branch reviews card.
  To bypass this and force-display the global table of all branches, use the [bold cyan]'all'[/bold cyan] or [bold cyan]'-a'[/bold cyan] parameter.
  
  This command [bold cyan]skips any Runbot CI build checks[/bold cyan] and focuses exclusively on human peer feedback,
  allowing you to quickly see what adjustments are needed before your PR is approved.

[bold yellow]Context-Aware Directory Sensing:[/bold yellow]
  If you run this command inside any subdirectory of an active worktree folder (including 'odoo' or 'enterprise'),
  it automatically detects your path, resolves the full branch name, and prints its dedicated detailed PR reviews card.

[bold yellow]⚠️  GitHub CLI Authentication Required:[/bold yellow]
  This command relies on the GitHub CLI ('gh' tool) being installed, alive, and
  authenticated ('gh auth status') to fetch Pull Request links and human review comments.
  If you are not logged in, reviews and comments will be skipped gracefully.

[bold yellow]Examples:[/bold yellow]
  [bold green]odoo-wt reviews[/bold green]                   [dim]# Show PR reviews card of current worktree branch[/dim]
  [bold green]odoo-wt reviews[/bold green] [cyan]-a[/cyan]               [dim]# Force display the PR reviews table of all branches[/dim]
""",

    "create": """\
The [bold green]create[/bold green] subcommand explicitly opens the TUI pre-filled in the 'Creation' tab to deploy a new worktree.

[bold yellow]Usage:[/bold yellow]
  [bold green]odoo-wt create[/bold green] [cyan]<branch_name>[/cyan]

[bold yellow]Description:[/bold yellow]
  Analyzes the requested branch name using [bold cyan]Magic Fix branch decomposition[/bold cyan] to automatically detect the target Odoo version,
  description, developer suffix, and base remote. Then, launches the TUI Creator pre-filled and ready to scaffold.

[bold yellow]Examples:[/bold yellow]
  [bold green]odoo-wt create[/bold green] [cyan]master-crm_lead-pian[/cyan]
""",

    "open": """\
The [bold green]open[/bold green] subcommand directly changes your shell directory into an existing worktree.

[bold yellow]Usage:[/bold yellow]
  [bold green]odoo-wt open[/bold green] [cyan]<branch_name>[/cyan]

[bold yellow]Description:[/bold yellow]
  Searches your local worktrees for the best matching branch name. If found, unsets its core tracking branch,
  configures PWD and OLDPWD environment variables to keep your shell history in line, and directly swaps your shell directory.

[bold yellow]Examples:[/bold yellow]
  [bold green]odoo-wt open[/bold green] [cyan]master-crm_lead-pian[/cyan]
""",

    "code": """\
The [bold green]code[/bold green] subcommand directly opens VS Code inside an existing worktree.

[bold yellow]Usage:[/bold yellow]
  [bold green]odoo-wt code[/bold green] [cyan]<branch_name>[/cyan]

[bold yellow]Description:[/bold yellow]
  Locates the matching worktree directory and invokes the VS Code 'code' binary on that path. It automatically
  ensures Odoo core and Enterprise folders are correctly mapped inside your launch configuration.

[bold yellow]Examples:[/bold yellow]
  [bold green]odoo-wt code[/bold green] [cyan]master-crm_lead-pian[/cyan]
""",

    "delete": """\
The [bold green]{subcommand}[/bold green] subcommand directly deletes a local worktree directory.

[bold yellow]Usage:[/bold yellow]
  [bold green]odoo-wt {subcommand}[/bold green] [cyan]<branch_name>[/cyan]

[bold yellow]Description:[/bold yellow]
  Locates the matching worktree directory, cleanly unregisters the worktree from Git's metadata database,
  and deletes the physical folder from your disk. A safety confirmation prompt is shown before taking any action.

[bold yellow]Examples:[/bold yellow]
  [bold green]odoo-wt {subcommand}[/bold green] [cyan]master-crm_lead-pian[/cyan]
""",

    "list": """\
The [bold green]list[/bold green] subcommand simply lists all registered local worktree branch names.

[bold yellow]Usage:[/bold yellow]
  [bold green]odoo-wt list[/bold green]

[bold yellow]Description:[/bold yellow]
  Prints a bare, unformatted list of all local worktree names, sorted by recency, one branch per line.
  This command is highly optimized for scripting, auto-completions, and pipeline utilities.
"""
}

SUBCOMMAND_HELP["rm"] = SUBCOMMAND_HELP["delete"]
