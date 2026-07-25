import pytest
import json
import os
import sys
import re
import urllib.request
from pathlib import Path
from odoo_wt.main_tui import OdooWtApp
from odoo_wt.setup_wizard import WizardApp
from odoo_wt.app_config import config_mgr
from odoo_wt.system_discovery import parse_branch_name, shorten_path, expand_path
from textual.widgets import TabbedContent, Select

@pytest.fixture(autouse=True)
def mock_config_path(tmp_path, monkeypatch):
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    config_file = config_dir / "odoo-wt.json"
    log_file = config_dir / "odoo-wt-logs.jsonl"
    
    import odoo_wt.app_config as ac
    monkeypatch.setattr(ac, "DEFAULT_CONFIG_FILE", config_file)
    monkeypatch.setattr(ac, "DEFAULT_LOG_FILE", log_file)
    monkeypatch.setattr(config_mgr, "config_file", config_file)
    monkeypatch.setattr(config_mgr, "log_file", log_file)
    
    # SAFETY SHIELD: Disable all disk writes during tests
    monkeypatch.setattr(config_mgr, "is_test_mode", True)
    
    # Pre-populate with valid defaults to avoid validation errors
    config_mgr.config = config_mgr._get_defaults()
    config_mgr.config["config_path"] = str(config_file)
    config_mgr.config["log_path"] = str(log_file)

    return config_file

@pytest.mark.asyncio
async def test_deployment_engine_base_branch(monkeypatch):
    from odoo_wt.deployment_engine import DeployEngine

    # Mock run_cmd_stream_gen to capture the executed commands
    commands_run = []
    async def mock_run_cmd_stream_gen(cmd, *args, **kwargs):
        commands_run.append(cmd)
        yield None

    monkeypatch.setattr("odoo_wt.deployment_engine.run_cmd_stream_gen", mock_run_cmd_stream_gen)

    config = {
        "wt_root": "/tmp",
        "env_root": "/tmp/envs",
        "remote_name": "odoo-dev",
        "community_dir": "odoo",
        "enterprise_dir": "enterprise"
    }

    # Test 1: Feature branch (should fetch from dev remote)
    engine = DeployEngine(config, {"version": "19.0", "desc": "fix-bug", "suffix": "test"})
    # Need to mock get_remote to prevent subprocess call
    monkeypatch.setattr("odoo_wt.deployment_engine.get_remote", lambda _: "odoo")
    monkeypatch.setattr("odoo_wt.deployment_engine.check_local", lambda _, __: False)

    commands_run.clear()
    async for _ in engine.deploy_repo(Path("/tmp"), "odoo", "odoo"):
        pass

    # The first command should be the fetch from the dev remote
    assert ["git", "fetch", "odoo-dev", "19.0-fix-bug-test:19.0-fix-bug-test", "--force"] in commands_run

    # Test 2: Base branch (should SKIP fetch from dev remote)
    engine_base = DeployEngine(config, {"version": "19.0", "desc": "", "suffix": ""})
    commands_run.clear()
    async for _ in engine_base.deploy_repo(Path("/tmp"), "odoo", "odoo"):
        pass

    # The dev remote fetch should NOT be in the commands
    assert ["git", "fetch", "odoo-dev", "19.0:19.0", "--force"] not in commands_run
    # Instead, it should immediately fetch the base version from the official remote with the correct refspec mapping
    assert ["git", "fetch", "odoo", "19.0:refs/remotes/odoo/19.0", "--force"] in commands_run

    # Test 3: Dynamic Fallback base version extraction
    # If version dropdown is "none" or empty, but description is "saas-19.3"
    engine_fallback = DeployEngine(config, {"version": "", "desc": "saas-19.3", "suffix": ""})
    assert engine_fallback.base_v == "saas-19.3"
    assert engine_fallback.branch_name == "saas-19.3"
    commands_run.clear()
    async for _ in engine_fallback.deploy_repo(Path("/tmp"), "odoo", "odoo"):
        pass
    # It should dynamically fetch saas-19.3 with the correct refspec mapping
    assert ["git", "fetch", "odoo", "saas-19.3:refs/remotes/odoo/saas-19.3", "--force"] in commands_run

@pytest.mark.asyncio
async def test_vscode_launch_generation(tmp_path, monkeypatch):
    from odoo_wt.deployment_engine import DeployEngine
    
    # 1. Setup mock directories
    wt_root = tmp_path / "wt"
    wt_root.mkdir()
    
    target_dir = wt_root / "master-owl3-migration-remove-usestate-elco"
    target_dir.mkdir()
    
    comm_dir = target_dir / "odoo"
    comm_dir.mkdir()
    
    # Create crm addon structure and manifest so it passes validation
    crm_addon = comm_dir / "addons" / "crm"
    crm_addon.mkdir(parents=True)
    with open(crm_addon / "__manifest__.py", "w") as f:
        f.write("{'name': 'CRM'}")
        
    config = {
        "wt_root": str(wt_root),
        "env_root": "/tmp/envs",
        "remote_name": "odoo-dev",
        "community_dir": "odoo",
        "enterprise_dir": "enterprise",
        "create_vscode_launch": True,
        "next_debug_port": 8069
    }
    
    engine = DeployEngine(config, {"version": "master", "desc": "owl3-migration-remove-usestate", "suffix": "elco"})
    engine.target_dir = target_dir
    
    # Mock subprocess.run to simulate crm addon modification
    import subprocess
    class MockCompletedProcess:
        def __init__(self, stdout):
            self.stdout = stdout
            self.returncode = 0
            
    def mock_run(cmd, *args, **kwargs):
        # We simulate git diff returning crm addon view change
        if "diff" in cmd:
            return MockCompletedProcess("addons/crm/views/crm_lead_views.xml\n")
        return MockCompletedProcess("")
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    
    # 2. Run setup_vscode
    await engine.setup_vscode()
    
    # 3. Assert launch.json content
    launch_json_path = target_dir / ".vscode" / "launch.json"
    assert launch_json_path.exists()
    
    with open(launch_json_path, "r") as f:
        data = json.load(f)
        config_entry = data["configurations"][0]
        assert config_entry["name"] == "Odoo Master: Run Server (Port 8069)"
        assert "--addons-path" in config_entry["args"]
        assert "odoo/addons" in config_entry["args"]
        assert "-d" in config_entry["args"]
        assert "owl3_migration_remove_usestate" in config_entry["args"]
        assert "-i" in config_entry["args"]
        assert "crm" in config_entry["args"]
        assert "--http-port" in config_entry["args"]
        assert "8069" in config_entry["args"]
        assert "--with-demo" in config_entry["args"]
        assert "--dev=all" in config_entry["args"]
        assert config_entry["cwd"] == "${workspaceFolder}"
        
    # Assert global port was incremented
    assert engine.config["next_debug_port"] == 8070

@pytest.mark.asyncio
async def test_deployment_engine_upstream_tracking(monkeypatch):
    from odoo_wt.deployment_engine import DeployEngine

    commands_run = []
    async def mock_run_cmd_stream_gen(cmd, *args, **kwargs):
        commands_run.append(cmd)
        # Symmetrically raise RuntimeError to simulate fetch failure for brand new feature branch
        if "fetch" in cmd and "odoo-dev" in cmd:
            raise RuntimeError("Fetch failed")
        yield None

    monkeypatch.setattr("odoo_wt.deployment_engine.run_cmd_stream_gen", mock_run_cmd_stream_gen)
    monkeypatch.setattr("odoo_wt.deployment_engine.get_remote", lambda _: "odoo")
    monkeypatch.setattr("odoo_wt.deployment_engine.check_local", lambda _, __: False)

    config = {
        "wt_root": "/tmp",
        "env_root": "/tmp/envs",
        "remote_name": "odoo-dev",
        "community_dir": "odoo",
        "enterprise_dir": "enterprise"
    }

    # Case A: Feature branch (should run --unset-upstream)
    engine_feature = DeployEngine(config, {"version": "19.0", "desc": "fix-bug", "suffix": "test"})
    commands_run.clear()
    async for _ in engine_feature.deploy_repo(Path("/tmp"), "odoo", "odoo"):
        pass

    assert ["git", "branch", "--unset-upstream", "19.0-fix-bug-test"] in commands_run

    # Case B: Base release branch (should NOT run --unset-upstream!)
    engine_base = DeployEngine(config, {"version": "19.0", "desc": "", "suffix": ""})
    commands_run.clear()
    async for _ in engine_base.deploy_repo(Path("/tmp"), "odoo", "odoo"):
        pass

    assert ["git", "branch", "--unset-upstream", "19.0"] not in commands_run
    assert ["git", "branch", "--set-upstream-to=odoo/19.0", "19.0"] in commands_run

@pytest.mark.asyncio
async def test_deployment_engine_dev_remote_upstream_tracking(monkeypatch):
    from odoo_wt.deployment_engine import DeployEngine

    commands_run = []
    async def mock_run_cmd_stream_gen(cmd, *args, **kwargs):
        commands_run.append(cmd)
        # Symmetrically yield None without raising to simulate successful fetch from dev_remote
        yield None

    monkeypatch.setattr("odoo_wt.deployment_engine.run_cmd_stream_gen", mock_run_cmd_stream_gen)
    monkeypatch.setattr("odoo_wt.deployment_engine.get_remote", lambda _: "odoo")

    config = {
        "wt_root": "/tmp",
        "env_root": "/tmp/envs",
        "remote_name": "odoo-dev",
        "community_dir": "odoo",
        "enterprise_dir": "enterprise"
    }

    engine = DeployEngine(config, {"version": "19.0", "desc": "fix-bug", "suffix": "test"})
    commands_run.clear()
    async for _ in engine.deploy_repo(Path("/tmp"), "odoo", "odoo"):
        pass

    # Ensure that it did NOT call --unset-upstream because fetch was successful
    assert ["git", "branch", "--unset-upstream", "19.0-fix-bug-test"] not in commands_run
    # Ensure that it correctly called --set-upstream-to targeting the dev_remote and branch
    assert ["git", "branch", "--set-upstream-to=odoo-dev/19.0-fix-bug-test", "19.0-fix-bug-test"] in commands_run
