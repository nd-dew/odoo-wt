import asyncio
from pathlib import Path
from textual.app import App
from textual import on, work
from textual.binding import Binding
from textual.widgets import Select, Input, Label, Button, ProgressBar, Footer
from textual.containers import Vertical, Horizontal, VerticalScroll

from .app_config import config_mgr
from .system_discovery import fast_scan, expand_path

class WizardApp(App):
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "stylesheet.tcss"
    
    BINDINGS = [
        Binding("enter", "submit_step", "Next", show=True, key_display="Enter"),
        Binding("escape", "quit", "", show=False),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True, key_display="Ctrl+Q"),
    ]

    def __init__(self):
        super().__init__()
        self.initial_load = True

    def action_submit_step(self):
        focused = self.focused
        if focused:
            if focused.id == "root-select":
                # Only manually force next if custom isn't selected, 
                # otherwise the Select dropdown catches Enter to select items
                if focused.value != "custom":
                    self.query_one("#env-path").focus()
            elif focused.id == "custom-root":
                self.query_one("#env-path").focus()
            elif focused.id == "env-path":
                self.query_one("#suffix-input").focus()
            elif focused.id == "suffix-input":
                self.query_one("#btn-finish").focus()
            elif focused.id == "btn-finish":
                self.on_finish()

    def compose(self):
        with VerticalScroll(id="wizard-scroll"):
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
                
                yield Label("Step 1: Tell me where that '[bold magenta]Worktree Root[/bold magenta]' is:", classes="step-title", id="scanner-status")
                yield ProgressBar(id="scanner-progress")
                yield Select([], id="root-select", classes="hidden", prompt="Select discovered root")
                yield Input(placeholder="Or enter path manually (~/ allowed)...", id="custom-root", classes="hidden")
                
                with Vertical(id="final-steps", classes="hidden"):
                    yield Label("[bold]Step 2: UV Environments Path[/bold]", classes="step-title")
                    yield Label(
                        "I'm a neat manager; I use `uv` to build one central virtual environment "
                        "per Odoo version so they can be instantly reused. Tell me where to put them:",
                        classes="step-desc"
                    )
                    yield Input(value="~/.envs", id="env-path")
                    
                    yield Label("[bold]Step 3: Developer Suffix[/bold]", classes="step-title")
                    yield Label(
                        "Your personal identifier (e.g. 'pian' or 'test').\n"
                        "This gets automatically appended to the end of your new branch names.",
                        classes="step-desc"
                    )
                    yield Input(placeholder="pian", id="suffix-input")
                    
                    yield Label("\nDon't worry, you can change all of these later in the Settings tab!", classes="step-desc")

                    with Horizontal(classes="btn-row"):
                        yield Button("Finish Setup", variant="success", id="btn-finish")
        yield Footer()

    def action_quit(self):
        config_mgr.append_log("Wizard Quit")
        self.exit()

    def on_mount(self):
        config_mgr.append_log("Wizard Started")
        self.run_scanner()

    @work(exclusive=True)
    async def run_scanner(self):
        roots = await asyncio.to_thread(fast_scan)
        try:
            self.query_one("#scanner-progress").remove()
        except Exception:
            pass
        
        if roots:
            status = self.query_one("#scanner-status")
            status.update("Step 1: Select a root from the proposed ones or set your own:")

            sel = self.query_one("#root-select", Select)
            options = [(r, r) for r in roots] + [("Custom Path", "custom")]
            sel.set_options(options)
            with self.prevent(Select.Changed):
                sel.value = roots[0]
            sel.remove_class("hidden")
            sel.focus()
        else:
            self.query_one("#scanner-status").update("Step 1: No standard roots found. Please specify manually:")
            self.query_one("#custom-root").remove_class("hidden")
            self.query_one("#custom-root").focus()

        self.query_one("#final-steps").remove_class("hidden")

    @on(Select.Changed, "#root-select")
    def on_root_change(self, event):
        config_mgr.append_log("Wizard Root Selected", {"value": str(event.value)})
        custom = self.query_one("#custom-root")
        if event.value == "custom":
            custom.remove_class("hidden")
            custom.focus()
        else:
            custom.add_class("hidden")
            self.query_one("#env-path").focus()

    @on(Input.Submitted, "#custom-root")
    def on_custom_root_submit(self, event):
        self.query_one("#env-path").focus()

    @on(Input.Submitted, "#env-path")
    def on_env_path_submit(self, event):
        self.query_one("#suffix-input").focus()

    @on(Input.Submitted, "#suffix-input")
    def on_suffix_submit(self, event):
        self.query_one("#btn-finish").focus()

    @on(Button.Pressed, "#btn-finish")
    def on_finish(self):
        root_sel = self.query_one("#root-select").value
        use_custom = (
            self.query_one("#root-select").has_class("hidden") or
            root_sel == "custom" or
            not root_sel or
            "Select." in str(root_sel)
        )
        wt_root_raw = self.query_one("#custom-root").value if use_custom else root_sel
        
        # Symmetrical input validation: do not allow empty, blank, or Select sentinels!
        wt_root_str = str(wt_root_raw).strip()
        if not wt_root_str or "Select." in wt_root_str:
            self.notify("Error: Please enter or select a valid Worktree Root path!", severity="error")
            self.query_one("#custom-root").focus()
            return
            
        wt_root = expand_path(wt_root_str)
        
        # Automatically create missing Worktree Root folder and notify
        wt_root_path = Path(wt_root)
        if not wt_root_path.exists():
            self.notify(f"📁 Worktree Root '{wt_root_str}' does not exist. Creating it...", severity="information", timeout=6.0)
            wt_root_path.mkdir(parents=True, exist_ok=True)

        env_path_raw = self.query_one("#env-path").value
        env_path = Path(expand_path(str(env_path_raw)))
        if not env_path.exists():
            env_path.mkdir(parents=True, exist_ok=True)

        # Check if base master clones are missing under the newly created/existing root to provide warning guidance
        base_odoo = wt_root_path / "master" / "odoo"
        base_ent = wt_root_path / "master" / "enterprise"
        missing = []
        if not base_odoo.exists() or not (base_odoo / ".git").exists():
            missing.append("Community (odoo)")
        if not base_ent.exists() or not (base_ent / ".git").exists():
            missing.append("Enterprise")

        if missing:
            self.notify(
                f"⚠️ Base clones for {', '.join(missing)} are missing under master/. Remember to clone them!",
                severity="warning",
                timeout=8.0
            )

        config = {
            "wt_root": wt_root,
            "env_root": str(env_path),
            "suffix": self.query_one("#suffix-input").value.strip() or "pian",
            "remote_name": "odoo-dev",
            "community_dir": "odoo",
            "enterprise_dir": "enterprise"
        }
        config_mgr.save(config)
        self.notify("Settings saved to ~/.config/odoo-wt.json")
        self.exit(config)
