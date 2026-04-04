import pytest
from odoo_wt.main_tui import OdooWtApp
from odoo_wt.setup_wizard import WizardApp
from odoo_wt.app_config import load_config, save_config, append_log
from odoo_wt.system_discovery import parse_branch_name, shorten_path, expand_path
from pathlib import Path
import json
import os

@pytest.fixture
def mock_config_path(tmp_path, monkeypatch):
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    config_file = config_dir / "odoo-wt.json"
    log_file = config_dir / "odoo-wt-logs.jsonl"
    import odoo_wt.app_config
    monkeypatch.setattr(odoo_wt.app_config, "CONFIG_FILE", config_file)
    monkeypatch.setattr(odoo_wt.app_config, "LOG_FILE", log_file)
    return config_file

def test_pure_logic_parsing():
    v, s = parse_branch_name("saas-17.1-fix-login-pian")
    assert v == "saas-17.1"
    assert s == "pian"
    
    v, s = parse_branch_name("16.0-test")
    assert v == "16.0"
    assert s == "test"

def test_path_utilities():
    home = str(Path.home())
    assert shorten_path(home + "/repos") == "~/repos"
    assert expand_path("~/repos") == home + "/repos"

def test_config_management(mock_config_path):
    config = {"wt_root": "/tmp/test", "env_root": "/tmp/envs", "suffix": "test", "remote_name": "origin"}
    save_config(config)
    loaded = load_config()
    assert loaded["suffix"] == "test"
    assert mock_config_path.exists()

def test_logging_system(mock_config_path):
    append_log("Test Action", {"key": "value"})
    log_file = mock_config_path.parent / "odoo-wt-logs.jsonl"
    assert log_file.exists()
    with open(log_file, "r") as f:
        line = f.read().strip()
        data = json.loads(line)
    assert data["action"] == "Test Action"

@pytest.mark.asyncio
async def test_app_mount():
    app = OdooWtApp({"wt_root": "/tmp"}, ["master"], ["pian"], [])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one(".title")
        print("\n🚀 MAIN APP MOUNT SUCCESSFUL!")

@pytest.mark.asyncio
async def test_wizard_mount():
    app = WizardApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one(".title")
        print("\n🚀 WIZARD MOUNT SUCCESSFUL!")

def test_git_branch_strategy_detection(tmp_path):
    from odoo_wt.system_discovery import run_git, check_local
    import subprocess
    
    repo = tmp_path / "mock_repo"
    repo.mkdir()
    
    # 1. Init a blank git repo
    run_git(["init"], cwd=repo)
    
    # 2. Branch should definitely NOT exist
    assert check_local(repo, "saas-17.1-fix-test-pian") is False
    
    # 3. Create a dummy commit and the branch
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=repo)
    run_git(["branch", "saas-17.1-fix-test-pian"], cwd=repo)
    
    # 4. Strategy detection should now properly identify it exists locally
    assert check_local(repo, "saas-17.1-fix-test-pian") is True
