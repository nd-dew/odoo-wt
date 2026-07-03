import asyncio
import os
import json
from pathlib import Path
from textual import on, work
from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.widgets import Label, Button, ProgressBar, RichLog
from textual.containers import Vertical, Horizontal, VerticalScroll

from .app_config import config_mgr
from .system_discovery import get_remote, check_local
from .deployment_engine import DeployEngine, DeployUpdate

class DeleteConfirmScreen(ModalScreen[bool]):
    def __init__(self, wt_name: str):
        super().__init__()
        self.wt_name = wt_name
        self.step = 1

    def on_key(self, event) -> None:
        if event.key == "left":
            self.focus_previous()
        elif event.key == "right":
            self.focus_next()

    def compose(self):
        with Vertical(id="delete-dialog"):
            yield Label(f"Delete worktree '{self.wt_name}'? (1/3)", id="del-msg")
            with Horizontal(classes="del-btn-row", id="btn-container"):
                yield Button("Yes, delete", variant="error", id="btn-yes")
                yield Button("Cancel", variant="primary", id="btn-cancel")

    @on(Button.Pressed, "#btn-yes")
    async def on_yes(self):
        config_mgr.append_log("Delete Confirm Step", {"step": self.step, "worktree": self.wt_name})
        self.step += 1
        if self.step > 3:
            self.dismiss(True)
            return
        msg = self.query_one("#del-msg", Label)
        container = self.query_one("#btn-container", Horizontal)
        await container.query_children().remove()
        if self.step == 2:
            msg.update(f"Are you SURE? (2/3)")
            await container.mount(Button("Cancel", variant="primary", id="btn-cancel"))
            await container.mount(Button("Yes, delete", variant="error", id="btn-yes"))
        elif self.step == 3:
            msg.update(f"Final warning: NUKE '{self.wt_name}'? (3/3)")
            await container.mount(Button("Yes, delete", variant="error", id="btn-yes"))
            await container.mount(Button("Cancel", variant="primary", id="btn-cancel"))
        self.query_one("#btn-cancel").focus()

    @on(Button.Pressed, "#btn-cancel")
    def on_cancel(self):
        config_mgr.append_log("Delete Cancelled", {"worktree": self.wt_name})
        self.dismiss(False)


class DeployScreen(Screen):
    BINDINGS = [
        Binding("t", "terminal", "Terminal", show=False),
        Binding("v", "vscode", "VS Code", show=False),
        Binding("b", "back", "Back", show=False),
        Binding("x", "exit", "Exit", show=False),
    ]

    def action_terminal(self):
        if not self.query_one("#success-footer").has_class("hidden"):
            self.on_terminal()
            
    def action_vscode(self):
        if not self.query_one("#success-footer").has_class("hidden"):
            self.on_vscode()
            
    def action_back(self):
        if not self.query_one("#success-footer").has_class("hidden"):
            self.on_back()
            
    def action_exit(self):
        if not self.query_one("#success-footer").has_class("hidden"):
            self.on_exit()

    def __init__(self, data, config):
        super().__init__()
        self.data = data
        self.config = config
        self.engine = DeployEngine(config, data)

    def compose(self):
        with VerticalScroll(id="deploy-logs-scroll"):
            with Vertical(classes="log-box"):
                with Horizontal(classes="log-header"):
                    yield Label("Community", classes="log-title")
                    yield ProgressBar(id="prog-odoo", show_eta=False)
                yield RichLog(id="log-odoo", markup=False, highlight=False)
                
            with Vertical(classes="log-box"):
                with Horizontal(classes="log-header"):
                    yield Label("Enterprise", classes="log-title")
                    yield ProgressBar(id="prog-ent", show_eta=False)
                yield RichLog(id="log-ent", markup=False, highlight=False)
                
            with Vertical(classes="log-uv-box", id="uv-box"):
                with Horizontal(classes="log-header"):
                    yield Label("UV Env", classes="log-title")
                    yield ProgressBar(id="prog-uv", show_eta=False)
                yield RichLog(id="log-uv", markup=False, highlight=False)
                
        with Vertical(id="success-footer", classes="hidden"):
            yield Label("", id="success-message", classes="success-msg")
            with Horizontal(classes="success-btn-row"):
                yield Button("(T)erminal", variant="success", id="btn-terminal")
                yield Button("(V)S Code", variant="primary", id="btn-vscode")
                yield Button("(B)ack to Tool", variant="warning", id="btn-back")
                yield Button("E(x)it", variant="error", id="btn-exit")

    def on_mount(self):
        self.run_deployment()

    @work(exclusive=True)
    async def run_deployment(self):
        config_mgr.append_log("Deployment Started", {"branch": self.engine.branch_name, "version": self.data["version"]})
        self.engine.target_dir.mkdir(parents=True, exist_ok=True)
        
        base_odoo = self.engine.wt_root / "master" / self.engine.comm_dir
        base_ent = self.engine.wt_root / "master" / self.engine.ent_dir

        async def handle_updates(gen):
            async for update in gen:
                if update.total is not None:
                    self.query_one(f"#prog-{update.category}", ProgressBar).update(total=update.total)
                if update.advance:
                    self.query_one(f"#prog-{update.category}", ProgressBar).advance(update.advance)
                if update.log_line:
                    self.query_one(f"#log-{update.category}", RichLog).write(update.log_line)

        await asyncio.gather(
            handle_updates(self.engine.deploy_repo(base_odoo, self.engine.comm_dir, "odoo")),
            handle_updates(self.engine.deploy_repo(base_ent, self.engine.ent_dir, "ent")),
            handle_updates(self.engine.setup_uv())
        )

        try:
            self.query_one("#log-uv", RichLog).write("Generating VS Code launch configuration...")
            await self.engine.setup_vscode()
            self.query_one("#log-uv", RichLog).write("✅ VS Code launch configuration created.")
        except Exception as e:
            self.query_one("#log-uv", RichLog).write(f"[bold red]Failed to create VS Code launch config: {e}[/bold red]")

        if self.engine.has_errors:
            self.show_failure_footer()
            return

        config_mgr.append_log("Deployment Success", {"branch": self.engine.branch_name, "path": str(self.engine.target_dir)})
        self.show_success_footer()

    def show_success_footer(self):
        msg = self.query_one("#success-message", Label)
        msg.update(f"SUCCESS! Worktree ready at: {self.engine.target_dir}\nWhat would you like to do next?")
        self.query_one("#success-footer").remove_class("hidden")
        self.query_one("#btn-terminal").focus()

    def show_failure_footer(self):
        msg = self.query_one("#success-message", Label)
        msg.update(f"[bold red]❌ DEPLOYMENT FAILED![/bold red] Base repositories were not found, or worktree operations aborted.\nPlease check the logs above.")
        
        # Hide action buttons that depend on successful worktrees
        try:
            self.query_one("#btn-terminal").add_class("hidden")
            self.query_one("#btn-vscode").add_class("hidden")
        except Exception:
            pass
            
        self.query_one("#success-footer").remove_class("hidden")
        self.query_one("#btn-back").focus()

    @on(Button.Pressed, "#btn-terminal")
    def on_terminal(self):
        config_mgr.append_log("Deployment Complete", {"choice": "terminal"})
        self.app.exit({"action": "terminal", "path": str(self.engine.target_dir)})

    @on(Button.Pressed, "#btn-vscode")
    def on_vscode(self):
        config_mgr.append_log("Deployment Complete", {"choice": "vscode"})
        self.app.exit({"action": "vscode", "path": str(self.engine.target_dir)})

    @on(Button.Pressed, "#btn-back")
    def on_back(self):
        config_mgr.append_log("Deployment Complete", {"choice": "back"})
        try:
            self.query_one("#btn-terminal").remove_class("hidden")
            self.query_one("#btn-vscode").remove_class("hidden")
        except Exception:
            pass
        self.dismiss()

    @on(Button.Pressed, "#btn-exit")
    def on_exit(self):
        config_mgr.append_log("Deployment Complete", {"choice": "exit"})
        self.app.exit()

class LogDetailScreen(ModalScreen[None]):
    def __init__(self, ts, action, details):
        super().__init__()
        self.ts = ts
        self.action = action
        self.details = details

    def compose(self):
        with Vertical(id="log-detail-dialog"):
            yield Label(f"[{self.ts}] {self.action}", classes="log-detail-title", markup=False)
            try:
                parsed = json.loads(self.details)
                pretty_details = json.dumps(parsed, indent=4)
            except json.JSONDecodeError:
                pretty_details = str(self.details)
            with VerticalScroll():
                yield Label(pretty_details, classes="log-detail-text", markup=False)
            with Horizontal(classes="log-detail-btn-row"):
                yield Button("Close", variant="primary", id="btn-close-log")

    @on(Button.Pressed, "#btn-close-log")
    def on_close(self):
        self.dismiss()

class RunbotMonitorScreen(ModalScreen[None]):
    def __init__(self, wt_name: str):
        super().__init__()
        self.wt_name = wt_name
        self.is_monitoring = True
        self.batch_url = None

    def compose(self):
        with Vertical(id="runbot-dialog"):
            yield Label("Runbot Monitor 🤖", classes="title")
            yield Label(f"Branch: [bold cyan]{self.wt_name}[/bold cyan]")
            yield Label(f"Resolving latest batch on Runbot...", id="runbot-status")
            yield Label("", id="runbot-url")
            yield Label("", id="runbot-timer")
            with Horizontal(classes="runbot-row"):
                yield Button("Close", variant="primary", id="btn-close-runbot")

    @on(Button.Pressed, "#btn-close-runbot")
    def on_close(self):
        self.is_monitoring = False
        self.dismiss()

    def on_mount(self) -> None:
        self.resolve_and_monitor()

    @work(exclusive=True, thread=True)
    def resolve_and_monitor(self) -> None:
        import re
        import urllib.request
        import time

        # 1. Resolve batch URL
        search_url = f"https://runbot.odoo.com/runbot?search={self.wt_name}"
        self.call_from_thread(self.query_one("#runbot-status", Label).update, f"Querying Runbot search for '{self.wt_name}'...")
        
        batch_url = None
        req = urllib.request.Request(search_url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req) as response:
                html = response.read().decode('utf-8')
            match = re.search(r'href="/runbot/batch/(\d+)"', html)
            if match:
                batch_id = match.group(1)
                batch_url = f"https://runbot.odoo.com/runbot/batch/{batch_id}"
        except Exception as e:
            self.call_from_thread(self.query_one("#runbot-status", Label).update, f"[bold red]Search failed: {e}[/bold red]")
            return

        if not batch_url:
            self.call_from_thread(self.query_one("#runbot-status", Label).update, "[bold red]No active/recent batch found for this branch on Runbot.[/bold red]")
            return

        self.batch_url = batch_url
        self.call_from_thread(self.query_one("#runbot-url", Label).update, f"[bold]Batch URL:[/bold] [underline]{batch_url}[/underline]")

        # 2. Polling loop
        while self.is_monitoring:
            self.call_from_thread(self.query_one("#runbot-status", Label).update, "⏳ Fetching batch build status...")
            req_batch = urllib.request.Request(batch_url, headers={'User-Agent': 'Mozilla/5.0'})
            try:
                with urllib.request.urlopen(req_batch) as resp:
                    batch_html = resp.read().decode('utf-8')
                
                spinners = batch_html.count("fa-spinner")
                
                if spinners > 0:
                    self.call_from_thread(self.query_one("#runbot-status", Label).update, f"⏳ [bold yellow]Monitoring:[/bold yellow] {spinners} builds running.")
                    # Countdown for 30s
                    for i in range(30, 0, -1):
                        if not self.is_monitoring:
                            break
                        self.call_from_thread(self.query_one("#runbot-timer", Label).update, f"Next check in {i}s...")
                        time.sleep(1)
                else:
                    self.call_from_thread(self.query_one("#runbot-status", Label).update, "🎉 [bold green]COMPLETED![/bold green] All builds are finished!")
                    self.call_from_thread(self.query_one("#runbot-timer", Label).update, "")
                    
                    # Play alarm sound
                    ALARM_SOUND = "/usr/share/sounds/sound-icons/trumpet-12.wav"
                    if os.path.exists(ALARM_SOUND):
                        import subprocess
                        for _ in range(5):
                            subprocess.run(["aplay", ALARM_SOUND], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        import sys
                        for _ in range(10):
                            sys.stdout.write("\a")
                            sys.stdout.flush()
                            time.sleep(0.5)
                            
                    break
            except Exception as e:
                self.call_from_thread(self.query_one("#runbot-status", Label).update, f"⚠️ Error updating status: {e}. Retrying...")
                time.sleep(10)
