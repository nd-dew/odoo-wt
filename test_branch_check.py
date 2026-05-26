import pytest
import asyncio
from pathlib import Path
from rich.text import Text
from odoo_wt.main_tui import OdooWtApp
from odoo_wt.app_config import config_mgr

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
    
    # SAFETY SHIELD
    monkeypatch.setattr(config_mgr, "is_test_mode", True)
    
    config_mgr.config = config_mgr._get_defaults()
    config_mgr.config["config_path"] = str(config_file)
    config_mgr.config["log_path"] = str(log_file)
    return config_file

@pytest.mark.asyncio
async def test_branch_check_ui_transitions(tmp_path, monkeypatch):
    # 1. Setup Mock Environment
    wt_root = tmp_path / "wt"
    wt_root.mkdir()
    # master worktree (required for the app to find base repos)
    master_dir = wt_root / "master"
    master_dir.mkdir()
    (master_dir / "odoo" / ".git").mkdir(parents=True)
    (master_dir / "enterprise" / ".git").mkdir(parents=True)

    config = {
        "wt_root": str(wt_root),
        "python_version": "3.12",
        "remote_name": "odoo-dev",
        "suffix": "pian"
    }

    # 2. Mocks for Git Logic
    def mock_check_remote(repo, branch, remote):
        import time
        # Simulate different speeds for different remotes
        if remote == "odoo-dev":
            time.sleep(0.4) # Fast success
            return True
        else:
            time.sleep(0.6) # Slow fail
            return False

    monkeypatch.setattr("odoo_wt.system_discovery.get_remote", lambda _: "odoo")
    monkeypatch.setattr("odoo_wt.system_discovery.check_local", lambda _, __: False)
    monkeypatch.setattr("odoo_wt.system_discovery.check_remote", mock_check_remote)

    # 3. Launch App in Test Mode
    app = OdooWtApp(config, ["master"], ["pian"], [])
    async with app.run_test(size=(100, 40)) as pilot:
        # Type a branch name to trigger checking
        await pilot.click("#desc")
        await pilot.press(*"fix-bug")
        
        # Debounce is 0.5s, wait a bit
        await pilot.pause(0.6)
        
        # PHASE A: Initial Checking State
        summary = pilot.app.query_one("#dynamic-summary")
        text = summary.render().plain
        assert "Checking" in text
        
        # PHASE B: Animation State
        await pilot.pause(0.2)
        text = summary.render().plain
        assert "Checking remotes" in text
        
        # PHASE C: Final Found State
        # Wait for our mock delays to finish (0.4s for odoo-dev)
        await pilot.pause(0.8)
        text = summary.render().plain
        assert "Found branch on 'odoo-dev'" in text
        assert "✓ Dev (odoo-dev) Community" in text
