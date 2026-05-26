import json
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll, Center
from textual.widgets import Header, Footer, Select, Input, Label, Button, TabbedContent, TabPane, DataTable, Static, Checkbox, Switch
from textual import on, work
from textual.events import Paste, Key, DescendantFocus
from textual.binding import Binding
from spellchecker import SpellChecker
from rich.text import Text
from rich.style import Style

spell = SpellChecker()
spell.word_frequency.load_words(['odoo', 'saas', 'erp', 'mrp', 'pos', 'crm', 'wt', 'api', 'ui', 'ux', 'db', 'sql', 'backend', 'frontend', 'js', 'py', 'xml', 'owl', 'mac', 'linux', 'windows', 'repo'])

from .app_config import config_mgr
from .system_discovery import discover_system_data, get_remote, run_git, decompose_branch
from .custom_screens import DeleteConfirmScreen, DeployScreen, LogDetailScreen

SETTINGS_HELP = {
    "set-wt": "The base directory where all your WorkTrees will be created.",
    "set-env": "Where the centralized UV virtual environments will be stored.",
    "set-suffix": "Your default developer quadrigram (e.g., 'pian') used as a branch suffix.",
    "set-remote": "The name of the git remote pointing to your personal Odoo fork.",
    "set-py-v": "The default Python version used when creating new UV environments.",
    "set-comm": "The name of the community folder inside a worktree (default: 'odoo').",
    "set-ent": "The name of the enterprise folder inside a worktree (default: 'enterprise').",
    "set-default-tab": "Which tab to open by default when the app starts.",
    "set-ig-v": "Comma-separated list of versions to hide from the creation dropdowns.",
    "set-ig-s": "Comma-separated list of suffixes to hide from the creation dropdowns.",
    "set-whitelist": "Comma-separated list of unrecognized words to ignore permanently.",
    "set-show-prefix": "Toggle visibility of the version dropdown in the Creation tab.",
    "set-show-suffix": "Toggle visibility of the suffix dropdown in the Creation tab.",
    "set-show-desc": "Toggle visibility of the app description text at the top.",
    "set-dark-mode": "Toggle between dark and light themes.",
    "set-config-path": "Moving this will migrate your config file to a new location.",
    "set-log-path": "Moving this will migrate your log file to a new location.",
}

class OdooWtApp(App):
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "stylesheet.tcss"

    BINDINGS = [
        Binding("ctrl+s", "submit", "Create", key_display="^S"),
        Binding("ctrl+x", "delete_wt", "Delete", key_display="^X"),
        Binding("ctrl+r", "refresh", "Refresh/Reset", key_display="^R"),
        Binding("ctrl+t", "next_tab", "Tab", key_display="^T"),
        Binding("ctrl+tab", "next_tab", "", show=False),
        Binding("c", "copy_text", "Copy", key_display="C"),
        Binding("escape", "quit", "", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True, key_display="^Q"),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(self, config, v_list, s_list, worktrees, version_str="dev"):
        super().__init__()
        self.config = config
        self.app_version = version_str
        
        # Track usage and auto-hide description at 18th launch
        use_count = self.config.get("use_count", 0) + 1
        self.config["use_count"] = use_count
        if use_count == 18:
            self.config["show_desc"] = False
        
        ig_v = set(config.get("ignored_versions", []))
        ig_s = set(config.get("ignored_suffixes", []))
        
        self.v_list = [v for v in v_list if v not in ig_v or v in ("none", "custom...")]
        if not self.v_list: self.v_list = ["custom..."]
        
        self.s_list = [s for s in s_list if s not in ig_s or s in ("none", "custom...")]
        if not self.s_list: self.s_list = ["custom..."]
        
        self.worktrees = worktrees
        self.fetched_versions = set()
        self.deleting_paths = set()
        self.branch_status = ""
        self.check_results_str = ""
        self.save_timer = None

        # Modern Textual Theme API
        is_dark = self.config.get("dark_mode", True)
        self.theme = "textual-dark" if is_dark else "textual-light"

    def get_footer_text(self) -> str:
        try:
            active_tab = self.query_one("#tabs").active
        except Exception:
            active_tab = "tab-create"
            
        parts = ["^S Create", "^X Delete", "^R Refresh", "^T Tab", "^Q Quit"]
        if active_tab == "tab-manage":
            parts.append("Enter Open")
        return "  ".join(parts)

    @on(DescendantFocus)
    def on_descendant_focus(self, event: DescendantFocus) -> None:
        try:
            help_bar = self.query_one("#global-help-bar", Static)
            active_tab = self.query_one("#tabs").active
            shortcuts = self.get_footer_text()
            
            if active_tab != "tab-settings":
                help_bar.update(shortcuts)
                return
            
            # Find help text in our global dictionary based on widget ID
            curr = event.widget
            help_text = None
            while curr and curr != self:
                if curr.id and curr.id in SETTINGS_HELP:
                    help_text = SETTINGS_HELP[curr.id]
                    break
                curr = curr.parent
            
            if help_text:
                help_bar.update(f"[bold cyan]Info:[/bold cyan] {help_text}\n{shortcuts}")
            else:
                help_bar.update(f"[bold cyan]Info:[/bold cyan] Navigate inputs to see descriptions.\n{shortcuts}")
        except Exception as e:
            import traceback
            config_mgr.append_log("Non-crashing UI error", {"error": str(e), "trace": traceback.format_exc()})

    @on(Key)
    def handle_global_keys(self, event: Key) -> None:
        try:
            active_tab = self.query_one("#tabs").active
            focused = self.focused
            
            # Priority Shortcut: Always delete on Manage tab with Ctrl+X, even if search is focused
            if active_tab == "tab-manage" and event.key == "ctrl+x":
                self.action_delete_wt()
                event.stop()
                event.prevent_default()
                return

            # 1. Search Navigation Proxy (Existing Tab)
            if focused and focused.id == "wt-search" and event.key in ("down", "up", "enter"):
                table = self.query_one("#wt-table", DataTable)
                if table.row_count > 0:
                    if event.key == "down":
                        table.action_cursor_down()
                        event.prevent_default()
                    elif event.key == "up":
                        table.action_cursor_up()
                        event.prevent_default()
                    elif event.key == "enter":
                        table.action_select_cursor()
                        event.prevent_default()
                return

            # 2. Settings Tab Navigation overrides (prevent inputs from swallowing arrows)
            if active_tab == "tab-settings":
                if event.key == "up":
                    self.screen.focus_previous()
                    event.prevent_default()
                elif event.key == "down":
                    self.screen.focus_next()
                    event.prevent_default()
                elif event.key == "pageup":
                    container = self.query_one(".settings-container", VerticalScroll)
                    container.scroll_page_up()
                    event.prevent_default()
                elif event.key == "pagedown":
                    container = self.query_one(".settings-container", VerticalScroll)
                    container.scroll_page_down()
                    event.prevent_default()
        except Exception as e:
            import traceback
            config_mgr.append_log("Non-crashing UI error", {"error": str(e), "trace": traceback.format_exc()})

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            with Horizontal(id="top-bar"):
                with Vertical(id="title-container"):
                    yield Label(f"Odoo WorkTree Tool v{self.app_version}", classes="title")
                    yield Label("Opinionated tool for Odoo development. Creates/removes WorkTrees\nreusing UV environments per Odoo version.", id="app-desc", classes="description")
                yield Button("X", id="btn-close-app", classes="close-btn")
            yield Label("")
            with TabbedContent(id="tabs"):
                with TabPane("Creation", id="tab-create"):
                    yield Label("What branch do you need?", classes="tab-description")

                    with Horizontal(classes="main-row"):
                        with Vertical(id="version-col"):
                            yield Select(((v, v) for v in self.v_list), value=self.v_list[0] if self.v_list else None, id="version", allow_blank=False)
                            yield Input(id="custom_version", classes="custom-field")

                        yield Label("-", classes="dash")

                        with Vertical(id="desc-col"):
                            yield Input(placeholder="fix_bug", id="desc")

                        yield Label("-", classes="dash")

                        with Vertical(id="suffix-col"):
                            yield Select(((s, s) for s in self.s_list), value=self.s_list[0] if self.s_list else None, id="suffix", allow_blank=False)
                            yield Input(id="custom_suffix", classes="custom-field")

                    with Center():
                        yield Button("✨ Magic Fix", id="magic-btn", classes="mini-btn hidden")

                    yield Label(
                        "Deployment Strategy (Surgical Safety):\n"
                        "1. Remote Check: Tries to pull the exact branch from your remote (e.g., odoo-dev).\n"
                        "2. Local Check: If it's not on your remote, it checks your local .git folder.\n"
                        "3. Fresh Start: If neither exist, creates a new branch from the official base version.",
                        classes="strategy-desc",
                        id="strategy-label"
                    )
                    yield Label("", id="dynamic-summary", classes="summary-box")
                    with Horizontal(classes="btn-row"):
                        yield Button("Create ⏎", variant="success", id="submit-btn")
                with TabPane("Manage", id="tab-manage"):
                    yield Label("Discovery: Scans 'Worktree Root Path' (in Settings)\nfor 'odoo/.git' folders. [bold cyan]Hint: Double-click or press Enter on a row to open in terminal.[/bold cyan]", classes="tab-description")
                    with Horizontal(classes="manage-top-row"):
                        yield Input(placeholder="Fuzzy search...", id="wt-search", classes="search-input")
                        yield Button("Open", variant="success", id="open-btn", classes="mini-btn")
                        yield Button("Refresh", id="refresh-btn", classes="mini-btn")
                        yield Button("Delete ^X", variant="error", id="delete-btn", classes="mini-btn")
                    yield DataTable(id="wt-table", cursor_type="row")
                with TabPane("Settings", id="tab-settings"):
                    yield Input(placeholder="Fuzzy search settings... (e.g. 'log', 'dark', 'path')", id="settings-search", classes="search-input")
                    with VerticalScroll(classes="settings-container"):
                        with Horizontal(classes="setting-item"):
                            yield Label("Worktree Root:", classes="setting-label")
                            yield Input(value=self.config.get("wt_root", ""), id="set-wt", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("UV Envs Path:", classes="setting-label")
                            yield Input(value=self.config.get("env_root", ""), id="set-env", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Default Suffix:", classes="setting-label")
                            yield Input(value=self.config.get("suffix", ""), id="set-suffix", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Dev Remote (Fork):", classes="setting-label")
                            yield Input(value=self.config.get("remote_name", "odoo-dev"), id="set-remote", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Python Version:", classes="setting-label")
                            yield Input(value=self.config.get("python_version", "3.12"), id="set-py-v", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Community Dir:", classes="setting-label")
                            yield Input(value=self.config.get("community_dir", "odoo"), id="set-comm", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Enterprise Dir:", classes="setting-label")
                            yield Input(value=self.config.get("enterprise_dir", "enterprise"), id="set-ent", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Start in Manage Tab:", classes="setting-label")
                            yield Switch(value=(self.config.get("default_tab", "tab-create") == "tab-manage"), id="set-default-tab", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Removed Versions:", classes="setting-label")
                            yield Input(value=",".join(self.config.get("ignored_versions", [])), id="set-ig-v", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Removed Suffixes:", classes="setting-label")
                            yield Input(value=",".join(self.config.get("ignored_suffixes", [])), id="set-ig-s", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Typos Whitelist:", classes="setting-label")
                            yield Input(value=",".join(self.config.get("ignored_typos", [])), id="set-whitelist", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Show Prefix (Version):", classes="setting-label")
                            yield Switch(value=self.config.get("show_prefix", True), id="set-show-prefix", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Show Suffix:", classes="setting-label")
                            yield Switch(value=self.config.get("show_suffix", True), id="set-show-suffix", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Show Description:", classes="setting-label")
                            yield Switch(value=self.config.get("show_desc", True), id="set-show-desc", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Auto Magic Fix:", classes="setting-label")
                            yield Switch(value=self.config.get("auto_magic_fix", True), id="set-auto-magic", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Dark Mode:", classes="setting-label")
                            yield Switch(value=self.config.get("dark_mode", True), id="set-dark-mode", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Config Path:", classes="setting-label")
                            yield Input(value=self.config.get("config_path", ""), id="set-config-path", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Log Path:", classes="setting-label")
                            yield Input(value=self.config.get("log_path", ""), id="set-log-path", classes="setting-input")
                with TabPane("Logs", id="tab-logs"):
                    yield Label("System Logs (Newest first)", classes="tab-description")
                    yield DataTable(id="logs-table", cursor_type="row")
                    with Horizontal(classes="btn-row"):
                        yield Button("Refresh", id="refresh-logs-btn")
                        yield Button("Clear Logs", variant="error", id="clear-logs-btn")
        
        # Replace Footer with our custom global help bar
        yield Static("^S Create  ^X Delete  ^R Refresh  ^T Tab  ^Q Quit", id="global-help-bar", classes="help-bar")

    def on_mount(self) -> None:
        config_mgr.append_log("App Started")
        
        default_tab = self.config.get("default_tab", "tab-create")
        try:
            self.query_one("#tabs", TabbedContent).active = default_tab
            if default_tab == "tab-manage":
                self.query_one("#wt-search").focus()
            elif default_tab == "tab-settings":
                self.query_one("#settings-search").focus()
            else:
                self.query_one("#desc").focus()
        except Exception as e:
            self.query_one("#desc").focus()
            config_mgr.append_log("on_mount focus error", {"error": str(e)})

        self.apply_visibility_settings()
        self.populate_table()
        self.populate_logs_table()
        self.update_summary()
        v_sel = self.query_one("#version", Select).value
        if v_sel and str(v_sel) != "custom...":
            self.background_fetch(str(v_sel))

    def apply_visibility_settings(self):
        prefix_col = self.query_one("#version-col")
        suffix_col = self.query_one("#suffix-col")
        app_desc = self.query_one("#app-desc")
        
        prefix_col.display = self.config.get("show_prefix", True)
        suffix_col.display = self.config.get("show_suffix", True)
        app_desc.display = self.config.get("show_desc", True)

    @work(exclusive=True, thread=True)
    async def background_fetch(self, version: str) -> None:
        if not version or version == "none" or version in self.fetched_versions:
            return
        wt_root = Path(self.config["wt_root"]).expanduser().absolute()
        base_odoo = wt_root / "master" / "odoo"
        base_ent = wt_root / "master" / "enterprise"
        if not base_odoo.exists(): return
        config_mgr.append_log("Background Fetch Started", {"version": version})
        
        def fetch_task(args):
            repo, label = args
            try:
                remote = get_remote(repo)
                config_mgr.append_log(f"Prefetch {label} Started", {"version": version, "remote": remote})
                run_git(["fetch", remote, version], cwd=repo)
                config_mgr.append_log(f"Prefetch {label} Finished", {"version": version, "remote": remote})
            except Exception as e:
                config_mgr.append_log(f"Prefetch {label} Failed", {"version": version, "error": str(e)})

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(fetch_task, [(base_odoo, "Community"), (base_ent, "Enterprise")]))
            
        self.fetched_versions.add(version)
        config_mgr.append_log("Background Fetch Finished", {"version": version})

    @on(Paste)
    def on_paste(self, event: Paste) -> None:
        try:
            focused = self.focused
            if focused and focused.id == "desc":
                self.query_one("#version", Select).value = "none"
                self.query_one("#suffix", Select).value = "none"
                self.notify("Paste detected: Version and Suffix unset.", timeout=3)
        except Exception as e:
            import traceback
            config_mgr.append_log("Non-crashing UI error", {"error": str(e), "trace": traceback.format_exc()})

    @on(TabbedContent.TabActivated, "#tabs")
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tabs = self.query_one("#tabs")
        active_pane = tabs.active
        config_mgr.append_log("Tab Changed", {"tab": active_pane})
        
        if active_pane == "tab-create":
            self.query_one("#desc").focus()
        elif active_pane == "tab-manage":
            self.query_one("#wt-search").focus()
        elif active_pane == "tab-settings":
            self.query_one("#settings-search").focus()
        elif active_pane == "tab-logs":
            self.populate_logs_table()
            self.query_one("#logs-table").focus()
            
        self.app.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        try:
            active_pane = self.query_one("#tabs").active
        except Exception:
            active_pane = "tab-create"

        if action == "submit":
            return active_pane == "tab-create"
        if action == "delete_wt":
            return active_pane == "tab-manage"
        if action == "refresh":
            return active_pane != "tab-create"
        return True

    def update_summary(self) -> None:
        try:
            v_sel = self.query_one("#version", Select).value
            version = self.query_one("#custom_version", Input).value if str(v_sel) == "custom..." else str(v_sel)
            desc = self.query_one("#desc", Input).value
            s_sel = self.query_one("#suffix", Select).value
            suffix = self.query_one("#custom_suffix", Input).value if str(s_sel) == "custom..." else str(s_sel)
            
            if version == "none" or version == Select.BLANK: version = ""
            if suffix == "none" or suffix == Select.BLANK: suffix = ""
            clean_desc = str(desc).strip().replace(" ", "_")
            parts = [p for p in [version, clean_desc, suffix] if p]
            branch_name = "-".join(parts)
            if not branch_name: branch_name = "<empty>"
            wt_root_raw = self.config.get("wt_root", "")
            wt_root = str(Path(wt_root_raw).expanduser().absolute())
            remote = self.config.get("remote_name", "odoo-dev")
            base_v = version if version else "master"
            comm_dir = self.config.get("community_dir", "odoo")
            ent_dir = self.config.get("enterprise_dir", "enterprise")
            
            # Update Strategy Text
            is_base_branch = (branch_name == base_v)
            strategy_label = self.query_one("#strategy-label", Label)
            if is_base_branch:
                strategy_label.update(
                    "[bold magenta]Deployment Strategy (Base Branch Safety):[/bold magenta]\n"
                    f"You requested a pure base branch ('{base_v}').\n"
                    "odoo-wt will completely [bold]bypass your dev remote[/bold] to ensure you\n"
                    "fetch the pristine, official branch directly from the base Odoo repo."
                )
            else:
                strategy_label.update(
                    "[bold cyan]Deployment Strategy (Surgical Safety):[/bold cyan]\n"
                    f"1. Remote Check: Tries to pull the exact branch from your remote (e.g., {remote}).\n"
                    "2. Local Check: If it's not on your remote, it checks your local .git folder.\n"
                    "3. Fresh Start: If neither exist, creates a new branch from the official base version."
                )

            # Build Summary using Rich Text for complex interactivity
            summary = Text()
            summary.append("Outcome:", style="bold")
            
            if self.check_results_str:
                summary.append("\n")
                summary.append_text(Text.from_markup(f"[bright_black]{self.check_results_str}[/bright_black]"))
                summary.append("\n")
            else:
                summary.append("\n")

            # 1. Branch Status Line
            summary.append("1. ", style="")
            summary.append("Branch Status: ", style="bold cyan")
            
            # Use self.branch_status which can be markup (like Checking...)
            if isinstance(self.branch_status, str):
                summary.append_text(Text.from_markup(self.branch_status or "Ready..."))
            else:
                summary.append_text(self.branch_status)

            # 2. Directory Line
            summary.append(f"\n2. I will create a new directory at ")
            summary.append(f"{wt_root}/{branch_name}", style="bold green")
            summary.append(":\n")
            summary.append(f"   ├── {comm_dir}/       ", style="")
            summary.append("(Community worktree)", style="bright_black")
            summary.append(f"\n   └── {ent_dir}/ ", style="")
            summary.append("(Enterprise worktree)", style="bright_black")
            
            # 3. UV Line
            summary.append(f"\n3. I will use or create the ")
            summary.append(f"{base_v}", style="bold magenta")
            summary.append(" UV environment and link it as '.venv'.")

            self.query_one("#dynamic-summary", Label).update(summary)
        except Exception as e:
            import traceback
            config_mgr.append_log("Non-crashing UI error", {"error": str(e), "trace": traceback.format_exc()})

    @on(Input.Changed, "#desc")
    @on(Input.Changed, "#custom_version")
    @on(Input.Changed, "#custom_suffix")
    @on(Select.Changed, "#version")
    @on(Select.Changed, "#suffix")
    def on_selection_changed(self, event) -> None: 
        self.check_results_str = ""
        self.branch_status = ""
        self.update_summary()
        self.check_branch_existence_task()

    @work(exclusive=True)
    async def check_branch_existence_task(self) -> None:
        try:
            v_sel = self.query_one("#version", Select).value
            version = self.query_one("#custom_version", Input).value if str(v_sel) == "custom..." else str(v_sel)
            desc = self.query_one("#desc", Input).value
            s_sel = self.query_one("#suffix", Select).value
            suffix = self.query_one("#custom_suffix", Input).value if str(s_sel) == "custom..." else str(s_sel)
            
            if not desc:
                self.branch_status = ""
                self.check_results_str = ""
                self.update_summary()
                return

            clean_desc = str(desc).strip().replace(" ", "_")
            parts = [p for p in [version if version != "none" else "", clean_desc, suffix if suffix != "none" else ""] if p]
            branch_name = "-".join(parts)
            
            if any(w['name'] == branch_name for w in self.worktrees):
                self.branch_status = "[bold red]A WORKTREE WITH THIS NAME ALREADY EXISTS![/bold red]"
                self.check_results_str = ""
                self.update_summary()
                return
            
            self.branch_status = "Checking..."
            self.check_results_str = ""
            self.update_summary()
            
            await asyncio.sleep(0.5) # Debounce

            wt_root = Path(self.config["wt_root"]).expanduser().absolute()
            base_odoo = wt_root / "master" / "odoo"
            base_ent = wt_root / "master" / "enterprise"
            dev_remote = self.config.get("remote_name", "odoo-dev")

            from .system_discovery import check_local, check_remote, get_remote
            main_remote = await asyncio.to_thread(get_remote, base_odoo)

            # Animation & Checklist Logic
            checks = [
                {"name": "Local Community", "path": base_odoo, "type": "local"},
                {"name": "Local Enterprise", "path": base_ent, "type": "local"},
                {"name": f"Dev ({dev_remote}) Community", "path": base_odoo, "type": "remote", "remote": dev_remote},
                {"name": f"Dev ({dev_remote}) Enterprise", "path": base_ent, "type": "remote", "remote": dev_remote},
                {"name": f"Main ({main_remote}) Community", "path": base_odoo, "type": "remote", "remote": main_remote},
                {"name": f"Main ({main_remote}) Enterprise", "path": base_ent, "type": "remote", "remote": main_remote},
            ]
            
            results = {}
            is_local = False
            is_remote = False
            found_remote_name = ""

            # 1. Local Checks (Sequential & Fast)
            for i in range(2):
                check = checks[i]
                if not check["path"].exists():
                    results[check["name"]] = "skip"
                    continue
                
                self.branch_status = "Checking local..."
                self.check_results_str = self._build_checklist(checks, results) + f" [yellow]→[/yellow] {check['name']}"
                self.update_summary()
                
                found = await asyncio.to_thread(check_local, check["path"], branch_name)
                if found:
                    is_local = True
                    results[check["name"]] = "ok"
                    break
                results[check["name"]] = "fail"
            
            # 2. Remote Checks (Parallel & Networked)
            if not is_local:
                remote_checks = []
                for i in range(2, 6):
                    check = checks[i]
                    if check["path"].exists():
                        remote_checks.append(check)
                    else:
                        results[check["name"]] = "skip"

                if remote_checks:
                    async def run_one_remote(c):
                        try:
                            r = c.get("remote", dev_remote)
                            # Add a 10s timeout to git ls-remote to prevent hanging
                            found = await asyncio.wait_for(asyncio.to_thread(check_remote, c["path"], branch_name, r), timeout=10.0)
                            return c["name"], "ok" if found else "fail", r
                        except asyncio.TimeoutError:
                            return c["name"], "fail", c.get("remote", dev_remote)
                        except Exception as e:
                            config_mgr.append_log("Remote Check Error", {"name": c["name"], "error": str(e)})
                            return c["name"], "fail", c.get("remote", dev_remote)

                    pending_tasks = [asyncio.create_task(run_one_remote(c)) for c in remote_checks]
                    
                    dot_count = 0
                    start_time = asyncio.get_event_loop().time()
                    while pending_tasks:
                        # Wait for any task to finish
                        done, pending = await asyncio.wait(pending_tasks, timeout=0.2, return_when=asyncio.FIRST_COMPLETED)
                        pending_tasks = list(pending)
                        
                        for task in done:
                            try:
                                name, res, r_name = task.result()
                                results[name] = res
                            except Exception as e:
                                config_mgr.append_log("Task Result Error", {"error": str(e)})
                        
                        # Update UI animation
                        dot_count = (dot_count + 1) % 4
                        self.branch_status = f"Checking remotes{'.' * (dot_count + 1)}"
                        active_check = next((c["name"] for c in remote_checks if c["name"] not in results), "Finishing...")
                        self.check_results_str = self._build_checklist(checks, results) + (f" [yellow]→[/yellow] {active_check}" if pending_tasks else "")
                        self.update_summary()

                        # Absolute safety break (30s)
                        if asyncio.get_event_loop().time() - start_time > 30:
                            config_mgr.append_log("Discovery Timeout", {"msg": "Forced break after 30s"})
                            for t in pending_tasks: t.cancel()
                            break

                    # Pick the highest priority remote result
                    for i in range(2, 6):
                        c_name = checks[i]["name"]
                        if results.get(c_name) == "ok":
                            is_remote = True
                            found_remote_name = checks[i].get("remote", dev_remote)
                            break

            # Final results string for the outcome block
            self.check_results_str = self._build_checklist(checks, results)

            # Spell Check & Validation
            words = [w for w in branch_name.replace("-", "_").split("_") if w]
            
            # Words to definitely ignore
            tech_terms = set(self.config.get("technical_terms", []))
            user_ignored = set(self.config.get("ignored_typos", []))
            cfg_suffix = self.config.get("suffix", "")
            system_ignore = {version, suffix, cfg_suffix, "none", "master", ""}
            
            unknown = spell.unknown([w for w in words if w not in system_ignore and w not in tech_terms and w not in user_ignored])
            unknown = {w for w in unknown if not w.isnumeric() and len(w) > 2}
            
            # Build final status using Rich Text
            status_text = Text()
            if is_local:
                status_text.append(f"Found branch '{branch_name}' locally.", style="bold yellow")
            elif is_remote:
                status_text.append(f"Found branch on '{found_remote_name}'.", style="bold green")
            else:
                status_text.append("New branch will be created.", style="bold white")
            
            warnings_text = Text()
            warn_list = []
            
            # 1. Typos with hover tooltips (using Textual's way of handling tooltips if possible, or just text)
            if unknown:
                typo_part = Text("Typo? ", style="bold red")
                for i, w in enumerate(sorted(list(unknown))):
                    if i > 0: typo_part.append(", ", style="bold red")
                    # We'll use a simpler markup for now to avoid crashes, 
                    # and rely on the fact that these are clickable blue links.
                    # To show tooltips in Textual for specific regions, we'd need a more complex setup,
                    # so for now we just make them look like buttons.
                    typo_part.append(w, style=Style(underline=True, color="blue", meta={"@click": f"app.ignore_typo('{w}')"}))
                warn_list.append(typo_part)
            
            # 2. Repeated words check
            seen_words = set()
            repeated = []
            for w in words:
                if not w or len(w) < 3: continue
                if w in seen_words:
                    repeated.append(w)
                seen_words.add(w)
            if repeated:
                warn_list.append(Text(f"Repeated: {', '.join(repeated)}", style="bold red"))
            
            # 3. Invalid characters check
            if ":" in branch_name:
                warn_list.append(Text("Found ':' (Github paste?)", style="bold red"))
            
            # 4. Smart Paste & Magic Fix
            needs_magic = ":" in branch_name or repeated
            magic_btn = self.query_one("#magic-btn")
            
            if needs_magic:
                if self.config.get("auto_magic_fix", True):
                    # Only auto-fix once to prevent loops
                    if not getattr(self, "_magic_fixing", False):
                        self._magic_fixing = True
                        self.action_magic_fix()
                        self._magic_fixing = False
                        return
                
                magic_btn.remove_class("hidden")
                warn_list.append(Text("Magic Fix?", style=Style(underline=True, color="blue", meta={"@click": "app.magic_fix"})))
            else:
                magic_btn.add_class("hidden")

            if warn_list:
                status_text.append(" (", style="bold red")
                for i, w_text in enumerate(warn_list):
                    if i > 0: status_text.append("; ", style="bold red")
                    status_text.append_text(w_text)
                status_text.append(")", style="bold red")

            self.branch_status = status_text
            self.update_summary()
        except Exception as e:
            import traceback
            config_mgr.append_log("Non-crashing UI error", {"error": str(e), "trace": traceback.format_exc()})

    def _build_checklist(self, checks, results) -> str:
        parts = []
        for c in checks:
            res = results.get(c["name"])
            if res == "ok": parts.append(f"[green]✓[/green] {c['name']}")
            elif res == "fail": parts.append(f"[red]✗[/red] {c['name']}")
        return " ".join(parts)

    @on(Input.Submitted, "#desc")
    @on(Input.Submitted, "#custom_version")
    @on(Input.Submitted, "#custom_suffix")
    def on_input_submitted(self, event) -> None:
        config_mgr.append_log("Enter Key Pressed", {"input": event.control.id})
        self.action_submit()

    def populate_logs_table(self) -> None:
        import datetime
        table = self.query_one("#logs-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Time", "Action", "Details")
        
        def relative_time(iso_str):
            if not iso_str: return "unknown"
            try:
                dt = datetime.datetime.fromisoformat(iso_str)
                diff = datetime.datetime.now() - dt
                secs = diff.total_seconds()
                if secs < 60: return f"{int(secs)} sec ago"
                elif secs < 3600: return f"{int(secs//60)} min ago"
                elif secs < 86400: return f"{int(secs//3600)} hours ago"
                else: return f"{int(secs//86400)} days ago"
            except ValueError:
                return iso_str

        if config_mgr.log_file.exists():
            try:
                with open(config_mgr.log_file, "r") as f:
                    lines = f.readlines()
                for line in reversed(lines):
                    if not line.strip(): continue
                    data = json.loads(line)
                    ts = data.get("timestamp", "")
                    rt = relative_time(ts)
                    details_str = json.dumps(data.get("details", {}))
                    table.add_row(rt, data.get("action", ""), details_str)
            except (OSError, IOError, json.JSONDecodeError) as e:
                config_mgr.append_log("Log table parsing error", {"error": str(e)})

    @on(Button.Pressed, "#refresh-logs-btn")
    def on_refresh_logs(self):
        self.populate_logs_table()
        self.notify("Logs refreshed!")

    @on(DataTable.RowSelected, "#logs-table")
    def on_log_row_selected(self, event: DataTable.RowSelected) -> None:
        row = event.data_table.get_row(event.row_key)
        self.app.push_screen(LogDetailScreen(row[0], row[1], row[2]))

    @on(Button.Pressed, "#clear-logs-btn")
    def on_clear_logs(self):
        if config_mgr.log_file.exists():
            config_mgr.log_file.unlink()
        self.populate_logs_table()
        self.notify("Logs cleared!")

    def _version_sort_key(self, wt_dict):
        v = wt_dict["version"]
        if v == "master": return (999, 999)
        # Parse version strings like "17.0", "saas-17.1"
        try:
            num_part = v.replace("saas-", "")
            parts = num_part.split(".")
            major = int(parts[0]) if parts else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            # Put saas branches slightly ahead of their base version
            is_saas = 1 if "saas-" in v else 0
            return (major, minor, is_saas)
        except Exception:
            return (0, 0, 0)

    def populate_table(self):
        table = self.query_one("#wt-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Branch Name", "Version")
        
        try:
            search_term = self.query_one("#wt-search", Input).value.lower()
        except Exception:
            search_term = ""

        # Sort by parsed version (descending), then by name
        sorted_wts = sorted(self.worktrees, key=lambda x: (self._version_sort_key(x), x["name"]), reverse=True)

        for wt in sorted_wts:
            name = wt["name"]
            path = wt["path"]
            
            # Fuzzy match
            if search_term and search_term not in name.lower():
                continue

            if path in self.deleting_paths:
                name = f"[strike]{name}[/strike] [bold red](Deleting...)[/bold red]"
            table.add_row(name, wt["version"], key=path)

    @on(Input.Changed, "#wt-search")
    def on_wt_search_changed(self, event: Input.Changed) -> None:
        self.populate_table()

    @on(Input.Changed, "#settings-search")
    def on_settings_search_changed(self, event: Input.Changed) -> None:
        search_terms = event.value.lower().split()
        for item in self.query(".setting-item"):
            try:
                # Aggregate searchable text
                labels = " ".join([l.render().plain.lower() if hasattr(l.render(), "plain") else str(l.render()).lower() for l in item.query(Label)])
                inputs = item.query("Input, Switch, Select, Checkbox")
                val_text = ""
                help_text = ""
                
                if inputs:
                    first = inputs.first()
                    if hasattr(first, "value"):
                        val_text = str(first.value).lower()
                    if first.id and first.id in SETTINGS_HELP:
                        help_text = SETTINGS_HELP[first.id].lower()
                        
                combined = f"{labels} {val_text} {help_text}"
                item.display = all(t in combined for t in search_terms)
            except Exception as e:
                import traceback
                config_mgr.append_log("Settings Search Error", {"error": str(e), "traceback": traceback.format_exc()})

    @on(DataTable.RowSelected, "#wt-table")
    def on_wt_row_selected(self, event: DataTable.RowSelected) -> None:
        path = str(event.row_key.value)
        config_mgr.append_log("Worktree Selected (Action)", {"path": path})
        self.exit({"action": "terminal", "path": path})

    def action_reset_settings(self) -> None:
        self.config = config_mgr.load()
        self.query_one("#set-wt", Input).value = self.config.get("wt_root", "")
        self.query_one("#set-env", Input).value = self.config.get("env_root", "")
        self.query_one("#set-suffix", Input).value = self.config.get("suffix", "")
        self.query_one("#set-remote", Input).value = self.config.get("remote_name", "odoo-dev")
        self.query_one("#set-py-v", Input).value = self.config.get("python_version", "3.12")
        self.query_one("#set-comm", Input).value = self.config.get("community_dir", "odoo")
        self.query_one("#set-ent", Input).value = self.config.get("enterprise_dir", "enterprise")
        self.query_one("#set-default-tab", Switch).value = (self.config.get("default_tab", "tab-create") == "tab-manage")
        self.query_one("#set-ig-v", Input).value = ",".join(self.config.get("ignored_versions", []))
        self.query_one("#set-ig-s", Input).value = ",".join(self.config.get("ignored_suffixes", []))
        self.query_one("#set-whitelist", Input).value = ",".join(self.config.get("ignored_typos", []))
        self.query_one("#set-config-path", Input).value = self.config.get("config_path", "")
        self.query_one("#set-log-path", Input).value = self.config.get("log_path", "")
        self.query_one("#set-show-prefix", Switch).value = self.config.get("show_prefix", True)
        self.query_one("#set-show-suffix", Switch).value = self.config.get("show_suffix", True)
        self.query_one("#set-show-desc", Switch).value = self.config.get("show_desc", True)
        self.query_one("#set-auto-magic", Switch).value = self.config.get("auto_magic_fix", True)
        
        is_dark = self.config.get("dark_mode", True)
        self.query_one("#set-dark-mode", Switch).value = is_dark
        self.theme = "textual-dark" if is_dark else "textual-light"
        
        self.apply_visibility_settings()
        self.notify("Settings reset to last saved state.")

    def action_refresh(self) -> None:
        active = self.query_one("#tabs").active
        if active == "tab-logs":
            self.populate_logs_table()
            self.notify("Logs refreshed!")
        elif active == "tab-manage":
            self.action_refresh_wts()
        elif active == "tab-settings":
            self.action_reset_settings()

    def action_refresh_wts(self) -> None:
        _, _, self.worktrees = discover_system_data(self.config["wt_root"], self.config["suffix"])
        self.populate_table()
        self.notify("Worktrees refreshed!")

    def action_quit(self) -> None:
        config_mgr.append_log("App Quit")
        self.exit()

    @on(Button.Pressed, "#magic-btn")
    def on_magic_btn_pressed(self) -> None:
        self.action_magic_fix()

    def action_magic_fix(self) -> None:
        """Cleans up pasted branch names (e.g., 'remote:v-desc-s') and updates UI."""
        try:
            desc_input = self.query_one("#desc", Input)
            raw_desc = desc_input.value
            
            remote, v, d, s = decompose_branch(raw_desc, self.v_list, self.s_list)
            
            flashed = False
            # If decompose found a version or suffix, update the selectors
            if v:
                v_sel = self.query_one("#version", Select)
                if v in self.v_list:
                    v_sel.value = v
                else:
                    v_sel.value = "custom..."
                    self.query_one("#custom_version", Input).value = v
                v_sel.add_class("magic-flash")
                self.set_timer(0.5, lambda: v_sel.remove_class("magic-flash"))
                flashed = True
                 
            if s:
                s_sel = self.query_one("#suffix", Select)
                if s in self.s_list:
                    s_sel.value = s
                else:
                    s_sel.value = "custom..."
                    self.query_one("#custom_suffix", Input).value = s
                s_sel.add_class("magic-flash")
                self.set_timer(0.5, lambda: s_sel.remove_class("magic-flash"))
                flashed = True
            
            if d != raw_desc:
                desc_input.value = d
                desc_input.add_class("magic-flash")
                self.set_timer(0.5, lambda: desc_input.remove_class("magic-flash"))
                flashed = True
            
            if flashed:
                if remote:
                    self.notify(f"✨ Magic Fix: Stripped remote '{remote}' and cleaned parts.", timeout=3)
                else:
                    self.notify("✨ Magic Fix: Cleaned redundant parts.", timeout=3)
                
            self.query_one("#magic-btn").add_class("hidden")
            self.update_summary()
            self.check_branch_existence_task()
            config_mgr.append_log("Magic Fix Applied", {"original": raw_desc, "new_desc": d, "version": v, "suffix": s})
        except Exception as e:
            self.notify(f"Magic Fix Error: {str(e)}", severity="error")
            config_mgr.append_log("Magic Fix Error", {"error": str(e)})

    def action_ignore_typo(self, word: str) -> None:
        """Adds a word to the ignored_typos list in config."""
        ignored = self.config.get("ignored_typos", [])
        if word not in ignored:
            ignored.append(word)
            self.config["ignored_typos"] = ignored
            config_mgr.save(self.config)
            config_mgr.append_log("Typo Ignored", {"word": word})
            self.update_summary()
            self.check_branch_existence_task()
            self.notify(f"Added '{word}' to ignored list.")

    def action_next_tab(self) -> None:
        config_mgr.append_log("Next Tab Shortcut Used")
        tabs = self.query_one("#tabs")
        if tabs.active == "tab-create": tabs.active = "tab-manage"
        elif tabs.active == "tab-manage": tabs.active = "tab-settings"
        elif tabs.active == "tab-settings": tabs.active = "tab-logs"
        else: tabs.active = "tab-create"

    def action_copy_text(self) -> None:
        try:
            active_pane = self.query_one("#tabs").active
        except Exception:
            return
            
        if active_pane == "tab-manage":
            table = self.query_one("#wt-table", DataTable)
            try:
                row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                path = str(row_key)
                self.app.copy_to_clipboard(path)
                self.notify(f"Copied to clipboard: {path}")
                config_mgr.append_log("Clipboard Copy", {"type": "worktree_path", "value": path})
            except Exception:
                self.notify("No worktree selected to copy.", severity="warning")
                
        elif active_pane == "tab-logs":
            table = self.query_one("#logs-table", DataTable)
            try:
                row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
                row = table.get_row(row_key)
                text = f"[{row[0]}] {row[1]}: {row[2]}"
                self.app.copy_to_clipboard(text)
                self.notify("Copied log entry to clipboard")
                config_mgr.append_log("Clipboard Copy", {"type": "log_entry"})
            except Exception:
                self.notify("No log selected to copy.", severity="warning")
                
        elif active_pane == "tab-create":
            v_sel = self.query_one("#version").value
            version = self.query_one("#custom_version").value if v_sel == "custom..." else v_sel
            desc = self.query_one("#desc").value
            s_sel = self.query_one("#suffix").value
            suffix = self.query_one("#custom_suffix").value if s_sel == "custom..." else s_sel
            
            if version == "none" or version == Select.BLANK: version = ""
            if suffix == "none" or suffix == Select.BLANK: suffix = ""
            clean_desc = str(desc).strip().replace(" ", "_")
            parts = [p for p in [version, clean_desc, suffix] if p]
            branch_name = "-".join(parts)
            
            if branch_name:
                self.app.copy_to_clipboard(branch_name)
                self.notify(f"Copied branch name: {branch_name}")
                config_mgr.append_log("Clipboard Copy", {"type": "branch_name", "value": branch_name})
            else:
                self.notify("No branch name to copy.", severity="warning")

    @on(Select.Changed, "#version")
    def version_changed(self, event: Select.Changed) -> None:
        config_mgr.append_log("Version Dropdown Changed", {"value": str(event.value)})
        custom = self.query_one("#custom_version")
        if event.value == "custom...":
            custom.add_class("visible")
            custom.focus()
        else:
            custom.remove_class("visible")
            if event.value and event.value != "none":
                self.background_fetch(str(event.value))
        self.update_summary()

    @on(Select.Changed, "#suffix")
    def suffix_changed(self, event: Select.Changed) -> None:
        config_mgr.append_log("Suffix Dropdown Changed", {"value": str(event.value)})
        custom = self.query_one("#custom_suffix")
        if event.value == "custom...": custom.add_class("visible"); custom.focus()
        else: custom.remove_class("visible")
        self.update_summary()

    @on(Input.Changed, "#set-wt")
    @on(Input.Changed, "#set-env")
    @on(Input.Changed, "#set-suffix")
    @on(Input.Changed, "#set-remote")
    @on(Input.Changed, "#set-py-v")
    @on(Input.Changed, "#set-comm")
    @on(Input.Changed, "#set-ent")
    @on(Input.Changed, "#set-ig-v")
    @on(Input.Changed, "#set-ig-s")
    @on(Input.Changed, "#set-whitelist")
    @on(Input.Changed, "#set-config-path")
    @on(Input.Changed, "#set-log-path")
    @on(Switch.Changed, "#set-default-tab")
    @on(Switch.Changed, "#set-show-prefix")
    @on(Switch.Changed, "#set-show-suffix")
    @on(Switch.Changed, "#set-show-desc")
    @on(Switch.Changed, "#set-auto-magic")
    @on(Switch.Changed, "#set-dark-mode")
    def on_setting_changed(self, event) -> None:
        if self.is_mounted:
            # Immediate theme toggle
            if hasattr(event, "switch") and event.switch.id == "set-dark-mode":
                self.theme = "textual-dark" if event.value else "textual-light"

            if self.save_timer:
                self.save_timer.stop()
            self.save_timer = self.set_timer(0.5, self.save_settings_auto)

    def save_settings_auto(self) -> None:
        self.config["wt_root"] = self.query_one("#set-wt", Input).value
        self.config["env_root"] = self.query_one("#set-env", Input).value
        self.config["suffix"] = self.query_one("#set-suffix", Input).value
        self.config["remote_name"] = self.query_one("#set-remote", Input).value
        self.config["python_version"] = self.query_one("#set-py-v", Input).value
        self.config["community_dir"] = self.query_one("#set-comm", Input).value
        self.config["enterprise_dir"] = self.query_one("#set-ent", Input).value
        
        is_manage_tab = self.query_one("#set-default-tab", Switch).value
        self.config["default_tab"] = "tab-manage" if is_manage_tab else "tab-create"
        
        self.config["config_path"] = self.query_one("#set-config-path", Input).value
        self.config["log_path"] = self.query_one("#set-log-path", Input).value
        self.config["show_prefix"] = self.query_one("#set-show-prefix", Switch).value
        self.config["show_suffix"] = self.query_one("#set-show-suffix", Switch).value
        self.config["show_desc"] = self.query_one("#set-show-desc", Switch).value
        self.config["auto_magic_fix"] = self.query_one("#set-auto-magic", Switch).value
        self.config["dark_mode"] = self.query_one("#set-dark-mode", Switch).value

        ig_v = [v.strip() for v in self.query_one("#set-ig-v", Input).value.split(",") if v.strip()]
        ig_s = [s.strip() for s in self.query_one("#set-ig-s", Input).value.split(",") if s.strip()]
        ig_t = [t.strip() for t in self.query_one("#set-whitelist", Input).value.split(",") if t.strip()]
        self.config["ignored_versions"] = ig_v
        self.config["ignored_suffixes"] = ig_s
        self.config["ignored_typos"] = ig_t

        config_mgr.save(self.config)
        config_mgr.append_log("Settings Auto-Saved", self.config)
        self.notify("Settings saved automatically", timeout=2)
        
        self.apply_visibility_settings()
        self.update_summary()
        
        v_list, s_list, _ = discover_system_data(self.config["wt_root"], self.config["suffix"])
        self.v_list = [v for v in v_list if v not in ig_v or v in ("none", "custom...")]
        if not self.v_list: self.v_list = ["custom..."]
        self.s_list = [s for s in s_list if s not in ig_s or s in ("none", "custom...")]
        if not self.s_list: self.s_list = ["custom..."]
        
        v_sel = self.query_one("#version", Select)
        curr_v = v_sel.value
        v_sel.set_options((v, v) for v in self.v_list)
        v_sel.value = curr_v if curr_v in self.v_list else (self.v_list[0] if self.v_list else None)
        
        s_sel = self.query_one("#suffix", Select)
        curr_s = s_sel.value
        s_sel.set_options((s, s) for s in self.s_list)
        s_sel.value = curr_s if curr_s in self.s_list else (self.s_list[0] if self.s_list else None)

    @on(Button.Pressed, "#submit-btn")
    def on_submit_btn(self) -> None: self.action_submit()

    @on(Button.Pressed, "#open-btn")
    def on_open_btn(self) -> None:
        table = self.query_one("#wt-table", DataTable)
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            self.on_wt_selected(DataTable.RowSelected(table, row_key))
        except Exception:
            self.notify("Select a worktree first!", severity="error")
    
    @on(Button.Pressed, "#refresh-btn")
    def on_refresh_btn(self) -> None:
        config_mgr.append_log("Refresh Button Clicked")
        self.action_refresh_wts()
        
    @on(Button.Pressed, "#delete-btn")
    def on_delete_btn(self) -> None:
        config_mgr.append_log("Delete Button Clicked")
        self.action_delete_wt()
        
    @on(Button.Pressed, "#btn-close-app")
    def on_close_app_btn(self) -> None:
        config_mgr.append_log("Cancel Button Clicked")
        self.exit()

    def action_delete_wt(self) -> None:
        table = self.query_one("#wt-table")
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            wt_name = Path(row_key).name
            if wt_name == "master":
                self.notify("The 'master' worktree is protected and cannot be deleted.", severity="error")
                return
            def check_delete(confirm: bool):
                if confirm: self.execute_deletion(row_key, wt_name)
            self.app.push_screen(DeleteConfirmScreen(wt_name), check_delete)
        except Exception: self.notify("Select a worktree first!", severity="error")

    @work(exclusive=False)
    async def execute_deletion(self, target_path_str, name):
        # 1. Track deletion in-progress
        self.deleting_paths.add(target_path_str)
        self.populate_table()
        self.notify(f"Queued deletion for '{name}'...", timeout=2)

        try:
            target_path = Path(target_path_str)
            base_odoo = target_path.parent / "master" / "odoo"
            base_ent = target_path.parent / "master" / "enterprise"

            # 2. Parallel Git operations
            async def remove_wt(sub_dir, base_dir):
                wt_path = target_path / sub_dir
                if wt_path.exists():
                    process = await asyncio.create_subprocess_exec(
                        "git", "worktree", "remove", "-f", str(wt_path),
                        cwd=base_dir,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    await process.wait()

            await asyncio.gather(
                remove_wt("odoo", base_odoo),
                remove_wt("enterprise", base_ent)
            )

            # 3. Clean up orphaned git references (Prune)
            async def prune_wt(base_dir):
                process = await asyncio.create_subprocess_exec(
                    "git", "worktree", "prune",
                    cwd=base_dir,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await process.wait()

            await asyncio.gather(
                prune_wt(base_odoo),
                prune_wt(base_ent)
            )

            # 4. Background folder deletion (with proper locking check)
            import shutil
            try:
                await asyncio.to_thread(shutil.rmtree, target_path)
            except PermissionError:
                self.notify(f"Cannot delete '{name}': Files in use. Stop the Odoo server first!", severity="error")
                return
            except Exception as e:
                config_mgr.append_log("Folder deletion error", {"error": str(e)})

            config_mgr.append_log("Deleted Worktree", {"name": name, "path": target_path_str})
            self.notify(f"Successfully deleted '{name}'!", severity="success")
        finally:
            self.deleting_paths.remove(target_path_str)
            self.worktrees = [w for w in self.worktrees if w["path"] != target_path_str]
            self.populate_table()

    def action_submit(self) -> None:
        if self.query_one("#tabs").active != "tab-create": return
        v_sel = self.query_one("#version").value
        version = self.query_one("#custom_version").value if v_sel == "custom..." else v_sel
        desc = self.query_one("#desc").value
        s_sel = self.query_one("#suffix").value
        suffix = self.query_one("#custom_suffix").value if s_sel == "custom..." else s_sel
        if version == "none" or version == Select.BLANK: version = ""
        if suffix == "none" or suffix == Select.BLANK: suffix = ""
        if s_sel == "custom..." and suffix and suffix != "none":
            self.config["suffix"] = suffix
            config_mgr.save(self.config)
        self.app.push_screen(DeployScreen({"action": "create", "version": version, "desc": desc, "suffix": suffix}, self.config))
