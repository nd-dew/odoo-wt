import pytest
from odoo_wt.main_tui import OdooWtApp
from odoo_wt.setup_wizard import WizardApp
from odoo_wt.app_config import load_config, save_config, append_log
from odoo_wt.system_discovery import parse_branch_name, shorten_path, expand_path
from textual.widgets import TabbedContent
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
    monkeypatch.setattr(ac, "CONFIG_FILE", config_file)
    monkeypatch.setattr(ac, "LOG_FILE", log_file)
    
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
    # Ensure we start clean
    if mock_config_path.exists(): mock_config_path.unlink()
    
    config = {"wt_root": "/tmp/test", "env_root": "/tmp/envs", "suffix": "test", "remote_name": "origin", "config_path": str(mock_config_path)}
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
async def test_app_mount_with_worktrees():
    # Regression test for AttributeError: 'OdooWtApp' object has no attribute 'deleting_paths'
    mock_worktrees = [
        {"name": "saas-19.1-test", "path": "/tmp/wt/saas-19.1-test", "version": "saas-19.1", "suffix": "test"}
    ]
    app = OdooWtApp({"wt_root": "/tmp"}, ["master"], ["pian"], mock_worktrees)

    # Assert that the attribute exists right after initialization
    assert hasattr(app, "deleting_paths")
    assert isinstance(app.deleting_paths, set)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one(".title")

@pytest.mark.asyncio
async def test_settings_keyboard_navigation(mock_config_path):
    # Regression test for AttributeError on focus_next in OdooWtApp
    app = OdooWtApp({"wt_root": "/tmp"}, ["master"], ["pian"], [])
    async with app.run_test() as pilot:
        await pilot.pause()
        # Switch to settings tab
        tabs = app.query_one("#tabs", TabbedContent)
        tabs.active = "tab-settings"
        await pilot.pause()

        # Press down arrow
        await pilot.press("down")
        await pilot.pause()

        # Press up arrow
        await pilot.press("up")
        await pilot.pause()

        # If no exceptions were raised, the test passes
        assert True

@pytest.mark.asyncio
async def test_settings_help_bar_visibility(mock_config_path):
    # Verify the help bar exists and updates on focus
    app = OdooWtApp({"wt_root": "/tmp"}, ["master"], ["pian"], [])
    async with app.run_test() as pilot:
        await pilot.pause()
        tabs = app.query_one("#tabs", TabbedContent)
        tabs.active = "tab-settings"
        await pilot.pause()
        
        help_bar = app.query_one("#settings-help-bar")
        
        # 1. Basic existence and layout checks
        assert help_bar.display is True
        assert help_bar.region.height > 0
        
        # 2. Focus an input and check if the bar updates
        wt_input = app.query_one("#set-wt")
        wt_input.focus()
        await pilot.pause()
        
        # Check if the Info text appeared (tooltip value from main_tui.py)
        # Using render() to get the actual Rich renderable content
        content = str(help_bar.render())
        assert "Base directory where worktree folders are created" in content
        assert "Info:" in content

@pytest.mark.asyncio
async def test_visibility_toggles(mock_config_path):
    # Verify that toggling the show_prefix and show_suffix checkboxes hides the columns
    app = OdooWtApp({"wt_root": "/tmp", "show_prefix": True, "show_suffix": True}, ["master"], ["pian"], [])
    async with app.run_test() as pilot:
        await pilot.pause()
        
        version_col = app.query_one("#version-col")
        suffix_col = app.query_one("#suffix-col")
        
        # Initial state should be visible (no hidden class)
        assert not version_col.has_class("hidden")
        assert not suffix_col.has_class("hidden")
        
        # Switch to settings tab
        tabs = app.query_one("#tabs", TabbedContent)
        tabs.active = "tab-settings"
        await pilot.pause()
        
        # Programmatically toggle the checkboxes
        prefix_cb = app.query_one("#set-show-prefix")
        suffix_cb = app.query_one("#set-show-suffix")
        prefix_cb.value = False
        suffix_cb.value = False
        
        # Wait for the 0.5s save_settings_auto debounce timer to finish
        await pilot.pause(0.6)
        
        # Both columns should now have the hidden class
        assert version_col.has_class("hidden")
        assert suffix_col.has_class("hidden")
        
        # Toggle one back on
        prefix_cb.value = True
        await pilot.pause(0.6)
        
        # Version should be visible, Suffix still hidden
        assert not version_col.has_class("hidden")
        assert suffix_col.has_class("hidden")

@pytest.mark.asyncio
async def test_spell_check():
    from odoo_wt.main_tui import spell
    assert "odoo" in spell
    assert "saas" in spell
    assert "erp" in spell
    assert "pos" in spell
    
    # Check that a typo is identified
    words = "fix_bug_in_oddo".split("_")
    unknown = spell.unknown(words)
    assert "oddo" in unknown

@pytest.mark.asyncio
async def test_wizard_mount_and_scan(monkeypatch):
    import odoo_wt.setup_wizard
    
    # Mock the scanner so it instantly returns dummy roots
    monkeypatch.setattr(odoo_wt.setup_wizard, "fast_scan", lambda: ["/mock/odoo/wt", "/mock/other/wt"])
    
    app = WizardApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert pilot.app.query_one(".title")
        
        # Wait a tiny bit for the mocked thread to yield
        await pilot.pause(0.2)
        
        status = app.query_one("#scanner-status")
        content = str(status.render())
        assert "Select a root from the proposed" in content
        
        # Verify the dropdown populated
        sel = app.query_one("#root-select")
        assert not sel.has_class("hidden")
        assert sel.value == "/mock/odoo/wt"

@pytest.mark.asyncio
async def test_wizard_scrollbar(monkeypatch):
    import odoo_wt.setup_wizard
    monkeypatch.setattr(odoo_wt.setup_wizard, "fast_scan", lambda: ["/mock"])
    
    app = WizardApp()
    # Force a small terminal size (e.g. 80 columns, 24 rows) to ensure scrolling is required
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.5)
        
        # Reveal the hidden steps so the content height increases
        app.query_one("#final-steps").remove_class("hidden")
        await pilot.pause(0.5)
        
        scroll_container = app.query_one("#wizard-scroll")

        # Verify that the virtual height (content) is greater than physical height (container)
        assert scroll_container.virtual_size.height > scroll_container.size.height        
        # Verify the scrollbar is active
        assert scroll_container.show_vertical_scrollbar is True, "Vertical scrollbar is not set to display!"

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
