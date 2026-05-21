import pytest
from odoo_wt.main_tui import OdooWtApp
from odoo_wt.setup_wizard import WizardApp
from odoo_wt.app_config import config_mgr
from odoo_wt.system_discovery import parse_branch_name, shorten_path, expand_path
from textual.widgets import TabbedContent, Select
from pathlib import Path
import json

@pytest.fixture
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

def test_worktree_discovery(tmp_path):
    from odoo_wt.system_discovery import discover_system_data
    
    # Create mock worktree structure
    wt_root = tmp_path / "wt"
    wt_root.mkdir()
    
    # master worktree
    master_wt = wt_root / "master"
    master_wt.mkdir()
    (master_wt / "odoo" / ".git").mkdir(parents=True)
    
    # normal worktree
    feature_wt = wt_root / "17.0-fix-pian"
    feature_wt.mkdir()
    (feature_wt / "odoo" / ".git").mkdir(parents=True)
    
    v_list, s_list, worktrees = discover_system_data(str(wt_root), "pian")
    
    # Verify master is included in worktrees
    wt_names = [w["name"] for w in worktrees]
    assert "master" in wt_names
    assert "17.0-fix-pian" in wt_names
    assert "master" in v_list

def test_config_management(mock_config_path):
    # Ensure we start clean
    if mock_config_path.exists(): mock_config_path.unlink()
    
    config = config_mgr._get_defaults()
    config["suffix"] = "test"
    config["config_path"] = str(mock_config_path)
    config_mgr.save(config)
    
    loaded = config_mgr.load()
    assert loaded["suffix"] == "test"
    assert mock_config_path.exists()

def test_logging_system(mock_config_path):
    config_mgr.append_log("Test Action", {"key": "value"})
    assert config_mgr.log_file.exists()
    with open(config_mgr.log_file, "r") as f:
        line = f.readline()
        data = json.loads(line)
        assert data["action"] == "Test Action"

@pytest.mark.asyncio
async def test_app_mount():
    app = OdooWtApp({"wt_root": "/tmp", "python_version": "3.12"}, ["master"], ["pian"], [])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one(".title")
        print("\n🚀 MAIN APP MOUNT SUCCESSFUL!")

@pytest.mark.asyncio
async def test_app_mount_with_worktrees():
    # Regression test for AttributeError: 'OdooWtApp' object has no attribute 'deleting_paths'
    mock_worktrees = [
        {"name": "saas-19.1-test", "path": "/tmp/wt/saas-19.1-test", "version": "saas-19.1", "suffix": "test"}
    ]
    app = OdooWtApp({"wt_root": "/tmp", "python_version": "3.12"}, ["master"], ["pian"], mock_worktrees)
    
    # Assert that the attribute exists right after initialization
    assert hasattr(app, "deleting_paths")
    assert isinstance(app.deleting_paths, set)
    
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one(".title")
        # Ensure the table is populated correctly
        table = pilot.app.query_one("#wt-table")
        assert table.row_count == 1

@pytest.mark.asyncio
async def test_protected_master_deletion():
    mock_worktrees = [
        {"name": "master", "path": "/tmp/wt/master", "version": "master", "suffix": ""}
    ]
    app = OdooWtApp({"wt_root": "/tmp", "python_version": "3.12"}, ["master"], ["pian"], mock_worktrees)
    async with app.run_test() as pilot:
        await pilot.pause()
        pilot.app.query_one("#tabs").active = "tab-manage"
        await pilot.pause()
        
        # Select the master row (first row)
        table = pilot.app.query_one("#wt-table")
        table.cursor_coordinate = (0, 0)
        
        # Trigger delete action
        await pilot.press("ctrl+d")
        await pilot.pause()
        
        # Ensure no DeleteConfirmScreen was pushed (meaning it was blocked)
        # Note: In Textual tests, we can check the screen stack
        assert not any(isinstance(s, DeleteConfirmScreen) for s in pilot.app.screen_stack)
        
        # Optionally check the notification text if possible, but screen stack check is robust
        # Check for error notification
        # This part is a bit tricky to assert directly in textual, but the logic is verified.

@pytest.mark.asyncio
async def test_spell_check():
    from odoo_wt.main_tui import spell
    assert "odoo" in spell
    assert "pos" in spell

from odoo_wt.custom_screens import DeleteConfirmScreen

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
    # Instead, it should immediately fetch the base version from the official remote
    assert ["git", "fetch", "odoo", "19.0"] in commands_run

@pytest.mark.asyncio
async def test_wizard_mount():
    app = WizardApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one(".title")
        print("\n🚀 WIZARD MOUNT SUCCESSFUL!")

@pytest.mark.asyncio
async def test_settings_tab_rendering():
    from odoo_wt.app_config import ConfigManager
    config_mgr = ConfigManager()
    app = OdooWtApp(config_mgr.load(), ["master"], ["pian"], [])
    async with app.run_test() as pilot:
        # Switch to settings tab
        pilot.app.query_one("#tabs").active = "tab-settings"
        await pilot.pause()
        # Check if Python Version input exists
        assert pilot.app.query_one("#set-py-v")
        # Check if Config path is displayed
        assert pilot.app.query_one(".tab-description")

@pytest.mark.asyncio
async def test_wizard_scrollbar(monkeypatch):
    import odoo_wt.setup_wizard
    monkeypatch.setattr(odoo_wt.setup_wizard, "fast_scan", lambda: ["/mock"])

    app = WizardApp()
    # Force a small terminal size
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.5)

        # Reveal the hidden steps
        app.query_one("#final-steps").remove_class("hidden")
        await pilot.pause(0.5)
        
        scroll_container = app.query_one("#wizard-scroll")
        assert scroll_container.virtual_size.height > scroll_container.size.height

def test_git_branch_strategy_detection(tmp_path):
    from odoo_wt.system_discovery import run_git, check_local
    import subprocess

    repo = tmp_path / "mock_repo"
    repo.mkdir()

    # 1. Init a blank git repo
    run_git(["init"], cwd=repo)
    run_git(["config", "user.email", "test@example.com"], cwd=repo)
    run_git(["config", "user.name", "Test User"], cwd=repo)
    
    # 2. Branch should definitely NOT exist
    assert check_local(repo, "saas-17.1-fix-test-pian") is False

    # 3. Create a dummy commit and the branch
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=repo)
    run_git(["branch", "saas-17.1-fix-test-pian"], cwd=repo)

    # 4. Strategy detection should now properly identify it exists locally
    assert check_local(repo, "saas-17.1-fix-test-pian") is True
