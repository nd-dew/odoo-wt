import json
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll, Center
from textual.widgets import Header, Footer, Select, Input, Label, Button, TabbedContent, TabPane, DataTable
from textual import on, work
from textual.binding import Binding

from .app_config import append_log, LOG_FILE, save_config, load_config
from .system_discovery import discover_system_data, get_remote, run_git
from .custom_screens import DeleteConfirmScreen, DeployScreen, LogDetailScreen

class OdooWtApp(App):
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "stylesheet.tcss"
    

    @property
    def bindings(self) -> list[Binding]:
        # We need to be careful if #tabs is not yet mounted
        try:
            active = self.query_one("#tabs").active
        except:
            active = "tab-create"
            
        return [
            Binding("ctrl+s", "submit", "Create", key_display="Ctrl+S", show=(active == "tab-create")),
            Binding("ctrl+d", "delete_wt", "Delete", key_display="Ctrl+D", show=(active == "tab-manage")),
            Binding("ctrl+r", "refresh", "Reset" if active == "tab-settings" else "Refresh", key_display="Ctrl+R", show=(active != "tab-create")),
            Binding("ctrl+t", "next_tab", "Tab", key_display="Ctrl+T"),
            Binding("escape", "quit", "", show=False),
            Binding("ctrl+c", "quit", "Close", key_display="Ctrl+C"),
        ]


    def __init__(self, config, v_list, s_list, worktrees):
        super().__init__()
        self.config = config
        self.v_list = v_list
        self.s_list = s_list
        self.worktrees = worktrees
        self.fetched_versions = set()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            with Horizontal(id="top-bar"):
                with Vertical(id="title-container"):
                    yield Label("Odoo WorkTree Tool", classes="title")
                    yield Label("Opinionated tool for Odoo development. Creates/removes WorkTrees\nreusing UV environments per Odoo version.", classes="description")
                yield Button("X", id="btn-close-app", classes="close-btn")
            yield Label("")
            with TabbedContent(id="tabs"):
                with TabPane("Creation", id="tab-create"):
                    yield Label("What branch do you need?", classes="tab-description")

                    with Horizontal(classes="main-row"):
                        with Vertical(id="version-col"):
                            yield Select(((v, v) for v in self.v_list), value=self.v_list[0], id="version", prompt="Ver")
                            yield Input(placeholder="Ver...", id="custom_version", classes="custom-field")

                        yield Label("-", classes="dash")

                        with Vertical(id="desc-col"):
                            yield Input(placeholder="fix_bug", id="desc")

                        yield Label("-", classes="dash")

                        with Vertical(id="suffix-col"):
                            yield Select(((s, s) for s in self.s_list), value=self.s_list[0], id="suffix", prompt="Suf")
                            yield Input(placeholder="Suf...", id="custom_suffix", classes="custom-field")

                    yield Label(
                        "Deployment Strategy (Surgical Safety):\n"
                        "1. Remote Check: Tries to pull the exact branch from your remote (e.g., odoo-dev).\n"
                        "2. Local Check: If it's not on your remote, it checks your local .git folder.\n"
                        "3. Fresh Start: If neither exist, creates a new branch from the official base version.",
                        classes="strategy-desc"
                    )
                    yield Label("", id="dynamic-summary", classes="summary-box")
                    with Horizontal(classes="btn-row"):
                        yield Button("Create", variant="success", id="submit-btn")
                with TabPane("Existing / Removal", id="tab-manage"):
                    yield Label("Discovery: Scans 'Worktree Root Path' (in Settings)\nfor 'odoo/.git' folders.", classes="tab-description")
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
                            yield Label("Community Dir:", classes="setting-label")
                            yield Input(value=self.config.get("community_dir", "odoo"), id="set-comm", classes="setting-input")
                        with Horizontal(classes="setting-item"):
                            yield Label("Enterprise Dir:", classes="setting-label")
                            yield Input(value=self.config.get("enterprise_dir", "enterprise"), id="set-ent", classes="setting-input")
                        yield Label(
                            "Worktree Root: Base directory where worktree folders are created.\n"
                            "UV Envs Path: Directory storing shared Python virtual environments.\n"
                            "Default Suffix: Developer quadrigram appended to new branches.\n"
                            "Dev Remote: Your personal fork (e.g. 'odoo-dev'). Used to push your features for PRs, and fetch colleagues' branches.\n"
                            "Repo Dirs: Names of the subfolders created inside each worktree.",
                            classes="tab-description"
                        )
                        with Center(classes="btn-row"):
                            yield Button("Save", variant="primary", id="save-settings")
                with TabPane("Logs", id="tab-logs"):
                    yield Label("System Logs (Newest first)", classes="tab-description")
                    yield DataTable(id="logs-table", cursor_type="row")
                    with Horizontal(classes="btn-row"):
                        yield Button("Refresh", id="refresh-logs-btn")
                        yield Button("Clear Logs", variant="error", id="clear-logs-btn")
        yield Footer()

    def on_mount(self) -> None:
        append_log("App Started")
        self.query_one("#desc").focus()
        self.populate_table()
        self.populate_logs_table()
        self.update_summary()
        v_sel = self.query_one("#version", Select).value
        if v_sel and str(v_sel) != "custom...":
            self.background_fetch(str(v_sel))

    @work(exclusive=True, thread=True)
    async def background_fetch(self, version: str) -> None:
        if not version or version == "none" or version in self.fetched_versions:
            return
        wt_root = Path(self.config["wt_root"])
        base_odoo = wt_root / "master" / "odoo"
        base_ent = wt_root / "master" / "enterprise"
        if not base_odoo.exists(): return
        append_log("Background Fetch Started", {"version": version})
        
        def fetch_task(args):
            repo, label = args
            try:
                remote = get_remote(repo)
                append_log(f"Prefetch {label} Started", {"version": version, "remote": remote})
                run_git(["fetch", remote, version], cwd=repo)
                append_log(f"Prefetch {label} Finished", {"version": version, "remote": remote})
            except Exception as e:
                append_log(f"Prefetch {label} Failed", {"version": version, "error": str(e)})

        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(fetch_task, [(base_odoo, "Community"), (base_ent, "Enterprise")]))
            
        self.fetched_versions.add(version)
        append_log("Background Fetch Finished", {"version": version})

    @on(TabbedContent.TabActivated, "#tabs")
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        tabs = self.query_one("#tabs")
        active_pane = tabs.active
        append_log("Tab Changed", {"tab": active_pane})
        
        if active_pane == "tab-create":
            self.query_one("#desc").focus()
        elif active_pane == "tab-manage":
            self.query_one("#wt-table").focus()
        elif active_pane == "tab-settings":
            self.query_one("#set-wt").focus()
        elif active_pane == "tab-logs":
            self.populate_logs_table()
            self.query_one("#logs-table").focus()
        self.query_one(Footer).refresh()

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
            summary = (
                f"[bold]Outcome:[/bold]\n"
                f"1. I will create a new directory at [bold green]{wt_root}/{branch_name}[/bold green]:\n"
                f"   ├── odoo/       (Community worktree)\n"
                f"   └── enterprise/ (Enterprise worktree)\n"
                f"2a. I will pull [bold green]{branch_name}[/bold green] from '{remote}' if it exists.\n"
                f"2b. Otherwise, I will create new worktrees based on 'origin/[bold magenta]{base_v}[/bold magenta]'.\n"
                f"3. I will use or create the [bold magenta]{base_v}[/bold magenta] UV environment and link it as '.venv'."
            )
            self.query_one("#dynamic-summary", Label).update(summary)
        except Exception: pass

    @on(Input.Changed, "#desc")
    @on(Input.Changed, "#custom_version")
    @on(Input.Changed, "#custom_suffix")
    def on_text_changed(self, event) -> None: self.update_summary()

    @on(Input.Submitted, "#desc")
    @on(Input.Submitted, "#custom_version")
    @on(Input.Submitted, "#custom_suffix")
    def on_input_submitted(self, event) -> None:
        append_log("Enter Key Pressed", {"input": event.control.id})
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
            except:
                return iso_str

        if LOG_FILE.exists():
            try:
                with open(LOG_FILE, "r") as f:
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
            except: pass

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
        if LOG_FILE.exists():
            LOG_FILE.unlink()
        self.populate_logs_table()
        self.notify("Logs cleared!")

    def populate_table(self):
        table = self.query_one("#wt-table")
        table.clear(columns=True)
        table.add_columns("Branch Name", "Version", "Suffix")
        for wt in self.worktrees:
            table.add_row(wt["name"], wt["version"], wt["suffix"], key=wt["path"])


    def action_reset_settings(self) -> None:
        self.config = load_config()
        self.query_one("#set-wt", Input).value = self.config.get("wt_root", "")
        self.query_one("#set-env", Input).value = self.config.get("env_root", "")
        self.query_one("#set-suffix", Input).value = self.config.get("suffix", "")
        self.query_one("#set-remote", Input).value = self.config.get("remote_name", "odoo-dev")
        self.query_one("#set-comm", Input).value = self.config.get("community_dir", "odoo")
        self.query_one("#set-ent", Input).value = self.config.get("enterprise_dir", "enterprise")
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
        append_log("App Quit")
        self.exit()

    def action_next_tab(self) -> None:
        append_log("Next Tab Shortcut Used")
        tabs = self.query_one("#tabs")
        if tabs.active == "tab-create": tabs.active = "tab-manage"
        elif tabs.active == "tab-manage": tabs.active = "tab-settings"
        elif tabs.active == "tab-settings": tabs.active = "tab-logs"
        else: tabs.active = "tab-create"

    @on(Select.Changed, "#version")
    def version_changed(self, event: Select.Changed) -> None:
        append_log("Version Dropdown Changed", {"value": str(event.value)})
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
        append_log("Suffix Dropdown Changed", {"value": str(event.value)})
        custom = self.query_one("#custom_suffix")
        if event.value == "custom...": custom.add_class("visible"); custom.focus()
        else: custom.remove_class("visible")
        self.update_summary()

    @on(Button.Pressed, "#save-settings")
    def save_settings(self) -> None:
        self.config["wt_root"] = self.query_one("#set-wt").value
        self.config["env_root"] = self.query_one("#set-env").value
        self.config["suffix"] = self.query_one("#set-suffix").value
        self.config["remote_name"] = self.query_one("#set-remote").value
        self.config["community_dir"] = self.query_one("#set-comm").value
        self.config["enterprise_dir"] = self.query_one("#set-ent").value
        save_config(self.config)
        append_log("Settings Saved", self.config)
        self.notify("Settings saved!")

    @on(Button.Pressed, "#submit-btn")
    def on_submit_btn(self) -> None: self.action_submit()
    
    @on(Button.Pressed, "#refresh-btn")
    def on_refresh_btn(self) -> None:
        append_log("Refresh Button Clicked")
        self.action_refresh_wts()
        
    @on(Button.Pressed, "#delete-btn")
    def on_delete_btn(self) -> None:
        append_log("Delete Button Clicked")
        self.action_delete_wt()
        
    @on(Button.Pressed, "#btn-close-app")
    def on_close_app_btn(self) -> None:
        append_log("Cancel Button Clicked")
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

    def execute_deletion(self, target_path_str, name):
        target_path = Path(target_path_str)
        base_odoo = target_path.parent / "master" / "odoo"
        base_ent = target_path.parent / "master" / "enterprise"
        if (target_path / "odoo").exists():
            run_git(["worktree", "remove", "-f", str(target_path / "odoo")], cwd=base_odoo)
        if (target_path / "enterprise").exists():
            run_git(["worktree", "remove", "-f", str(target_path / "enterprise")], cwd=base_ent)
        import shutil
        try:
            shutil.rmtree(target_path)
        except:
            pass
        append_log("Deleted Worktree", {"name": name, "path": target_path_str})
        self.notify(f"Deleted {name} successfully!")
        self.action_refresh_wts()

    def action_submit(self) -> None:
        if self.query_one("#tabs").active != "tab-create": return
        v_sel = self.query_one("#version").value
        version = self.query_one("#custom_version").value if v_sel == "custom..." else v_sel
        desc = self.query_one("#desc").value
        s_sel = self.query_one("#suffix").value
        suffix = self.query_one("#custom_suffix").value if s_sel == "custom..." else s_sel
        if version == "none": version = ""
        if suffix == "none": suffix = ""
        if s_sel == "custom..." and suffix and suffix != "none":
            self.config["suffix"] = suffix
            save_config(self.config)
        self.app.push_screen(DeployScreen({"action": "create", "version": version, "desc": desc, "suffix": suffix}, self.config))
