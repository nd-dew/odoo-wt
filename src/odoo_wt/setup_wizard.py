import asyncio
from pathlib import Path
from textual.app import App
from textual import on, work
from textual.binding import Binding
from textual.widgets import Select, Input, Label, Button, ProgressBar, Footer
from textual.containers import Vertical, Horizontal

from .app_config import append_log, save_config
from .system_discovery import fast_scan, expand_path

class WizardApp(App):
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "stylesheet.tcss"
    
    BINDINGS = [
        Binding("escape", "quit", "", show=False),
        Binding("ctrl+c", "quit", "Close", key_display="^c"),
    ]

    def compose(self):
        with Vertical(id="wizard-dialog"):
            yield Label("[bold]Welcome to Odoo WorkTree Tool[/bold]", classes="title")
            yield Label(
                "This tool will create new directories with Community and Enterprise worktrees.\n"
                "You should have a structure like this somewhere on your PC:",
                classes="req"
            )
            
            with Vertical(classes="tree-box"):
                yield Label(
                    "[bold magenta]Worktree Root/[/bold magenta]\n"
                    " ├── master/       (Base Folder)\n"
                    " │    ├── odoo/       (Community clone)\n"
                    " │    └── enterprise/ (Enterprise clone)\n"
                    " └── ...           (Tool creates new ones here)"
                )
            
            yield Label("Step 1: Tell me where that '[bold magenta]Worktree Root[/bold magenta]' is:", classes="step-title")
            yield ProgressBar(id="scanner-progress")
            yield Label("", id="scanner-status")
            yield Select([], id="root-select", classes="hidden", prompt="Select discovered root")
            yield Input(placeholder="Or enter path manually (~/ allowed)...", id="custom-root", classes="hidden")
            
            with Vertical(id="final-steps", classes="hidden"):
                yield Label("[bold]Step 2: UV Environments Path[/bold]", classes="step-title")
                yield Label(
                    "This tool uses `uv` to manage your Python dependencies.\n"
                    "It builds one central virtual environment per Odoo version, "
                    "so they can be instantly reused across all your worktrees without re-downloading packages.",
                    classes="step-desc"
                )
                yield Input(value="~/.envs", id="env-path")
                
                yield Label("[bold]Step 3: Developer Suffix[/bold]", classes="step-title")
                yield Label(
                    "Your personal identifier (e.g. 'pian' or 'test').\n"
                    "This gets automatically appended to the end of your new branch names.",
                    classes="step-desc"
                )
                yield Input(value="pian", id="suffix-input")
                
                yield Label("\nDon't worry, you can change all of these later in the Settings tab!", classes="step-desc")

                with Horizontal(classes="btn-row"):
                    yield Button("Finish Setup", variant="success", id="btn-finish")
        yield Footer()

    def action_quit(self):
        append_log("Wizard Quit")
        self.exit()

    def on_mount(self):
        append_log("Wizard Started")
        self.run_scanner()

    @work(exclusive=True)
    async def run_scanner(self):
        roots = await asyncio.to_thread(fast_scan)
        try:
            self.query_one("#scanner-progress").remove()
        except:
            pass
        
        if roots:
            status = self.query_one("#scanner-status")
            status.update(f"Found {len(roots)} potential root(s)!")
            
            select = self.query_one("#root-select")
            options = [(r, r) for r in roots] + [("Custom Path", "custom")]
            select.set_options(options)
            select.value = roots[0]
            select.remove_class("hidden")
        else:
            self.query_one("#scanner-status").update("No standard roots found. Please specify manually:")
            self.query_one("#custom-root").remove_class("hidden")
            self.query_one("#custom-root").focus()

        self.query_one("#final-steps").remove_class("hidden")

    @on(Select.Changed, "#root-select")
    def on_root_change(self, event):
        append_log("Wizard Root Selected", {"value": str(event.value)})
        custom = self.query_one("#custom-root")
        if event.value == "custom":
            custom.remove_class("hidden")
            custom.focus()
        else:
            custom.add_class("hidden")

    @on(Button.Pressed, "#btn-finish")
    def on_finish(self):
        root_sel = self.query_one("#root-select").value
        wt_root_raw = self.query_one("#custom-root").value if (root_sel == "custom" or str(root_sel) == "Select.BLANK") or not root_sel else root_sel
        wt_root = expand_path(str(wt_root_raw))
        
        env_path_raw = self.query_one("#env-path").value
        env_path = Path(expand_path(str(env_path_raw)))
        if not env_path.exists():
            env_path.mkdir(parents=True, exist_ok=True)

        config = {
            "wt_root": wt_root,
            "env_root": str(env_path),
            "suffix": self.query_one("#suffix-input").value,
            "remote_name": "odoo-dev"
        }
        save_config(config)
        self.notify("Settings saved to ~/.config/odoo-wt.json")
        self.exit(config)
