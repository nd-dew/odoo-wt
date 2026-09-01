import json
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll, Center
from textual.widgets import Header, Footer, Select, Input, Label, Button, TabbedContent, TabPane, DataTable, Static, Checkbox, Switch
from textual import on, work
from textual.events import Paste, Key, DescendantFocus, Click
from textual.binding import Binding
from spellchecker import SpellChecker
from rich.text import Text
from rich.style import Style

spell = SpellChecker()
spell.word_frequency.load_words(['odoo', 'saas', 'erp', 'mrp', 'pos', 'crm', 'wt', 'api', 'ui', 'ux', 'db', 'sql', 'backend', 'frontend', 'js', 'py', 'xml', 'owl', 'mac', 'linux', 'windows', 'repo'])

from .app_config import config_mgr, debug_log
from .system_discovery import discover_system_data, get_remote, run_git, decompose_branch, get_remote_url, is_base_branch
from .custom_screens import DeleteConfirmScreen, BulkDeleteConfirmScreen, DeployScreen, LogDetailScreen

SETTINGS_HELP = {
    "set-wt": "The base directory where all your WorkTrees will be created.",
    "set-env": "Where the centralized UV virtual environments will be stored.",
    "set-suffix": "Your default developer quadrigram (e.g., 'pian') used as a branch suffix.",
    "set-remote": "The name of the git remote pointing to your personal Odoo fork.",
    "set-py-v": "The default Python version used when creating new UV environments.",
    "set-comm": "The name of the community folder inside a worktree (default: 'odoo').",
    "set-ent": "The name of the enterprise folder inside a worktree (default: 'enterprise').",
    "set-comm-remote": "The main official remote for Community (leave blank to auto-detect).",
    "set-ent-remote": "The main official remote for Enterprise (leave blank to auto-detect).",
    "set-default-tab": "Which tab to open by default when the app starts.",
    "set-ig-v": "Comma-separated list of versions to hide from the creation dropdowns.",
    "set-ig-s": "Comma-separated list of suffixes to hide from the creation dropdowns.",
    "set-whitelist": "Comma-separated list of unrecognized words to ignore permanently.",
    "set-known-versions": "The default known/pinned versions displayed in the Creation dropdown.",
    "set-known-suffixes": "The default known/pinned developer suffixes displayed in the Creation dropdown.",
    "set-tech-terms": "Technical words or jargon to completely bypass during spell checking.",
    "set-next-port": "The starting port number for Odoo's debugging sessions (incremented on each run).",
    "set-status-max-width": "Capping your CLI table output to a maximum width (default: 150 chars) prevents text wrapping on large screens.",
    "set-spell-check": "Toggle spellchecking on branch names to highlight potential typos.",
    "set-show-prefix": "Toggle visibility of the version dropdown in the Creation tab.",
    "set-show-suffix": "Toggle visibility of the suffix dropdown in the Creation tab.",
    "set-show-desc": "Toggle visibility of the app description text at the top.",
    "set-dark-mode": "Toggle between dark and light themes.",
    "set-config-path": "Moving this will migrate your config file to a new location.",
    "set-log-path": "Moving this will migrate your log file to a new location.",
}

class RunbotDataTable(DataTable):
    def on_click(self, event: Click) -> None:
        meta = event.style.meta
        config_mgr.append_log("RunbotDataTable Clicked Natively", {
            "meta": str(meta),
            "screen_x": event.screen_x,
            "screen_y": event.screen_y,
            "style": str(event.style) if event.style else "no-style"
        })
        if hasattr(self.app, "handle_table_click"):
            self.app.handle_table_click(event)

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
        Binding("ctrl+b", "open_runbot", "Runbot", key_display="^B"),
        Binding("ctrl+y", "toggle_sort", "Sort: Cycle", key_display="^Y"),
        Binding("ctrl+w", "toggle_select", "Toggle Select", show=True, key_display="^W"),
        Binding("ctrl+a", "select_all", "Select All", show=False),
        Binding("ctrl+d", "deselect_all", "Clear", show=False),
        Binding("escape", "quit", "", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True, key_display="^Q"),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(self, config, v_list, s_list, worktrees, version_str="dev"):
        super().__init__()
        debug_log("OdooWtApp.__init__ starting...")
        self.config = config
        self.app_version = version_str
        
        debug_log(f"OdooWtApp received: config_keys={list(config.keys())}, v_list={v_list}, s_list={s_list}, worktrees_count={len(worktrees)}")
        
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
        self.selected_wts = set()
        self.branch_status = ""
        self.check_results_str = ""
        self.save_timer = None
        self.resolved_comm_remote = ""
        self.resolved_comm_url = ""
        self.resolved_ent_remote = ""
        self.resolved_ent_url = ""
        self.resolved_runbot_urls = {}
        self.resolved_runbot_statuses = {}
        self.resolved_odoo_pr_urls = {}
        self.resolved_enterprise_pr_urls = {}
        self.resolved_upgrade_pr_urls = {}
        self.resolved_pr_comments = {}
        self.resolved_runbot_timestamps = {}
        self.active_sort_mode = "recency"


        # Modern Textual Theme API
        is_dark = self.config.get("dark_mode", True)
        self.theme = "textual-dark" if is_dark else "textual-light"

    def run(self, *args, **kwargs):
        debug_log("OdooWtApp.run() execution starting...")
        try:
            import os
            import sys
            import shutil
            tty_info = {
                "stdin_isatty": sys.stdin.isatty(),
                "stdout_isatty": sys.stdout.isatty(),
                "stderr_isatty": sys.stderr.isatty(),
                "fd0_isatty": os.isatty(0) if hasattr(os, "isatty") else "N/A",
                "fd1_isatty": os.isatty(1) if hasattr(os, "isatty") else "N/A",
                "fd2_isatty": os.isatty(2) if hasattr(os, "isatty") else "N/A",
                "term_env": os.environ.get("TERM", "NOT SET"),
                "term_size": str(shutil.get_terminal_size() if hasattr(shutil, "get_terminal_size") else "N/A"),
                "is_test_mode": config_mgr.is_test_mode
            }
            debug_log(f"OdooWtApp.run() TTY diagnostics: {tty_info}")
        except Exception as e:
            debug_log(f"OdooWtApp.run() failed gathering TTY diagnostics: {e}")

        try:
            return super().run(*args, **kwargs)
        except Exception as e:
            debug_log(f"OdooWtApp.run() execution failed: {e}")
            raise

    def get_footer_text(self) -> str:
        try:
            active_tab = self.query_one("#tabs").active
        except Exception:
            active_tab = "tab-create"
            
        parts = []
        if active_tab == "tab-create":
            parts.append("^S Create")
            
        parts.extend(["^X Delete", "^R Refresh", "^T Tab", "^Q Quit"])
        if active_tab == "tab-manage":
            parts.append("^B Runbot")
            parts.append("^W ^A ^D Select")
            sort_labels = {
                "recency": "Rec",
                "version": "Ver",
                "name": "Name",
                "runbot": "CI",
                "reviews": "PR"
            }
            parts.append(f"^Y Sort: {sort_labels.get(self.active_sort_mode, self.active_sort_mode)}")
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
            
            # Priority Shortcuts: Always available on Manage tab, even if search is focused
            # (bypasses Input's own built-in ctrl+w/ctrl+a/ctrl+d/ctrl+x bindings)
            if active_tab == "tab-manage" and event.key in ("ctrl+x", "ctrl+w", "ctrl+a", "ctrl+d"):
                if event.key == "ctrl+x":
                    self.action_delete_wt()
                elif event.key == "ctrl+w":
                    self.action_toggle_select()
                elif event.key == "ctrl+a":
                    self.action_select_all()
                elif event.key == "ctrl+d":
                    self.action_deselect_all()
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
        debug_log("OdooWtApp.compose starting...")
        
        with Vertical(id="dialog"):
            yield from self._compose_header()
            yield Label("")
            
            with TabbedContent(id="tabs"):
                yield from self._compose_tab_creation()
                yield from self._compose_tab_manage()
                yield from self._compose_tab_settings()
                yield from self._compose_tab_logs()
                
        yield Static("^S Create  ^X Delete  ^R Refresh  ^B Runbot  ^T Tab  ^Q Quit", id="global-help-bar", classes="help-bar")

    def _compose_header(self) -> ComposeResult:
        """Renders the top bar and title."""
        with Horizontal(id="top-bar"):
            with Vertical(id="title-container"):
                yield Label(f"Odoo WorkTree Tool v{self.app_version}", classes="title")
                yield Label(
                    "Opinionated tool for Odoo development. Creates/removes WorkTrees\nreusing UV environments per Odoo version.", 
                    id="app-desc", classes="description"
                )
            yield Button("X", id="btn-close-app", classes="close-btn")

    def _compose_tab_creation(self) -> ComposeResult:
        """Renders the Creation tab."""
        with TabPane("Creation", id="tab-create"):
            with VerticalScroll():
                yield Label("What branch do you need?", classes="tab-description")
                yield Label("", id="preflight-banner", classes="hidden")

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

    def _compose_tab_manage(self) -> ComposeResult:
        """Renders the Manage tab."""
        with TabPane("Manage", id="tab-manage"):
            yield Label(
                "Discovery: Scans 'Worktree Root Path' (in Settings)\nfor 'odoo/.git' folders. [bold cyan]Hint: Double-click or press Enter on a row to open in terminal.[/bold cyan]", 
                classes="tab-description"
            )
            with Horizontal(classes="manage-top-row"):
                yield Input(placeholder="Fuzzy search...", id="wt-search", classes="search-input")
                yield Button("Open", variant="success", id="open-btn", classes="mini-btn")
                yield Button("Refresh", id="refresh-btn", classes="mini-btn")
                yield Button("Delete ^X", variant="error", id="delete-btn", classes="mini-btn")
            
            yield RunbotDataTable(id="wt-table", cursor_type="row")

    def _compose_tab_settings(self) -> ComposeResult:
        """Renders the Settings tab using a data-driven approach."""
        with TabPane("Settings", id="tab-settings"):
            with Horizontal(classes="settings-top-row"):
                yield Input(placeholder="Fuzzy search settings... (e.g. 'log', 'dark', 'path')", id="settings-search", classes="search-input")
                yield Button("Save", variant="success", id="save-settings-btn", classes="mini-btn", disabled=True)
                yield Button("Discard", id="reset-settings-btn", classes="mini-btn", disabled=True)
            
            with VerticalScroll(classes="settings-container"):
                # Configuration map: (Label text, Widget Class, widget_id, kwargs_dict)
                settings_fields = [
                    ("Worktree Root:", Input, "set-wt", {"value": self.config.get("wt_root", "")}),
                    ("UV Envs Path:", Input, "set-env", {"value": self.config.get("env_root", "")}),
                    ("Default Suffix:", Input, "set-suffix", {"value": self.config.get("suffix", "")}),
                    ("Dev Remote (Fork):", Input, "set-remote", {"value": self.config.get("remote_name", "odoo-dev")}),
                    ("Python Version:", Input, "set-py-v", {"value": self.config.get("python_version", "3.12")}),
                    ("Community Dir:", Input, "set-comm", {"value": self.config.get("community_dir", "odoo")}),
                    ("Enterprise Dir:", Input, "set-ent", {"value": self.config.get("enterprise_dir", "enterprise")}),
                    ("Comm Main Remote:", Input, "set-comm-remote", {"value": self.config.get("community_remote", ""), "placeholder": "Blank = auto-detect"}),
                    ("Ent Main Remote:", Input, "set-ent-remote", {"value": self.config.get("enterprise_remote", ""), "placeholder": "Blank = auto-detect"}),
                    ("Start in Manage Tab:", Switch, "set-default-tab", {"value": self.config.get("default_tab", "tab-create") == "tab-manage"}),
                    ("Removed Versions:", Input, "set-ig-v", {"value": ",".join(self.config.get("ignored_versions", []))}),
                    ("Removed Suffixes:", Input, "set-ig-s", {"value": ",".join(self.config.get("ignored_suffixes", []))}),
                    ("Typos Whitelist:", Input, "set-whitelist", {"value": ",".join(self.config.get("ignored_typos", []))}),
                    ("Pinned Versions:", Input, "set-known-versions", {"value": ",".join(self.config.get("known_versions", []))}),
                    ("Pinned Suffixes:", Input, "set-known-suffixes", {"value": ",".join(self.config.get("known_suffixes", []))}),
                    ("Technical Jargon:", Input, "set-tech-terms", {"value": ",".join(self.config.get("technical_terms", []))}),
                    ("Next Debug Port:", Input, "set-next-port", {"value": str(self.config.get("next_debug_port", 8069))}),
                    ("CLI Status Max Width:", Input, "set-status-max-width", {"value": str(self.config.get("status_max_width", 150))}),
                    ("Enable Spell Check:", Switch, "set-spell-check", {"value": self.config.get("enable_spell_check", True)}),
                    ("Show Prefix (Version):", Switch, "set-show-prefix", {"value": self.config.get("show_prefix", True)}),
                    ("Show Suffix:", Switch, "set-show-suffix", {"value": self.config.get("show_suffix", True)}),
                    ("Show Description:", Switch, "set-show-desc", {"value": self.config.get("show_desc", True)}),
                    ("Auto Magic Fix:", Switch, "set-auto-magic", {"value": self.config.get("auto_magic_fix", True)}),
                    ("Dark Mode:", Switch, "set-dark-mode", {"value": self.config.get("dark_mode", True)}),
                    ("Config Path:", Input, "set-config-path", {"value": self.config.get("config_path", "")}),
                    ("Log Path:", Input, "set-log-path", {"value": self.config.get("log_path", "")}),
                ]

                for label, WidgetClass, widget_id, kwargs in settings_fields:
                    with Horizontal(classes="setting-item"):
                        yield Label(label, classes="setting-label")
                        yield WidgetClass(id=widget_id, classes="setting-input", **kwargs)

    def _compose_tab_logs(self) -> ComposeResult:
        """Renders the Logs tab."""
        with TabPane("Logs", id="tab-logs"):
            yield Label("System Logs (Newest first)", classes="tab-description")
            yield DataTable(id="logs-table", cursor_type="row")
            with Horizontal(classes="btn-row"):
                yield Button("Refresh", id="refresh-logs-btn")
                yield Button("Clear Logs", variant="error", id="clear-logs-btn")
                
    def on_mount(self) -> None:
        debug_log("OdooWtApp.on_mount starting...")
        config_mgr.append_log("App Started")
        
        # Initialize Manage Table Columns
        table = self.query_one("#wt-table", DataTable)
        table.add_column("[dim]✔[/dim]", key="col-select")
        table.add_column("Branch Name", key="col-branch")
        table.add_column("Runbot Status", key="col-runbot")
        table.add_column("Link", key="col-link")
        table.add_column("Last Comment", key="col-comment")

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
            
        self.run_preflight_diagnostics()

    def on_ready(self) -> None:
        debug_log("OdooWtApp.on_ready starting...")
        self.run_runbot_checker()

    def run_preflight_diagnostics(self) -> None:
        debug_log("OdooWtApp.run_preflight_diagnostics starting...")
        from .preflight_checker import run_preflight_checks
        results = run_preflight_checks(self.config)
        debug_log(f"OdooWtApp pre-flight diagnostics completed. Statuses: {[r.status for r in results]}")
        has_error = any(r.status == "error" for r in results)
        has_warn = any(r.status == "warn" for r in results)
        
        if has_error:
            err_msg = next(r.advice for r in results if r.status == "error")
            self.notify(f"PRE-FLIGHT ERROR: {err_msg}", severity="error", timeout=12.0)
            try:
                banner = self.query_one("#preflight-banner", Label)
                banner.update(f"[bold red]❌ PRE-FLIGHT ERROR:[/bold red]\n{err_msg}")
                banner.remove_class("hidden")
            except Exception:
                pass
        elif has_warn:
            warn_msg = next(r.advice for r in results if r.status == "warn")
            self.notify(f"PRE-FLIGHT WARNING: {warn_msg}", severity="warning", timeout=8.0)
            try:
                banner = self.query_one("#preflight-banner", Label)
                banner.update(f"[bold yellow]⚠️  PRE-FLIGHT WARNING:[/bold yellow]\n{warn_msg}")
                banner.remove_class("hidden")
                banner.styles.background = "$warning-subtle"
                banner.styles.border = ("solid", "$warning")
                banner.styles.color = "$warning"
            except Exception:
                pass

    def apply_visibility_settings(self):
        debug_log("OdooWtApp.apply_visibility_settings starting...")
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
            self.run_runbot_checker()
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
            
            # Resolve base version from branch name if not explicitly set
            base_v = version if version else ""
            if not base_v or base_v == "none":
                _, parsed_v, _, _ = decompose_branch(branch_name)
                base_v = parsed_v or "master"
                
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

            if getattr(self, "resolved_comm_remote", ""):
                summary.append("\n\nUsing Remotes (Configuration & Auto-detect):")
                summary.append(f"\n  • Community: '{self.resolved_comm_remote}' -> ", style="bright_black")
                summary.append(f"{self.resolved_comm_url}", style="cyan")
                summary.append(f"\n  • Enterprise: '{self.resolved_ent_remote}' -> ", style="bright_black")
                summary.append(f"{self.resolved_ent_url}", style="cyan")

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
            comm_main_remote = self.config.get("community_remote", "").strip() or await asyncio.to_thread(get_remote, base_odoo)
            ent_main_remote = self.config.get("enterprise_remote", "").strip() or await asyncio.to_thread(get_remote, base_ent)
            
            comm_url = await asyncio.to_thread(get_remote_url, base_odoo, comm_main_remote)
            ent_url = await asyncio.to_thread(get_remote_url, base_ent, ent_main_remote)
            
            self.resolved_comm_remote = comm_main_remote
            self.resolved_comm_url = comm_url
            self.resolved_ent_remote = ent_main_remote
            self.resolved_ent_url = ent_url

            # Animation & Checklist Logic
            checks = [
                {"name": "Local Community", "path": base_odoo, "type": "local"},
                {"name": "Local Enterprise", "path": base_ent, "type": "local"},
                {"name": f"Dev ({dev_remote}) Community", "path": base_odoo, "type": "remote", "remote": dev_remote},
                {"name": f"Dev ({dev_remote}) Enterprise", "path": base_ent, "type": "remote", "remote": dev_remote},
                {"name": f"Main ({comm_main_remote}) Community", "path": base_odoo, "type": "remote", "remote": comm_main_remote},
                {"name": f"Main ({ent_main_remote}) Enterprise", "path": base_ent, "type": "remote", "remote": ent_main_remote},
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
            
            if self.config.get("enable_spell_check", True):
                unknown = spell.unknown([w for w in words if w not in system_ignore and w not in tech_terms and w not in user_ignored])
                unknown = {w for w in unknown if not w.isnumeric() and len(w) > 2}
            else:
                unknown = set()
            
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
        def get_status_tag(res):
            if res == "ok": return "[green]✓[/green]"
            if res == "fail": return "[red]✗[/red]"
            return "[bright_black]~[/bright_black]"  # skipped / pending
            
        lc = get_status_tag(results.get(checks[0]["name"]))
        le = get_status_tag(results.get(checks[1]["name"]))
        dc = get_status_tag(results.get(checks[2]["name"]))
        de = get_status_tag(results.get(checks[3]["name"]))
        mc = get_status_tag(results.get(checks[4]["name"]))
        me = get_status_tag(results.get(checks[5]["name"]))
        
        dev_label = checks[2].get("remote", "odoo-dev")
        
        return (
            f"Availability:   Local: {lc} Comm / {le} Ent   |   "
            f"Fork ({dev_label}): {dc} Comm / {de} Ent   |   "
            f"Odoo: {mc} Comm / {me} Ent"
        )


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
        debug_log("OdooWtApp.populate_table starting...")
        table = self.query_one("#wt-table", DataTable)
        table.clear()
        
        try:
            search_term = self.query_one("#wt-search", Input).value.lower()
        except Exception:
            search_term = ""

        # Symmetrical multi-mode sorting inside TUI
        if self.active_sort_mode == "version":
            sorted_wts = sorted(self.worktrees, key=self._version_sort_key, reverse=True)
        elif self.active_sort_mode == "name":
            sorted_wts = sorted(self.worktrees, key=lambda wt: wt["name"].lower())
        elif self.active_sort_mode == "runbot":
            def runbot_sort_key(wt_dict):
                name = wt_dict["name"]
                return self.resolved_runbot_timestamps.get(name, "")
            sorted_wts = sorted(self.worktrees, key=runbot_sort_key, reverse=True)
        elif self.active_sort_mode == "reviews":
            def comment_sort_key(wt_dict):
                name = wt_dict["name"]
                comment_data = self.resolved_pr_comments.get(name)
                return comment_data.get("created_at", "") if comment_data else ""
            sorted_wts = sorted(self.worktrees, key=comment_sort_key, reverse=True)
        else: # recency
            def recency_sort_key(wt_dict):
                path_str = wt_dict["path"]
                ts = self.config.get("worktree_recency", {}).get(path_str, "")
                return (ts, self._version_sort_key(wt_dict), wt_dict["name"])
            sorted_wts = sorted(self.worktrees, key=recency_sort_key, reverse=True)

        for wt in sorted_wts:
            name = wt["name"]
            path = wt["path"]
            
            # Fuzzy match
            if search_term and search_term not in name.lower():
                continue

            display_name = name
            if path in self.deleting_paths:
                display_name = f"[strike]{name}[/strike] [bold red](Deleting...)[/bold red]"
                
            # Read from local status and URL caches
            status = self.resolved_runbot_statuses.get(name, "⏳ checking... ")
            
            if is_base_branch(name):
                status = "⚪"
                link = "[link=https://runbot.odoo.com/runbot]Board[/link]"
            elif name in self.resolved_runbot_urls:
                batch_url = self.resolved_runbot_urls[name]
                parts = [f"[link={batch_url}]CI[/link]"]
                odoo_pr = self.resolved_odoo_pr_urls.get(name)
                if odoo_pr:
                    parts.append(f"[link={odoo_pr}]Com[/link]")
                ent_pr = self.resolved_enterprise_pr_urls.get(name)
                if ent_pr:
                    parts.append(f"[link={ent_pr}]Ent[/link]")
                upg_pr = self.resolved_upgrade_pr_urls.get(name)
                if upg_pr:
                    parts.append(f"[link={upg_pr}]Upg[/link]")
                link = "|".join(parts)
            else:
                link = f"[link=https://runbot.odoo.com/runbot?search={name}]Search[/link]"
                
            # Get latest PR comment cell
            comment_cell = ""
            if not is_base_branch(name):
                comment_data = self.resolved_pr_comments.get(name)
                if comment_data:
                    user = comment_data["user"]
                    relative = comment_data["relative"]
                    link_url = comment_data["html_url"]
                    body_clean = comment_data.get("body_clean", "")
                    
                    comment_text = f"{user} ({relative})"
                    if body_clean:
                        comment_text += f": {body_clean}"
                    
                    comment_cell = f"[link={link_url}]{comment_text}[/link]"
                else:
                    comment_cell = "[dim]⏳ Checking...[/dim]"
            else:
                comment_cell = ""

            # Selection cell logic
            is_selected = path in self.selected_wts
            select_cell = "" if is_base_branch(name) else ("[b green]✔[/b green]" if is_selected else "[dim]☐[/dim]")

            table.add_row(select_cell, display_name, status, link, comment_cell, key=path)
            
        self.adjust_column_widths()

    def adjust_column_widths(self) -> None:
        try:
            table = self.query_one("#wt-table", DataTable)
            W = table.size.width
            if W <= 10:
                return
                
            # Symmetrical dynamic grid calculation:
            # - Selection column takes 4 cells.
            # - Runbot Status takes 14 cells.
            # - Link takes 15 cells.
            # - Branch Name gets up to 35% of W, minimum 25, maximum 45.
            # - Last Comment gets the absolute remaining width to prevent truncation and overflow!
            select_w = 4
            runbot_w = 14
            link_w = 15
            branch_w = max(25, min(45, int(W * 0.35)))
            comment_w = max(20, W - select_w - branch_w - runbot_w - link_w - 6)
            
            if "col-select" in table.columns:
                table.columns["col-select"].auto_width = False
                table.columns["col-select"].width = select_w
            if "col-branch" in table.columns:
                table.columns["col-branch"].auto_width = False
                table.columns["col-branch"].width = branch_w
            if "col-runbot" in table.columns:
                table.columns["col-runbot"].auto_width = False
                table.columns["col-runbot"].width = runbot_w
            if "col-link" in table.columns:
                table.columns["col-link"].auto_width = False
                table.columns["col-link"].width = link_w
            if "col-comment" in table.columns:
                table.columns["col-comment"].auto_width = False
                table.columns["col-comment"].width = comment_w
                
            table.refresh(layout=True)
        except Exception:
            pass

    def on_resize(self, event) -> None:
        self.adjust_column_widths()

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
        import time
        if time.time() - getattr(self, "_last_table_click_time", 0) < 0.2:
            return
        path = str(event.row_key.value)
        self.touch_worktree(path)
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
        self.query_one("#set-comm-remote", Input).value = self.config.get("community_remote", "")
        self.query_one("#set-ent-remote", Input).value = self.config.get("enterprise_remote", "")
        self.query_one("#set-default-tab", Switch).value = (self.config.get("default_tab", "tab-create") == "tab-manage")
        self.query_one("#set-ig-v", Input).value = ",".join(self.config.get("ignored_versions", []))
        self.query_one("#set-ig-s", Input).value = ",".join(self.config.get("ignored_suffixes", []))
        self.query_one("#set-whitelist", Input).value = ",".join(self.config.get("ignored_typos", []))
        self.query_one("#set-known-versions", Input).value = ",".join(self.config.get("known_versions", []))
        self.query_one("#set-known-suffixes", Input).value = ",".join(self.config.get("known_suffixes", []))
        self.query_one("#set-tech-terms", Input).value = ",".join(self.config.get("technical_terms", []))
        self.query_one("#set-next-port", Input).value = str(self.config.get("next_debug_port", 8069))
        self.query_one("#set-status-max-width", Input).value = str(self.config.get("status_max_width", 150))
        self.query_one("#set-spell-check", Switch).value = self.config.get("enable_spell_check", True)
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
        try:
            self.query_one("#save-settings-btn", Button).disabled = True
            self.query_one("#reset-settings-btn", Button).disabled = True
        except Exception:
            pass
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
        self.resolved_runbot_urls.clear()
        self.resolved_runbot_statuses.clear()
        self.resolved_odoo_pr_urls.clear()
        self.resolved_enterprise_pr_urls.clear()
        self.resolved_upgrade_pr_urls.clear()
        _, _, self.worktrees = discover_system_data(
            self.config["wt_root"], 
            self.config["suffix"],
            known_versions=self.config.get("known_versions", []),
            known_suffixes=self.config.get("known_suffixes", [])
        )
        self.populate_table()
        self.run_runbot_checker()
        self.notify("Worktrees refreshed!")

    def update_table_cell(self, row_key: str, column_key: str, value: str) -> None:
        try:
            table = self.query_one("#wt-table", DataTable)
            table.update_cell(row_key, column_key, value)
            self.adjust_column_widths()
            config_mgr.append_log("UI Cell Updated", {"row": row_key, "col": column_key, "value": value})
        except Exception as e:
            config_mgr.append_log("UI Cell Update Error", {"error": str(e)})

    def touch_worktree(self, path_str: str) -> None:
        import datetime
        if "worktree_recency" not in self.config:
            self.config["worktree_recency"] = {}
        self.config["worktree_recency"][path_str] = datetime.datetime.utcnow().isoformat()
        config_mgr.save(self.config)
        config_mgr.append_log("Worktree Touched", {"path": path_str, "timestamp": self.config["worktree_recency"][path_str]})

    @work(exclusive=True, thread=True)
    def run_runbot_checker(self) -> None:
        debug_log("OdooWtApp.run_runbot_checker starting...")
        from .runbot_client import check_branch_status_and_comments
        import traceback
        import datetime
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        config_mgr.append_log("Runbot Concurrent Checker Started", {"worktrees_count": len(self.worktrees)})
        
        def relative_time(ts_str: str) -> str:
            if not ts_str: return ""
            try:
                dt = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                now = datetime.datetime.utcnow()
                delta = now - dt
                total_seconds = int(delta.total_seconds())
                if total_seconds < 0:
                    total_seconds = 0
                if total_seconds < 60:
                    return "just now"
                elif total_seconds < 3600:
                    return f"{total_seconds // 60}m ago"
                elif total_seconds < 86400:
                    return f"{total_seconds // 3600}h ago"
                else:
                    return f"{total_seconds // 86400}d ago"
            except Exception:
                return ""
        
        wts = list(self.worktrees)
        
        # 1. Update all base branches immediately (doesn't need network CI polling)
        for wt in wts:
            if is_base_branch(wt["name"]):
                self.call_from_thread(self.update_table_cell, wt["path"], "col-runbot", "⚪")
                self.call_from_thread(self.update_table_cell, wt["path"], "col-link", "[link=https://runbot.odoo.com/runbot]Board[/link]")
                self.resolved_runbot_statuses[wt["name"]] = "⚪"

        # Filter out base branches for concurrent web checks
        to_check = [wt for wt in wts if not is_base_branch(wt["name"])]
        if not to_check:
            return

        # 2. Check all other branches in parallel concurrently
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_wt = {
                executor.submit(check_branch_status_and_comments, wt["name"]): wt 
                for wt in to_check
            }
            
            for future in as_completed(future_to_wt):
                wt = future_to_wt[future]
                path = wt["path"]
                branch_name = wt["name"]
                
                status = "⚪ No batch"
                link = f"[link=https://runbot.odoo.com/runbot?search={branch_name}]Search...          [/link]"
                comment_cell = "[dim]-[/dim]"
                
                try:
                    res = future.result()
                    if res:
                        self.resolved_runbot_urls[branch_name] = res["batch_url"]
                        
                        if res["odoo_pr"]:
                            self.resolved_odoo_pr_urls[branch_name] = res["odoo_pr"]
                        if res["enterprise_pr"]:
                            self.resolved_enterprise_pr_urls[branch_name] = res["enterprise_pr"]
                        if res["upgrade_pr"]:
                            self.resolved_upgrade_pr_urls[branch_name] = res["upgrade_pr"]
                        
                        self.resolved_runbot_timestamps[branch_name] = res.get("ts_str", "")
                        
                        parts = [f"[link={res['batch_url']}]CI[/link]"]
                        if res["odoo_pr"]:
                            parts.append(f"[link={res['odoo_pr']}]Com[/link]")
                        if res["enterprise_pr"]:
                            parts.append(f"[link={res['enterprise_pr']}]Ent[/link]")
                        if res["upgrade_pr"]:
                            parts.append(f"[link={res['upgrade_pr']}]Upg[/link]")
                        link = "|".join(parts)
                        
                        time_suffix = f" {relative_time(res['ts_str'])}" if res["ts_str"] else ""
                        
                        # Apply minimalist TUI status formatting
                        if res["running"] > 0:
                            status = f"🏃{time_suffix}"
                        elif res["failed"] > 0:
                            status = f"🔴{time_suffix}"
                        elif res["warning"] > 0:
                            status = f"🟡{time_suffix}"
                        else:
                            status = f"🟢{time_suffix}"
                            
                        comment_data = res.get("comment_data")
                        if comment_data:
                            self.resolved_pr_comments[branch_name] = comment_data
                            user = comment_data["user"]
                            relative = comment_data["relative"]
                            link_url = comment_data["html_url"]
                            body_clean = comment_data.get("body_clean", "")
                            
                            comment_text = f"{user} ({relative})"
                            if body_clean:
                                comment_text += f": {body_clean}"
                            
                            comment_cell = f"[link={link_url}]{comment_text}[/link]"
                        else:
                            comment_cell = "[dim]-[/dim]"
                    else:
                        status = "⚪ No batch"
                        link = f"[link=https://runbot.odoo.com/runbot?search={branch_name}]Search...          [/link]"
                        comment_cell = "[dim]-[/dim]"
                    
                    self.resolved_runbot_statuses[branch_name] = status
                except Exception as e:
                    config_mgr.append_log("Runbot Concurrent Checker Error", {"branch": branch_name, "error": str(e), "traceback": traceback.format_exc()})
                    status = "⚠️ Error"
                    link = f"[link=https://runbot.odoo.com/runbot?search={branch_name}]Search...          [/link]"
                    comment_cell = "[dim]-[/dim]"
                    self.resolved_runbot_statuses[branch_name] = status
                    
                self.call_from_thread(self.update_table_cell, path, "col-runbot", status)
                self.call_from_thread(self.update_table_cell, path, "col-link", link)
                self.call_from_thread(self.update_table_cell, path, "col-comment", comment_cell)

    def action_quit(self) -> None:
        config_mgr.append_log("App Quit")
        self.exit()

    def action_toggle_sort(self) -> None:
        modes = ["recency", "version", "name", "runbot", "reviews"]
        curr_idx = modes.index(self.active_sort_mode)
        next_idx = (curr_idx + 1) % len(modes)
        self.active_sort_mode = modes[next_idx]
        
        mode_labels = {
            "recency": "Recency (last accessed/deployed first)",
            "version": "Odoo release version descending",
            "name": "Alphabetical branch name ascending",
            "runbot": "Most recently active Runbot builds first",
            "reviews": "Most recently active human PR comments first"
        }
        
        self.notify(f"Sorting Mode: {mode_labels[self.active_sort_mode]}", timeout=3)
        self.populate_table()
        
        # Update the help bar display with the new sort label
        try:
            help_bar = self.query_one("#global-help-bar", Static)
            help_bar.update(self.get_footer_text())
        except Exception:
            pass

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
                 
            s_sel = self.query_one("#suffix", Select)
            custom_s_input = self.query_one("#custom_suffix", Input)
            target_s = s if s else "none"
            
            if s_sel.value != target_s or (target_s == "custom..." and custom_s_input.value != s):
                if target_s in self.s_list:
                    s_sel.value = target_s
                else:
                    s_sel.value = "custom..."
                    custom_s_input.value = s
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

    def action_toggle_select(self) -> None:
        try:
            if self.query_one("#tabs").active != "tab-manage":
                return
        except Exception:
            return

        table = self.query_one("#wt-table", DataTable)
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
            path = str(row_key.value)
            wt_name = Path(path).name
            if is_base_branch(wt_name):
                self.notify(f"The '{wt_name}' branch is a base branch and is protected.", severity="warning")
                return
            
            if path in self.selected_wts:
                self.selected_wts.remove(path)
            else:
                self.selected_wts.add(path)
                
            is_selected = path in self.selected_wts
            cell_value = "[b green]✔[/b green]" if is_selected else "[dim]☐[/dim]"
            table.update_cell(row_key, "col-select", cell_value)
        except Exception:
            self.notify("Focus on a row first!", severity="error")

    def action_select_all(self) -> None:
        try:
            if self.query_one("#tabs").active != "tab-manage":
                return
        except Exception:
            return

        table = self.query_one("#wt-table", DataTable)
        for row_key in table.rows:
            path = str(row_key.value)
            if not is_base_branch(Path(path).name):
                self.selected_wts.add(path)
        self.populate_table()
        self.notify("Selected all visible worktrees.")

    def action_deselect_all(self) -> None:
        try:
            if self.query_one("#tabs").active != "tab-manage":
                return
        except Exception:
            return

        self.selected_wts.clear()
        self.populate_table()
        self.notify("Cleared selections.")

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
    @on(Input.Changed, "#set-comm-remote")
    @on(Input.Changed, "#set-ent-remote")
    @on(Input.Changed, "#set-ig-v")
    @on(Input.Changed, "#set-ig-s")
    @on(Input.Changed, "#set-whitelist")
    @on(Input.Changed, "#set-known-versions")
    @on(Input.Changed, "#set-known-suffixes")
    @on(Input.Changed, "#set-tech-terms")
    @on(Input.Changed, "#set-next-port")
    @on(Input.Changed, "#set-status-max-width")
    @on(Switch.Changed, "#set-spell-check")
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

            is_dirty = self.is_settings_dirty()
            try:
                self.query_one("#save-settings-btn", Button).disabled = not is_dirty
                self.query_one("#reset-settings-btn", Button).disabled = not is_dirty
            except Exception:
                pass

    def is_settings_dirty(self) -> bool:
        try:
            def clean_list(val: str):
                return [v.strip() for v in val.split(",") if v.strip()]

            # Strings
            if self.query_one("#set-wt", Input).value.strip() != self.config.get("wt_root", ""): return True
            if self.query_one("#set-env", Input).value.strip() != self.config.get("env_root", ""): return True
            if self.query_one("#set-suffix", Input).value.strip() != self.config.get("suffix", ""): return True
            if self.query_one("#set-remote", Input).value.strip() != self.config.get("remote_name", "odoo-dev"): return True
            if self.query_one("#set-py-v", Input).value.strip() != self.config.get("python_version", "3.12"): return True
            if self.query_one("#set-comm", Input).value.strip() != self.config.get("community_dir", "odoo"): return True
            if self.query_one("#set-ent", Input).value.strip() != self.config.get("enterprise_dir", "enterprise"): return True
            if self.query_one("#set-comm-remote", Input).value.strip() != self.config.get("community_remote", ""): return True
            if self.query_one("#set-ent-remote", Input).value.strip() != self.config.get("enterprise_remote", ""): return True
            if self.query_one("#set-config-path", Input).value.strip() != self.config.get("config_path", ""): return True
            if self.query_one("#set-log-path", Input).value.strip() != self.config.get("log_path", ""): return True

            # Switches / Checkboxes
            default_tab_val = "tab-manage" if self.query_one("#set-default-tab", Switch).value else "tab-create"
            config_tab_val = "tab-manage" if self.config.get("default_tab", "tab-create") == "tab-manage" else "tab-create"
            if default_tab_val != config_tab_val: return True

            if self.query_one("#set-show-prefix", Switch).value != self.config.get("show_prefix", True): return True
            if self.query_one("#set-show-suffix", Switch).value != self.config.get("show_suffix", True): return True
            if self.query_one("#set-show-desc", Switch).value != self.config.get("show_desc", True): return True
            if self.query_one("#set-auto-magic", Switch).value != self.config.get("auto_magic_fix", True): return True
            if self.query_one("#set-dark-mode", Switch).value != self.config.get("dark_mode", True): return True
            if self.query_one("#set-spell-check", Switch).value != self.config.get("enable_spell_check", True): return True

            # Lists
            if clean_list(self.query_one("#set-ig-v", Input).value) != self.config.get("ignored_versions", []): return True
            if clean_list(self.query_one("#set-ig-s", Input).value) != self.config.get("ignored_suffixes", []): return True
            if clean_list(self.query_one("#set-whitelist", Input).value) != self.config.get("ignored_typos", []): return True
            if clean_list(self.query_one("#set-known-versions", Input).value) != self.config.get("known_versions", []): return True
            if clean_list(self.query_one("#set-known-suffixes", Input).value) != self.config.get("known_suffixes", []): return True
            if clean_list(self.query_one("#set-tech-terms", Input).value) != self.config.get("technical_terms", []): return True

            # Numeric fields
            try:
                if int(self.query_one("#set-next-port", Input).value.strip()) != self.config.get("next_debug_port", 8069): return True
            except ValueError:
                pass

            try:
                if int(self.query_one("#set-status-max-width", Input).value.strip()) != self.config.get("status_max_width", 150): return True
            except ValueError:
                pass

        except Exception:
            return False

        return False

    @on(Button.Pressed, "#save-settings-btn")
    def on_save_settings_btn_pressed(self) -> None:
        self.save_settings()

    @on(Button.Pressed, "#reset-settings-btn")
    def on_reset_settings_btn_pressed(self) -> None:
        self.action_reset_settings()

    def save_settings(self) -> None:
        wt_val = self.query_one("#set-wt", Input).value.strip()
        env_val = self.query_one("#set-env", Input).value.strip()
        py_val = self.query_one("#set-py-v", Input).value.strip()
        comm_val = self.query_one("#set-comm", Input).value.strip()
        ent_val = self.query_one("#set-ent", Input).value.strip()

        # Validation
        if not wt_val or not env_val:
            self.notify("Error: Worktree Root and UV Envs Path cannot be blank!", severity="error")
            return

        self.config["wt_root"] = wt_val
        self.config["env_root"] = env_val
        self.config["suffix"] = self.query_one("#set-suffix", Input).value.strip()
        self.config["remote_name"] = self.query_one("#set-remote", Input).value.strip()
        self.config["python_version"] = py_val if py_val else "3.12"
        self.config["community_dir"] = comm_val if comm_val else "odoo"
        self.config["enterprise_dir"] = ent_val if ent_val else "enterprise"
        self.config["community_remote"] = self.query_one("#set-comm-remote", Input).value.strip()
        self.config["enterprise_remote"] = self.query_one("#set-ent-remote", Input).value.strip()

        is_manage_tab = self.query_one("#set-default-tab", Switch).value
        self.config["default_tab"] = "tab-manage" if is_manage_tab else "tab-create"

        self.config["config_path"] = self.query_one("#set-config-path", Input).value.strip()
        self.config["log_path"] = self.query_one("#set-log-path", Input).value.strip()
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

        self.config["known_versions"] = [v.strip() for v in self.query_one("#set-known-versions", Input).value.split(",") if v.strip()]
        self.config["known_suffixes"] = [s.strip() for s in self.query_one("#set-known-suffixes", Input).value.split(",") if s.strip()]
        self.config["technical_terms"] = [t.strip() for t in self.query_one("#set-tech-terms", Input).value.split(",") if t.strip()]

        try:
            self.config["next_debug_port"] = int(self.query_one("#set-next-port", Input).value.strip())
        except ValueError:
            pass

        try:
            self.config["status_max_width"] = int(self.query_one("#set-status-max-width", Input).value.strip())
        except ValueError:
            pass

        self.config["enable_spell_check"] = self.query_one("#set-spell-check", Switch).value

        config_mgr.save(self.config)
        config_mgr.append_log("Settings Saved Manually", self.config)
        self.notify("Settings saved successfully!")

        try:
            self.query_one("#save-settings-btn", Button).disabled = True
            self.query_one("#reset-settings-btn", Button).disabled = True
        except Exception:
            pass

        self.apply_visibility_settings()
        self.update_summary()

        v_list, s_list, _ = discover_system_data(
            self.config["wt_root"],
            self.config["suffix"],
            known_versions=self.config.get("known_versions", []),
            known_suffixes=self.config.get("known_suffixes", [])
        )
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
            self.on_wt_row_selected(DataTable.RowSelected(table, row_key))
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
        
        # 1. Bulk Deletion Action
        if self.selected_wts:
            valid_paths = [p for p in self.selected_wts if not is_base_branch(Path(p).name)]
            if not valid_paths:
                self.notify("No deletable worktrees selected.", severity="error")
                return
            
            wt_names = [Path(p).name for p in valid_paths]
            
            def check_bulk_delete(confirm: bool):
                if confirm:
                    self.execute_bulk_deletion(valid_paths, wt_names)
                    
            self.app.push_screen(BulkDeleteConfirmScreen(wt_names), check_bulk_delete)
            return

        # 2. Single Deletion Fallback (Muscle Memory)
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            wt_name = Path(row_key).name
            if is_base_branch(wt_name):
                self.notify(f"The '{wt_name}' base branch is protected and cannot be deleted.", severity="error")
                return
            def check_delete(confirm: bool):
                if confirm: self.execute_deletion(row_key, wt_name)
            self.app.push_screen(DeleteConfirmScreen(wt_name), check_delete)
        except Exception:
            self.notify("Select a worktree first!", severity="error")

    async def _do_single_deletion(self, target_path_str: str, name: str) -> None:
        target_path = Path(target_path_str)
        base_odoo = target_path.parent / "master" / "odoo"
        base_ent = target_path.parent / "master" / "enterprise"

        # 1. Parallel Git operations
        async def remove_wt(sub_dir, base_dir):
            wt_path = target_path / sub_dir
            if wt_path.exists():
                process = await asyncio.create_subprocess_exec(
                    "git", "worktree", "remove", "-f", str(wt_path),
                    cwd=base_dir,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await process.communicate()
                code = process.returncode
                if code != 0:
                    err_text = stderr.decode(errors="replace").strip() if stderr else "unknown git error"
                    raise RuntimeError(f"git worktree remove failed for '{sub_dir}': {err_text}")

        await asyncio.gather(
            remove_wt("odoo", base_odoo),
            remove_wt("enterprise", base_ent)
        )

        # 2. Clean up orphaned git references (Prune)
        async def prune_wt(base_dir):
            process = await asyncio.create_subprocess_exec(
                "git", "worktree", "prune",
                cwd=base_dir,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()
            code = process.returncode
            if code != 0:
                err_text = stderr.decode(errors="replace").strip() if stderr else "unknown git error"
                config_mgr.append_log("Prune error (non-fatal)", {"dir": str(base_dir), "error": err_text})

        await asyncio.gather(
            prune_wt(base_odoo),
            prune_wt(base_ent)
        )

        # 3. Background folder deletion (with proper locking check)
        import shutil
        await asyncio.to_thread(shutil.rmtree, target_path)
        config_mgr.append_log("Deleted Worktree", {"name": name, "path": target_path_str})

    @work(exclusive=False)
    async def execute_deletion(self, target_path_str, name):
        # 1. Track deletion in-progress
        self.deleting_paths.add(target_path_str)
        self.populate_table()
        self.notify(f"Queued deletion for '{name}'...", timeout=2)

        success = False
        try:
            await self._do_single_deletion(target_path_str, name)
            self.notify(f"Successfully deleted '{name}'!", severity="success")
            success = True
        except PermissionError as e:
            self.notify(f"Cannot delete '{name}': Files in use. Stop the Odoo server first!", severity="error")
            config_mgr.append_log("Folder deletion error", {"name": name, "path": target_path_str, "error": str(e)})
        except Exception as e:
            self.notify(f"Failed to delete '{name}': {str(e)}", severity="error")
            config_mgr.append_log("Folder deletion error", {"name": name, "path": target_path_str, "error": str(e)})
        finally:
            self.deleting_paths.remove(target_path_str)
            if success:
                self.worktrees = [w for w in self.worktrees if w["path"] != target_path_str]
            self.populate_table()

    @work(exclusive=False)
    async def execute_bulk_deletion(self, target_paths: list[str], names: list[str]) -> None:
        for p in target_paths:
            self.deleting_paths.add(p)
        self.selected_wts.clear()
        self.populate_table()
        self.notify(f"Queued bulk deletion for {len(names)} worktrees...", timeout=3)

        successful_paths = []
        failures = []

        async def safe_delete(path, name):
            try:
                await self._do_single_deletion(path, name)
                successful_paths.append(path)
            except PermissionError as e:
                failures.append(f"{name} (Files in use)")
                config_mgr.append_log("Folder deletion error", {"name": name, "path": path, "error": str(e)})
            except Exception as e:
                failures.append(f"{name} ({str(e)})")
                config_mgr.append_log("Folder deletion error", {"name": name, "path": path, "error": str(e)})

        tasks = [safe_delete(p, n) for p, n in zip(target_paths, names)]
        await asyncio.gather(*tasks)

        if successful_paths:
            self.notify(f"Successfully deleted {len(successful_paths)} worktrees!", severity="success")
        if failures:
            self.notify(f"Failed to delete: {', '.join(failures)}", severity="error")

        for p in target_paths:
            if p in self.deleting_paths:
                self.deleting_paths.remove(p)
        if successful_paths:
            self.worktrees = [w for w in self.worktrees if w["path"] not in successful_paths]
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
            
        # Predict target folder name to touch the path
        parts = []
        if version: parts.append(str(version))
        if desc: parts.append(str(desc))
        if suffix: parts.append(str(suffix))
        folder_name = "-".join(parts)
        target_path = str(Path(self.config["wt_root"]).expanduser().absolute() / folder_name)
        self.touch_worktree(target_path)
        
        self.app.push_screen(DeployScreen({"action": "create", "version": version, "desc": desc, "suffix": suffix}, self.config))

    def handle_table_click(self, event: Click) -> None:
        table = self.query_one("#wt-table", DataTable)
        meta = event.style.meta
        config_mgr.append_log("App received table click", {"meta": str(meta)})
        
        import time
        self._last_table_click_time = time.time()
        
        if "row" in meta and "column" in meta:
            try:
                col_index = meta["column"]
                row_index = meta["row"]
                col_key = list(table.columns.keys())[col_index].value
                
                # Double click opens the worktree (except on checkbox column)
                if event.chain == 2:
                    if col_key != "col-select":
                        from textual.coordinate import Coordinate
                        row_key = table.coordinate_to_cell_key(Coordinate(row_index, 0)).row_key
                        path = str(row_key.value)
                        self.touch_worktree(path)
                        config_mgr.append_log("Worktree Selected (Double-Click)", {"path": path})
                        self.exit({"action": "terminal", "path": path})
                    return

                if col_key == "col-select":
                    from textual.coordinate import Coordinate
                    coord = Coordinate(row_index, col_index)
                    row_key = table.coordinate_to_cell_key(coord).row_key
                    path = str(row_key.value)
                    if is_base_branch(Path(path).name):
                        return
                    
                    if path in self.selected_wts:
                        self.selected_wts.remove(path)
                    else:
                        self.selected_wts.add(path)
                    
                    is_selected = path in self.selected_wts
                    cell_value = "[b green]✔[/b green]" if is_selected else "[dim]☐[/dim]"
                    table.update_cell(row_key, "col-select", cell_value)
                    return

                if col_key == "col-link":
                    from textual.coordinate import Coordinate
                    coord = Coordinate(row_index, col_index)
                    row_key = table.coordinate_to_cell_key(coord).row_key.value
                    wt_name = Path(row_key).name
                    config_mgr.append_log("Runbot Cell Mouse-Clicked", {"branch": wt_name})
                    self.trigger_runbot_for_wt(wt_name)
            except Exception as e:
                config_mgr.append_log("DataTable Click Handler Error", {"error": str(e)})

    def action_open_runbot(self) -> None:
        table = self.query_one("#wt-table", DataTable)
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            wt_name = Path(row_key).name
            self.trigger_runbot_for_wt(wt_name)
        except Exception:
            self.notify("Select a worktree first!", severity="error")

    def trigger_runbot_for_wt(self, wt_name: str) -> None:
        import webbrowser
        
        # Touch the worktree matching wt_name to update its recency
        for wt in self.worktrees:
            if wt["name"] == wt_name:
                self.touch_worktree(wt["path"])
                break
        
        if wt_name == "master":
            webbrowser.open("https://runbot.odoo.com/runbot")
            self.notify("Opened Runbot dashboard in browser.")
            return

        if wt_name in self.resolved_runbot_urls:
            target_url = self.resolved_runbot_urls[wt_name]
            webbrowser.open(target_url)
            self.notify(f"Opened Runbot page for '{wt_name}'!")
            return

        # Fallback to search query
        search_url = f"https://runbot.odoo.com/runbot?search={wt_name}"
        webbrowser.open(search_url)
        self.notify(f"Opening Runbot search for '{wt_name}'...")
