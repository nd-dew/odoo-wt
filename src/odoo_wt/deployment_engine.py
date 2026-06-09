import asyncio
import os
import json
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional
from .system_discovery import get_remote, check_local
from .app_config import config_mgr

@dataclass
class DeployUpdate:
    category: str  # "odoo", "ent", "uv"
    message: Optional[str] = None
    advance: int = 0
    total: Optional[int] = None
    log_line: Optional[str] = None

async def run_cmd_stream_gen(cmd: List[str], cwd: Path, category: str, prefix: str = "", allow_fail: bool = False) -> AsyncGenerator[DeployUpdate, None]:
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
        yield DeployUpdate(category=category, log_line=f"{prefix}{text}")
    
    await process.wait()
    if process.returncode != 0:
        if not allow_fail:
            yield DeployUpdate(category=category, log_line=f"[bold red]❌ Command failed with exit code {process.returncode}[/bold red]")
        raise RuntimeError(f"Command failed with exit code {process.returncode}: {' '.join(cmd)}")

class DeployEngine:
    def __init__(self, config: dict, data: dict):
        self.config = config
        self.data = data
        self.wt_root = Path(config["wt_root"]).expanduser().absolute()
        self.dev_remote = config.get("remote_name", "odoo-dev")
        self.comm_dir = config.get("community_dir", "odoo")
        self.ent_dir = config.get("enterprise_dir", "enterprise")
        self.env_root = Path(config["env_root"]).expanduser().absolute()
        
        clean_desc = data["desc"].strip().replace(" ", "_")
        parts = [p for p in [data["version"], clean_desc, data["suffix"]] if p]
        self.branch_name = "-".join(parts)
        self.target_dir = self.wt_root / self.branch_name
        
        # Resolve base version from branch name if not explicitly provided
        base_v = data.get("version")
        if not base_v or base_v == "none":
            from .system_discovery import decompose_branch
            _, parsed_v, _, _ = decompose_branch(self.branch_name)
            base_v = parsed_v or "master"
        self.base_v = base_v


    async def deploy_repo(self, repo_path: Path, dest_label: str, category: str) -> AsyncGenerator[DeployUpdate, None]:
        yield DeployUpdate(category=category, total=3)
        
        if not repo_path.exists():
            yield DeployUpdate(category=category, log_line=f"[bold red]Error: Base repository not found at {repo_path}[/bold red]", advance=3)
            return

        # Resolve main remote (use setting if specified, otherwise auto-detect)
        if dest_label == self.comm_dir:
            remote = self.config.get("community_remote", "").strip()
        elif dest_label == self.ent_dir:
            remote = self.config.get("enterprise_remote", "").strip()
        else:
            remote = ""
            
        if not remote:
            remote = await asyncio.to_thread(get_remote, repo_path)
            yield DeployUpdate(category=category, log_line=f"Detected base remote: {remote}", advance=1)
        else:
            yield DeployUpdate(category=category, log_line=f"Using configured remote: {remote}", advance=1)

        is_base_branch = (self.branch_name == self.base_v)
        fetch_success = False

        if not is_base_branch:
            yield DeployUpdate(category=category, log_line=f"Fetching '{self.branch_name}' from '{self.dev_remote}'...")
            fetch_success = True
            try:
                async for update in run_cmd_stream_gen(["git", "fetch", self.dev_remote, f"{self.branch_name}:{self.branch_name}", "--force"], repo_path, category, allow_fail=True):
                    yield update
            except RuntimeError:
                fetch_success = False
        else:
            yield DeployUpdate(category=category, log_line=f"Requested base branch '{self.branch_name}'. Skipping dev remote fetch.")
        
        yield DeployUpdate(category=category, advance=1)

        try:
            if fetch_success:
                yield DeployUpdate(category=category, log_line="Fetch successful. Creating worktree...")
                async for update in run_cmd_stream_gen(["git", "worktree", "add", str(self.target_dir / dest_label), self.branch_name], repo_path, category):
                    yield update
            else:
                if not is_base_branch:
                    yield DeployUpdate(category=category, log_line=f"Branch not found on '{self.dev_remote}'. Fetching '{self.base_v}' from '{remote}'...")
                else:
                    yield DeployUpdate(category=category, log_line=f"Fetching '{self.base_v}' from '{remote}'...")
                    
                async for update in run_cmd_stream_gen(["git", "fetch", remote, self.base_v], repo_path, category):
                    yield update
                
                is_local = await asyncio.to_thread(check_local, repo_path, self.branch_name)
                if is_local:
                    yield DeployUpdate(category=category, log_line="Branch exists locally. Creating worktree...")
                    async for update in run_cmd_stream_gen(["git", "worktree", "add", str(self.target_dir / dest_label), self.branch_name], repo_path, category):
                        yield update
                    # No error if checkout worked
                else:
                    yield DeployUpdate(category=category, log_line=f"Creating new branch from {remote}/{self.base_v}...")
                    async for update in run_cmd_stream_gen(["git", "worktree", "add", "-b", self.branch_name, str(self.target_dir / dest_label), f"{remote}/{self.base_v}"], repo_path, category):
                        yield update
                    async for update in run_cmd_stream_gen(["git", "branch", "--set-upstream-to", f"{remote}/{self.base_v}", self.branch_name], repo_path, category):
                        yield update
            
            yield DeployUpdate(category=category, advance=1, log_line="✅ Done.")
        except RuntimeError as e:
            yield DeployUpdate(category=category, log_line=f"[bold red]CRITICAL FAILURE: Repo deployment aborted.[/bold red]")

    async def setup_uv(self) -> AsyncGenerator[DeployUpdate, None]:
        category = "uv"
        yield DeployUpdate(category=category, total=4)
        
        self.env_root.mkdir(parents=True, exist_ok=True)
        py_v = self.config.get("python_version", "3.12")
        target_env = self.env_root / self.base_v
        
        try:
            if not target_env.exists():
                yield DeployUpdate(category=category, log_line=f"Initializing UV environment ({py_v}) for {self.base_v}...", advance=1)
                async for update in run_cmd_stream_gen(["uv", "venv", str(target_env), "--python", py_v], self.env_root, category):
                    yield update
                
                base_req = self.wt_root / "master" / self.comm_dir / "requirements.txt"
                if base_req.exists():
                    yield DeployUpdate(category=category, log_line=f"Installing requirements from base '{self.comm_dir}'...", advance=1)
                    async for update in run_cmd_stream_gen([
                        "uv", "pip", "install", "-r", str(base_req), 
                        "--python", str(target_env / "bin" / "python")
                    ], self.env_root, category):
                        yield update
                else:
                    yield DeployUpdate(category=category, advance=1)
            else:
                yield DeployUpdate(category=category, log_line=f"UV environment '{self.base_v}' already exists.", advance=2)

            venv_symlink = self.target_dir / ".venv"
            if not venv_symlink.exists():
                try:
                    os.symlink(target_env, venv_symlink)
                    yield DeployUpdate(category=category, log_line="Created .venv symlink.")
                except OSError as e:
                    yield DeployUpdate(category=category, log_line=f"[bold red]Failed to create symlink: {e}[/bold red]")
                    return # Exit early on link failure
            
            yield DeployUpdate(category=category, advance=1, log_line="✅ Done.")
        except RuntimeError:
            yield DeployUpdate(category=category, log_line=f"[bold red]CRITICAL FAILURE: UV setup aborted.[/bold red]")

    async def setup_vscode(self) -> None:
        if not self.config.get("create_vscode_launch", True):
            return

        from .system_discovery import decompose_branch
        _, _, desc, _ = decompose_branch(self.branch_name)
        if desc:
            db_name = desc.replace("-", "_").strip("_")
        else:
            db_name = self.branch_name.replace("-", "_").strip("_")

        # Determine if enterprise folder exists to build addons-path
        has_ent = (self.target_dir / self.ent_dir).exists()
        if has_ent:
            addons_path = f"{self.comm_dir}/addons,enterprise"
        else:
            addons_path = f"{self.comm_dir}/addons"

        # Detect modified modules via git diff against origin/{base_v}
        def get_modified_modules(repo_path, base_v):
            if not repo_path.exists():
                return set()
            cmds = [
                ["git", "diff", "--name-only", f"origin/{base_v}..."],
                ["git", "diff", "--name-only", f"origin/{base_v}...HEAD"],
                ["git", "diff", "--name-only", "HEAD~1"]
            ]
            output = ""
            for cmd in cmds:
                try:
                    res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=True)
                    if res.stdout.strip():
                        output = res.stdout
                        break
                except Exception:
                    continue
            
            modules = set()
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = Path(line).parts
                if "addons" in parts:
                    idx = parts.index("addons")
                    if idx + 1 < len(parts):
                        modules.add(parts[idx + 1])
                elif len(parts) > 0:
                    modules.add(parts[0])
            return modules

        comm_repo = self.target_dir / self.comm_dir
        ent_repo = self.target_dir / self.ent_dir
        
        modules = set()
        if comm_repo.exists():
            modules.update(get_modified_modules(comm_repo, self.base_v))
        if ent_repo.exists():
            modules.update(get_modified_modules(ent_repo, self.base_v))

        # Filter to keep only actual, valid Odoo modules (must contain a __manifest__.py)
        valid_modules = []
        for m in sorted(modules):
            comm_addon_path = comm_repo / "addons" / m
            comm_base_addon_path = comm_repo / "odoo" / "addons" / m
            ent_addon_path = ent_repo / m
            
            if (comm_addon_path / "__manifest__.py").exists() or \
               (comm_base_addon_path / "__manifest__.py").exists() or \
               (ent_addon_path / "__manifest__.py").exists():
                valid_modules.append(m)

        # Retrieve and increment global next_debug_port
        port = self.config.get("next_debug_port", 8069)
        self.config["next_debug_port"] = port + 1
        config_mgr.save(self.config)

        # Prepare and write the VS Code launch.json file
        vscode_dir = self.target_dir / ".vscode"
        vscode_dir.mkdir(parents=True, exist_ok=True)

        args = [
            "--addons-path", addons_path,
            "-d", db_name
        ]
        if valid_modules:
            args.extend(["-i", ",".join(valid_modules)])
        
        args.extend([
            "--with-demo",
            "--http-port", str(port),
            "--dev=all"
        ])

        config_data = {
            "version": "0.2.0",
            "configurations": [
                {
                    "name": f"Odoo {self.base_v.capitalize()}: Run Server (Port {port})",
                    "type": "debugpy",
                    "request": "launch",
                    "program": f"${{workspaceFolder}}/{self.comm_dir}/odoo-bin",
                    "python": "${workspaceFolder}/.venv/bin/python",
                    "args": args,
                    "console": "integratedTerminal",
                    "cwd": "${workspaceFolder}",
                    "justMyCode": False
                }
            ]
        }

        with open(vscode_dir / "launch.json", "w") as f:
            json.dump(config_data, f, indent=4)

