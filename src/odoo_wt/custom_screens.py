import asyncio
import os
import json
from pathlib import Path
from textual import on, work
from textual.screen import ModalScreen, Screen
from textual.widgets import Label, Button, ProgressBar, RichLog
from textual.containers import Vertical, Horizontal, VerticalScroll

from .app_config import append_log
from .system_discovery import get_remote, check_local

async def run_cmd_stream(cmd, cwd, log_widget, prefix=""):
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        text = line.decode('utf-8', errors='replace').rstrip()
        log_widget.write(f"{prefix}{text}")
    await process.wait()
    return process.returncode == 0

class DeleteConfirmScreen(ModalScreen[bool]):
    def __init__(self, wt_name: str):
        super().__init__()
        self.wt_name = wt_name
        self.step = 1

    def compose(self):
        with Vertical(id="delete-dialog"):
            yield Label(f"Delete worktree '{self.wt_name}'? (1/3)", id="del-msg")
            with Horizontal(classes="del-btn-row", id="btn-container"):
                yield Button("Yes, delete", variant="error", id="btn-yes")
                yield Button("Cancel", variant="primary", id="btn-cancel")

    @on(Button.Pressed, "#btn-yes")
    async def on_yes(self):
        append_log("Delete Confirm Step", {"step": self.step, "worktree": self.wt_name})
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
        append_log("Delete Cancelled", {"worktree": self.wt_name})
        self.dismiss(False)



from textual.binding import Binding
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
        wt_root = Path(self.config["wt_root"])
        dev_remote = self.config.get("remote_name", "odoo-dev")
        comm_dir = self.config.get("community_dir", "odoo")
        ent_dir = self.config.get("enterprise_dir", "enterprise")
        
        clean_desc = self.data["desc"].strip().replace(" ", "_")
        parts = [p for p in [self.data["version"], clean_desc, self.data["suffix"]] if p]
        branch_name = "-".join(parts)
        append_log("Deployment Started", {"branch": branch_name, "version": self.data["version"]})
        target_dir = wt_root / branch_name
        base_odoo = wt_root / "master" / comm_dir
        base_ent = wt_root / "master" / ent_dir
        base_v = self.data["version"] or "master"
        
        target_dir.mkdir(parents=True, exist_ok=True)
        
        async def deploy_repo(repo, dest, log_id, prog_id):
            log = self.query_one(f"#{log_id}", RichLog)
            prog = self.query_one(f"#{prog_id}", ProgressBar)
            prog.update(total=3)
            
            remote = await asyncio.to_thread(get_remote, repo)
            log.write(f"Detected base remote: {remote}")
            prog.advance(1)

            log.write(f"Fetching '{branch_name}' from '{dev_remote}'...")
            success = await run_cmd_stream(["git", "fetch", dev_remote, f"{branch_name}:{branch_name}", "--force"], repo, log)
            prog.advance(1)

            if success:
                log.write("Fetch successful. Creating worktree...")
                append_log("Branch Strategy Selected", {"repo": dest, "strategy": "remote_pull", "remote": dev_remote, "branch": branch_name})
                await run_cmd_stream(["git", "worktree", "add", str(target_dir / dest), branch_name], repo, log)
            else:
                log.write(f"Branch not found on '{dev_remote}'. Fetching '{base_v}' from '{remote}'...")
                await run_cmd_stream(["git", "fetch", remote, base_v], repo, log)
                
                is_local = await asyncio.to_thread(check_local, repo, branch_name)
                if is_local:
                    log.write("Branch exists locally. Creating worktree...")
                    append_log("Branch Strategy Selected", {"repo": dest, "strategy": "local_checkout", "branch": branch_name})
                    await run_cmd_stream(["git", "worktree", "add", str(target_dir / dest), branch_name], repo, log)
                else:
                    log.write(f"Creating new branch from {remote}/{base_v}...")
                    append_log("Branch Strategy Selected", {"repo": dest, "strategy": "new_branch", "base": f"{remote}/{base_v}", "branch": branch_name})
                    await run_cmd_stream(["git", "worktree", "add", "-b", branch_name, str(target_dir / dest), f"{remote}/{base_v}"], repo, log)
                    await run_cmd_stream(["git", "branch", "--set-upstream-to", f"{remote}/{base_v}", branch_name], repo, log)
            
            prog.advance(1)
            log.write("✅ Done.")

        async def setup_uv():
            log_uv = self.query_one("#log-uv", RichLog)
            prog_uv = self.query_one("#prog-uv", ProgressBar)
            prog_uv.update(total=4)
            
            env_root = Path(self.config["env_root"])
            env_root.mkdir(parents=True, exist_ok=True)
            target_env = env_root / base_v
            
            if not target_env.exists():
                log_uv.write(f"Initializing UV environment for {base_v}...")
                await run_cmd_stream(["uv", "venv", str(target_env), "--python", "3.12"], env_root, log_uv)
                prog_uv.advance(1)
                
                # Use base folder requirements to avoid waiting for worktree creation
                base_req = wt_root / "master" / comm_dir / "requirements.txt"
                if base_req.exists():
                    log_uv.write(f"Installing requirements from base '{comm_dir}'...")
                    await run_cmd_stream([
                        "uv", "pip", "install", "-r", str(base_req), 
                        "--python", str(target_env / "bin" / "python")
                    ], env_root, log_uv)
                prog_uv.advance(1)
            else:
                log_uv.write(f"UV environment '{base_v}' already exists.")
                prog_uv.advance(2)

            # Wait for target_dir to definitely exist (though we create it at start)
            # but more importantly, we need to wait for odoo/enterprise worktrees 
            # to finish before we can reliably symlink .venv into the target_dir
            # actually target_dir is just a folder, we can symlink now!
            venv_symlink = target_dir / ".venv"
            if not venv_symlink.exists():
                try:
                    os.symlink(target_env, venv_symlink)
                    log_uv.write("Created .venv symlink.")
                except Exception as e:
                    log_uv.write(f"Failed to create symlink: {e}")
            prog_uv.advance(1)
            log_uv.write("✅ Done.")
            return True

        await asyncio.gather(
            deploy_repo(base_odoo, comm_dir, "log-odoo", "prog-odoo"),
            deploy_repo(base_ent, ent_dir, "log-ent", "prog-ent"),
            setup_uv()
        )

        append_log("Deployment Success", {"branch": branch_name, "path": str(target_dir)})
        self.target_dir = target_dir
        self.show_success_footer()

    def show_success_footer(self):
        msg = self.query_one("#success-message", Label)
        msg.update(f"SUCCESS! Worktree ready at: {self.target_dir}\nWhat would you like to do next?")
        self.query_one("#success-footer").remove_class("hidden")
        self.query_one("#btn-terminal").focus()

    @on(Button.Pressed, "#btn-terminal")
    def on_terminal(self):
        append_log("Deployment Complete", {"choice": "terminal"})
        self.app.exit({"action": "terminal", "path": str(self.target_dir)})

    @on(Button.Pressed, "#btn-vscode")
    def on_vscode(self):
        append_log("Deployment Complete", {"choice": "vscode"})
        self.app.exit({"action": "vscode", "path": str(self.target_dir)})

    @on(Button.Pressed, "#btn-back")
    def on_back(self):
        append_log("Deployment Complete", {"choice": "back"})
        self.dismiss()

    @on(Button.Pressed, "#btn-exit")
    def on_exit(self):
        append_log("Deployment Complete", {"choice": "exit"})
        self.app.exit()

class LogDetailScreen(ModalScreen[None]):
    def __init__(self, ts, action, details):
        super().__init__()
        self.ts = ts
        self.action = action
        self.details = details

    def compose(self):
        with Vertical(id="log-detail-dialog"):
            yield Label(f"[{self.ts}] {self.action}", classes="log-detail-title")
            try:
                parsed = json.loads(self.details)
                pretty_details = json.dumps(parsed, indent=4)
            except:
                pretty_details = str(self.details)
            with VerticalScroll():
                yield Label(pretty_details, classes="log-detail-text")
            with Horizontal(classes="log-detail-btn-row"):
                yield Button("Close", variant="primary", id="btn-close-log")

    @on(Button.Pressed, "#btn-close-log")
    def on_close(self):
        self.dismiss()
