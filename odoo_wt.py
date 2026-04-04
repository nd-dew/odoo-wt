# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "textual>=0.52.1",
#     "rich>=13.7.1",
# ]
# ///

import os
import sys
import json
import subprocess
from pathlib import Path
from rich.console import Console
from rich.status import Status

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll, Center
from textual.widgets import Header, Footer, Select, Input, Label, Button, TabbedContent, TabPane, DataTable
from textual.screen import ModalScreen
from textual import on

# --- CONFIGURATION ---
CONFIG_FILE = Path.home() / ".config" / "odoo-wt.json"

def load_config():
    default_config = {
        "wt_root": str(Path.home() / "repos" / "Odoo" / "wt"),
        "env_root": str(Path.home() / ".envs"),
        "suffix": "pian",
        "remote_name": "odoo-dev"
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                default_config.update(json.load(f))
        except:
            pass
    return default_config

def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

# --- SYSTEM DISCOVERY ---
def parse_branch_name(name):
    if name.startswith("saas-"):
        parts = name.split("-")
        v = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else name
    else:
        v = name.split("-")[0]
        
    s = ""
    if "-" in name:
        s_candidate = name.rsplit("-", 1)[-1]
        if s_candidate and len(s_candidate) <= 12 and " " not in s_candidate:
            s = s_candidate
            
    return v, s

def discover_system_data(wt_root, default_suffix):
    versions = set()
    suffixes = set([default_suffix, "test", "none"])
    worktrees = []
    
    wt_path = Path(wt_root)
    if wt_path.exists():
        for entry in wt_path.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                name = entry.name
                v, s = parse_branch_name(name)
                
                is_wt = (entry / "odoo" / ".git").exists()
                if is_wt and name != "master":
                    worktrees.append({
                        "name": name,
                        "path": str(entry),
                        "version": v,
                        "suffix": s
                    })

                if v == "master" or v.startswith("saas-") or (v and v[0].isdigit()):
                    versions.add(v)
                if s:
                    suffixes.add(s)

    v_list = sorted(list(versions))
    if "master" in v_list: v_list.remove("master")
    v_list.insert(0, "master")
    v_list.append("none")
    v_list.append("custom...")

    s_list = sorted(list(suffixes))
    if default_suffix in s_list: s_list.remove(default_suffix)
    if "none" in s_list: s_list.remove("none")
    s_list.insert(0, default_suffix)
    s_list.append("none")
    s_list.append("custom...")
    
    return v_list, s_list, worktrees

# --- TEXTUAL UI MODAL ---
class DeleteConfirmScreen(ModalScreen[bool]):
    CSS = """
    DeleteConfirmScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    #delete-dialog {
        width: 50;
        height: auto;
        padding: 2 4;
        border: thick $error;
        background: $surface;
    }
    .del-btn-row {
        align: center middle;
        margin-top: 1;
        height: 3;
    }
    #del-msg {
        text-align: center;
        text-style: bold;
        color: $error;
        width: 100%;
        margin-bottom: 1;
    }
    """
    def __init__(self, wt_name: str):
        super().__init__()
        self.wt_name = wt_name
        self.step = 1

    def compose(self) -> ComposeResult:
        with Vertical(id="delete-dialog"):
            yield Label(f"Delete worktree '{self.wt_name}'? (1/3)", id="del-msg")
            with Horizontal(classes="del-btn-row", id="btn-container"):
                yield Button("Yes, delete", variant="error", id="btn-yes")
                yield Button("Cancel", variant="primary", id="btn-cancel")

    @on(Button.Pressed, "#btn-yes")
    async def on_yes(self):
        self.step += 1
        if self.step > 3:
            self.dismiss(True)
            return

        msg = self.query_one("#del-msg", Label)
        container = self.query_one("#btn-container", Horizontal)
        
        # Await the removal of all children before trying to mount new ones with the same IDs
        await container.query_children().remove()

        if self.step == 2:
            msg.update(f"Are you SURE? (2/3)")
            # Swap: Cancel on Left, Yes on Right
            await container.mount(Button("Cancel", variant="primary", id="btn-cancel"))
            await container.mount(Button("Yes, delete", variant="error", id="btn-yes"))
            self.query_one("#btn-cancel").focus()
            
        elif self.step == 3:
            msg.update(f"Final warning: NUKE '{self.wt_name}'? (3/3)")
            # Swap Back: Yes on Left, Cancel on Right
            await container.mount(Button("Yes, delete", variant="error", id="btn-yes"))
            await container.mount(Button("Cancel", variant="primary", id="btn-cancel"))
            self.query_one("#btn-cancel").focus()

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self):
        self.dismiss(False)


# --- TEXTUAL UI MAIN ---
class OdooWtApp(App):
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen {
        align: center middle;
        background: transparent;
    }
    #dialog {
        width: 80;
        height: auto;
        max-height: 98vh;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    .main-row {
        height: auto;
        margin: 1 0;
        align: center middle;
    }
    .dash {
        padding: 1 0;
        color: $text-muted;
        text-style: bold;
    }
    #version-col { width: 15; height: auto; }
    #desc-col { width: 35; height: auto; }
    #suffix-col { width: 15; height: auto; }
    
    .custom-field {
        display: none;
        margin-top: 0;
        border: solid $accent;
    }
    .custom-field.visible {
        display: block;
    }
    .title {
        text-align: left;
        text-style: bold;
        color: $accent;
        margin: 0 0 1 0;
        height: auto;
    }
    .description {
        text-align: left;
        margin-bottom: 1;
        height: auto;
        width: 100%;
    }
    .tab-description {
        margin: 1 0;
        color: $text-muted;
        text-style: italic;
        height: auto;
        width: 100%;
    }
    .info-box {
        background: $boost;
        padding: 1 2;
        margin: 1 0;
        border-left: thick $accent;
        height: auto;
    }
    .summary-box {
        background: $surface-lighten-1;
        padding: 1 2;
        margin: 1 0;
        border-left: thick $success;
        height: auto;
        width: 100%;
    }
    .settings-container {
        padding: 0 1;
        height: auto;
    }
    .setting-item {
        height: 3;
        margin-bottom: 0;
        align: left middle;
    }
    .setting-label {
        width: 22;
        height: 3;
        content-align: left middle;
        color: $secondary;
        text-style: bold;
    }
    .setting-input {
        width: 1fr;
        height: 3;
    }
    .btn-row {
        align: center middle;
        margin-top: 1;
        height: auto;
    }
    Button {
        margin: 0 1;
    }
    DataTable {
        height: 10;
        margin: 1 0;
        border: solid $accent;
    }
    Tab {
        padding: 0 3;
    }
    """

    BINDINGS = [
        ("ctrl+s", "submit", "Create"),
        ("ctrl+d", "delete_wt", "Delete"),
        ("ctrl+r", "refresh_wts", "Refresh"),
        ("ctrl+t", "next_tab", "Next Tab"),
        ("escape", "quit", "Cancel"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, config, v_list, s_list, worktrees):
        super().__init__()
        self.config = config
        self.v_list = v_list
        self.s_list = s_list
        self.worktrees = worktrees

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label("[bold cyan]Odoo WorkTree Tool[/bold cyan]", classes="title")
            
            yield Label(
                "Opinionated tool for Odoo development. Creates/removes WorkTrees\n"
                "reusing UV environments per Odoo version.",
                classes="description"
            )
            
            yield Label("") # Tiny space
            
            with TabbedContent(id="tabs"):
                with TabPane("[green]Creation[/green]", id="tab-create"):
                    with Vertical(classes="info-box"):
                        yield Label("Format: [bold cyan]VERSION[/bold cyan]-[italic]description[/italic]-[bold magenta]SUFFIX[/bold magenta]")

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

                    yield Label("", id="dynamic-summary", classes="summary-box")

                    with Horizontal(classes="btn-row"):
                        yield Button("Create", variant="success", id="submit-btn")
                        yield Button("Cancel", variant="error", id="cancel-btn")

                with TabPane("[white]Existing[/white] / [red]Removal[/red]", id="tab-manage"):
                    yield Label(
                        "Discovery: Scans 'Worktree Root Path' (in Settings)\n"
                        "for 'odoo/.git' folders.",
                        classes="tab-description"
                    )
                    yield DataTable(id="wt-table", cursor_type="row")
                    with Horizontal(classes="btn-row"):
                        yield Button("Refresh", id="refresh-btn")
                        yield Button("Delete Selected", variant="error", id="delete-btn")

                with TabPane("Settings", id="tab-settings"):
                    with VerticalScroll(classes="settings-container"):
                        yield Label(
                            "Worktree Root: Where new environments are built and scanned.\n"
                            "UV Envs Path: Where shared Python environments (one per version) are stored.\n"
                            "Default Suffix: Your developer ID (quadrigram) used for new branches.\n"
                            "Remote Name: Your personal fork where we check for existing branches.",
                            classes="tab-description"
                        )
                        
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
                            yield Label("Remote Name:", classes="setting-label")
                            yield Input(value=self.config.get("remote_name", "odoo-dev"), id="set-remote", classes="setting-input")
                        
                        with Center(classes="btn-row"):
                            yield Button("Save", variant="primary", id="save-settings")

        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#desc").focus()
        self.populate_table()
        self.update_summary()

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
            if not branch_name:
                branch_name = "<empty>"
                
            wt_root = self.config.get("wt_root", "")
            remote = self.config.get("remote_name", "odoo-dev")
            base_v = version if version else "master"

            summary = (
                f"I will create a new directory at [bold cyan]{wt_root}/{branch_name}[/bold cyan]:\n"
                f"  ├── odoo/       (Community worktree)\n"
                f"  └── enterprise/ (Enterprise worktree)\n\n"
                f"I will pull [bold green]{branch_name}[/bold green] from '{remote}' if it exists.\n"
                f"Otherwise, I will create new worktrees based on 'origin/{base_v}'.\n"
                f"I will use or create the [bold magenta]{base_v}[/bold magenta] UV environment and link it as '.venv'."
            )
            self.query_one("#dynamic-summary", Label).update(summary)
        except Exception:
            pass

    @on(Input.Changed, "#desc")
    @on(Input.Changed, "#custom_version")
    @on(Input.Changed, "#custom_suffix")
    def on_text_changed(self, event) -> None:
        self.update_summary()

    def populate_table(self):
        table = self.query_one("#wt-table")
        table.clear(columns=True)
        table.add_columns("Branch Name", "Version", "Suffix")
        
        for wt in self.worktrees:
            table.add_row(wt["name"], wt["version"], wt["suffix"], key=wt["path"])

    def action_refresh_wts(self) -> None:
        _, _, self.worktrees = discover_system_data(self.config["wt_root"], self.config["suffix"])
        self.populate_table()
        self.notify("Worktrees refreshed!")

    def action_next_tab(self) -> None:
        tabs = self.query_one("#tabs")
        if tabs.active == "tab-create": tabs.active = "tab-manage"
        elif tabs.active == "tab-manage": tabs.active = "tab-settings"
        else: tabs.active = "tab-create"

    @on(Select.Changed, "#version")
    def version_changed(self, event: Select.Changed) -> None:
        custom = self.query_one("#custom_version")
        if event.value == "custom...":
            custom.add_class("visible")
            custom.focus()
        else:
            custom.remove_class("visible")
        self.update_summary()

    @on(Select.Changed, "#suffix")
    def suffix_changed(self, event: Select.Changed) -> None:
        custom = self.query_one("#custom_suffix")
        if event.value == "custom...":
            custom.add_class("visible")
            custom.focus()
        else:
            custom.remove_class("visible")
        self.update_summary()

    @on(Button.Pressed, "#save-settings")
    def save_settings(self) -> None:
        self.config["wt_root"] = self.query_one("#set-wt").value
        self.config["env_root"] = self.query_one("#set-env").value
        self.config["suffix"] = self.query_one("#set-suffix").value
        self.config["remote_name"] = self.query_one("#set-remote").value
        save_config(self.config)
        self.notify("Settings saved!")

    @on(Button.Pressed, "#submit-btn")
    def on_submit_btn(self) -> None:
        self.action_submit()
        
    @on(Button.Pressed, "#refresh-btn")
    def on_refresh_btn(self) -> None:
        self.action_refresh_wts()

    @on(Button.Pressed, "#delete-btn")
    def on_delete_btn(self) -> None:
        self.action_delete_wt()

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_btn(self) -> None:
        self.exit()

    def action_delete_wt(self) -> None:
        table = self.query_one("#wt-table")
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            wt_name = Path(row_key).name
            
            def check_delete(confirm: bool):
                if confirm:
                    self.execute_deletion(row_key, wt_name)
                    
            self.app.push_screen(DeleteConfirmScreen(wt_name), check_delete)
        except Exception as e:
            self.notify("Select a worktree first!", severity="error")

    def execute_deletion(self, target_path_str, name):
        target_path = Path(target_path_str)
        base_odoo = target_path.parent / "master" / "odoo"
        base_ent = target_path.parent / "master" / "enterprise"
        
        if (target_path / "odoo").exists():
            subprocess.run(["git", "worktree", "remove", "-f", str(target_path / "odoo")], cwd=base_odoo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if (target_path / "enterprise").exists():
            subprocess.run(["git", "worktree", "remove", "-f", str(target_path / "enterprise")], cwd=base_ent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        subprocess.run(["rm", "-rf", str(target_path)])
        self.notify(f"Deleted {name} successfully!")
        self.action_refresh_wts()

    def action_submit(self) -> None:
        if self.query_one("#tabs").active != "tab-create":
            return

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

        self.exit({
            "action": "create",
            "version": version,
            "desc": desc,
            "suffix": suffix
        })

# --- DEPLOYMENT LOGIC ---
def run_git(args, cwd=None, capture=False):
    cmd = ["git"] + args
    if capture:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return res.returncode == 0, res.stdout
    else:
        res = subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0

def check_remote(repo, branch, dev_remote):
    success, out = run_git(["ls-remote", "--heads", dev_remote, branch], cwd=repo, capture=True)
    return success and f"refs/heads/{branch}" in out

def check_local(repo, branch):
    return run_git(["rev-parse", "--verify", branch], cwd=repo)

def get_remote(repo):
    success, out = run_git(["remote"], cwd=repo, capture=True)
    if success and "odoo\n" in out:
        return "odoo"
    return "origin"

def deploy(data, config):
    console = Console()
    wt_root = Path(config["wt_root"])
    dev_remote = config.get("remote_name", "odoo-dev")
    
    clean_desc = data["desc"].strip().replace(" ", "_")
    parts = [p for p in [data["version"], clean_desc, data["suffix"]] if p]
    branch_name = "-".join(parts)

    if not branch_name:
        console.print("[red]Error: Branch name cannot be entirely empty.[/red]")
        return

    target_dir = wt_root / branch_name
    base_odoo = wt_root / "master" / "odoo"
    base_ent = wt_root / "master" / "enterprise"

    console.print(f"\n🔍 Checking status for [bold yellow]{branch_name}[/bold yellow]...")

    local_exists = check_local(base_odoo, branch_name)
    remote_exists = check_remote(base_odoo, branch_name, dev_remote) if not local_exists else False
    
    base_v = data["version"] or "master"

    if local_exists:
        status_msg = "[bold green]🔄 Existing (Local)[/bold green] - Will use local branch"
    elif remote_exists:
        status_msg = f"[bold blue]☁️  Existing (Remote)[/bold blue] - Will fetch from {dev_remote}"
    else:
        status_msg = f"[bold magenta]✨ New Branch[/bold magenta] - Will create from origin/{base_v}"

    console.print(f"\n[cyan bold]PLAN SUMMARY[/cyan bold]")
    console.print(f"  - Branch:  [yellow]{branch_name}[/yellow]")
    console.print(f"  - Status:  {status_msg}")
    console.print(f"  - Path:    [yellow]{target_dir}[/yellow]\n")

    confirm = console.input("Proceed with creation? [Y/n] ")
    if confirm.lower() == 'n':
        console.print("Aborted.")
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    with Status("[bold blue]Deploying Odoo Environment...", console=console, spinner="dots") as status:
        for repo, dest, label in [(base_odoo, "odoo", "Community"), (base_ent, "enterprise", "Enterprise")]:
            status.update(f"[bold blue]Setting up {label}...")
            remote = get_remote(repo)

            if run_git(["fetch", dev_remote, f"{branch_name}:{branch_name}", "--force"], cwd=repo):
                run_git(["worktree", "add", str(target_dir / dest), branch_name], cwd=repo)
            else:
                run_git(["fetch", remote, base_v], cwd=repo)
                if check_local(repo, branch_name):
                    run_git(["worktree", "add", str(target_dir / dest), branch_name], cwd=repo)
                else:
                    run_git(["worktree", "add", "-b", branch_name, str(target_dir / dest), f"{remote}/{base_v}"], cwd=repo)
                    run_git(["branch", "--set-upstream-to", f"{remote}/{base_v}", branch_name], cwd=repo)

        status.update("[bold blue]Setting up UV Python Environment...")
        env_root = Path(config["env_root"])
        env_root.mkdir(parents=True, exist_ok=True)
        
        target_env = env_root / base_v
        if not target_env.exists():
            console.print(f"✨ Initializing new UV environment for [yellow]{base_v}[/yellow]...")
            subprocess.run(["uv", "venv", str(target_env), "--python", "3.12"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            req_path = target_dir / "odoo" / "requirements.txt"
            if req_path.exists():
                console.print("📦 Installing Odoo requirements...")
                subprocess.run([
                    "uv", "pip", "install", "-r", str(req_path),
                    "--python", str(target_env / "bin" / "python")
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        venv_symlink = target_dir / ".venv"
        if not venv_symlink.exists():
            try:
                os.symlink(target_env, venv_symlink)
            except:
                pass

    console.print(f"\n🚀 [bold green]SUCCESS![/bold green] Env ready at [cyan]{target_dir}[/cyan]")
    console.print(f"Tip: Run 'occ {branch_name}' to jump in.\n")

def main():
    config = load_config()
    
    if len(sys.argv) > 1:
        branch = sys.argv[1]
        v = branch.split("-")[0] if "-" in branch else "master"
        data = {"action": "create", "version": v, "desc": branch, "suffix": ""}
    else:
        v_list, s_list, worktrees = discover_system_data(config["wt_root"], config["suffix"])
        app = OdooWtApp(config, v_list, s_list, worktrees)
        data = app.run()

    if data:
        if data.get("action") == "create":
            deploy(data, load_config())

if __name__ == "__main__":
    main()
