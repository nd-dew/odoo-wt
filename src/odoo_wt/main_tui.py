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

spell = SpellChecker()
spell.word_frequency.load_words(['odoo', 'saas', 'erp', 'mrp', 'pos', 'crm', 'wt', 'api', 'ui', 'ux', 'db', 'sql', 'backend', 'frontend', 'js', 'py', 'xml', 'owl', 'mac', 'linux', 'windows', 'repo'])

from .app_config import config_mgr
from .system_discovery import discover_system_data, get_remote, run_git
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
    "set-show-prefix": "Toggle visibility of the version dropdown in the Creation tab.",
    "set-show-suffix": "Toggle visibility of the suffix dropdown in the Creation tab.",
    "set-show-desc": "Toggle visibility of the app description text at the top.",
    "set-config-path": "Moving this will migrate your config file to a new location.",
    "set-log-path": "Moving this will migrate your log file to a new location.",
}

class OdooWtApp(App):
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "stylesheet.tcss"

    BINDINGS = [
        Binding("ctrl+s", "submit", "Create", key_display="^S"),
        Binding("ctrl+d", "delete_wt", "Delete", key_display="^D"),
        Binding("ctrl+r", "refresh", "Refresh/Reset", key_display="^R"),
        Binding("ctrl+t", "next_tab", "Tab", key_display="^T"),
        Binding("ctrl+tab", "next_tab", "", show=False),
        Binding("c", "copy_text", "Copy", key_display="C"),
        Binding("escape", "quit", "", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True, key_display="^Q"),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(self, config, v_list, s_list, worktrees):
        super().__init__()
        self.config = config
        
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
        self.save_timer = None

    @on(DescendantFocus)
    def on_descendant_focus(self, event: DescendantFocus) -> None:
        try:
            help_bar = self.query_one("#global-help-bar", Static)
            active_tab = self.query_one("#tabs").active
            
            base_shortcuts = "[bold]Shortcuts:[/bold] ^S (Create) | ^D (Delete) | ^R (Refresh) | ^T (Next Tab) | ^Q (Quit)"
            shortcuts = base_shortcuts
            
            if active_tab == "tab-manage":
                shortcuts += " | [bold cyan]Enter[/bold cyan] (Open Terminal)"
            
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
        except Exception: pass

    @on(Key)
    def handle_global_keys(self, event: Key) -> None:
        try:
            active_tab = self.query_one("#tabs").active
            focused = self.focused
            
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
        except Exception: pass

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            with Horizontal(id="top-bar"):
                with Vertical(id="title-container"):
                    yield Label("Odoo WorkTree Tool", classes="title")
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
                with TabPane("Existing / Removal", id="tab-manage"):
                    yield Label("Discovery: Scans 'Worktree Root Path' (in Settings)\nfor 'odoo/.git' folders. [bold cyan]Hint: Double-click or press Enter on a row to open in terminal.[/bold cyan]", classes="tab-description")
                    yield Input(placeholder="Fuzzy search worktrees...", id="wt-search", classes="search-input")
                    yield DataTable(id="wt-table", cursor_type="row")
                    with Horizontal(classes="btn-row"):
                        yield Button("Refresh", id="refresh-btn")
                        yield Button("Delete Selected", variant="error", id="delete-btn")
                with TabPane("Settings", id="tab-settings"):
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
                            yield Label("Show Prefix (Version):", classes="setting-label")
                            yield Switch(value=self.config.get("show_prefix", True), id="set-show-prefix", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Show Suffix:", classes="setting-label")
                            yield Switch(value=self.config.get("show_suffix", True), id="set-show-suffix", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Show Description:", classes="setting-label")
                            yield Switch(value=self.config.get("show_desc", True), id="set-show-desc", classes="setting-input")
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
        yield Static("[bold]Shortcuts:[/bold] ^S (Create) | ^D (Delete) | ^R (Refresh) | ^T (Next Tab) | ^Q (Quit)", id="global-help-bar", classes="help-bar")

    def on_mount(self) -> None:
        config_mgr.append_log("App Started")
        
        default_tab = self.config.get("default_tab", "tab-create")
        try:
            self.query_one("#tabs", TabbedContent).active = default_tab
            if default_tab == "tab-manage":
                self.query_one("#wt-search").focus()
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
        wt_root = Path(self.config["wt_root"])
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
        except Exception:
            pass

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
            self.query_one("#set-wt").focus()
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
            wt_root = self.config.get("wt_root", "")
            remote = self.config.get("remote_name", "odoo-dev")
            base_v = version if version else "master"
            
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

            summary = (
                f"[bold]Outcome:[/bold]\n"
                f"1. [bold cyan]Branch Status:[/bold cyan] {self.branch_status or 'Ready...'}\n"
                f"2. I will create a new directory at [bold green]{wt_root}/{branch_name}[/bold green]:\n"
                f"   ├── odoo/       (Community worktree)\n"
                f"   └── enterprise/ (Enterprise worktree)\n"
                f"3. I will use or create the [bold magenta]{base_v}[/bold magenta] UV environment and link it as '.venv'."
            )
            self.query_one("#dynamic-summary", Label).update(summary)
        except Exception: pass

    @on(Input.Changed, "#desc")
    @on(Input.Changed, "#custom_version")
    @on(Input.Changed, "#custom_suffix")
    def on_text_changed(self, event) -> None: 
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
                self.update_summary()
                return

            clean_desc = str(desc).strip().replace(" ", "_")
            parts = [p for p in [version if version != "none" else "", clean_desc, suffix if suffix != "none" else ""] if p]
            branch_name = "-".join(parts)
            
            if any(w['name'] == branch_name for w in self.worktrees):
                self.branch_status = "[bold red]A WORKTREE WITH THIS NAME ALREADY EXISTS![/bold red]"
                self.update_summary()
                return
            
            self.branch_status = "Checking..."
            self.update_summary()
            
            await asyncio.sleep(0.5) # Debounce
            
            wt_root = Path(self.config["wt_root"])
            base_odoo = wt_root / "master" / "odoo"
            dev_remote = self.config.get("remote_name", "odoo-dev")
            
            # Check local git
            from .system_discovery import check_local, check_remote
            is_local = await asyncio.to_thread(check_local, base_odoo, branch_name)
            
            # Spell Check
            words = clean_desc.replace("-", "_").split("_")
            unknown = spell.unknown(words)
            unknown = {w for w in unknown if not w.isnumeric() and len(w) > 2}
            
            # Ignore configured and active suffixes
            cfg_suffix = self.config.get("suffix", "")
            if cfg_suffix:
                unknown.discard(cfg_suffix)
            if suffix and suffix != "none":
                unknown.discard(suffix)
                
            spell_warning = f" [bold red](Typo? {', '.join(unknown)})[/bold red]" if unknown else ""

            if is_local:
                self.branch_status = f"[bold yellow]Found branch '{branch_name}' locally.[/bold yellow]{spell_warning}"
            else:
                is_remote = await asyncio.to_thread(check_remote, base_odoo, branch_name, dev_remote)
                if is_remote:
                    self.branch_status = f"[bold green]Found branch on '{dev_remote}'.[/bold green]{spell_warning}"
                else:
                    self.branch_status = f"[bold white]New branch will be created.[/bold white]{spell_warning}"
            
            self.update_summary()
        except Exception:
            pass

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
                    if len(details_str) > 60:
                        details_str = details_str[:57] + "..."
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
        self.query_one("#set-config-path", Input).value = self.config.get("config_path", "")
        self.query_one("#set-log-path", Input).value = self.config.get("log_path", "")
        self.query_one("#set-show-prefix", Switch).value = self.config.get("show_prefix", True)
        self.query_one("#set-show-suffix", Switch).value = self.config.get("show_suffix", True)
        self.query_one("#set-show-desc", Switch).value = self.config.get("show_desc", True)
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
    @on(Input.Changed, "#set-config-path")
    @on(Input.Changed, "#set-log-path")
    @on(Switch.Changed, "#set-default-tab")
    @on(Switch.Changed, "#set-show-prefix")
    @on(Switch.Changed, "#set-show-suffix")
    @on(Switch.Changed, "#set-show-desc")
    def on_setting_changed(self, event) -> None:
        if self.is_mounted:
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

        ig_v = [v.strip() for v in self.query_one("#set-ig-v", Input).value.split(",") if v.strip()]
        ig_s = [s.strip() for s in self.query_one("#set-ig-s", Input).value.split(",") if s.strip()]
        self.config["ignored_versions"] = ig_v
        self.config["ignored_suffixes"] = ig_s

        config_mgr.save(self.config)
        config_mgr.append_log("Settings Auto-Saved", self.config)
        
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
