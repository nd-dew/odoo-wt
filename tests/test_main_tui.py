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
from odoo_wt.custom_screens import DeleteConfirmScreen

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

@pytest.mark.asyncio
async def test_main_tui_runbot_column(tmp_path, monkeypatch):
    from odoo_wt.main_tui import OdooWtApp
    
    wt_root = tmp_path / "wt"
    wt_root.mkdir()
    (wt_root / "master" / "odoo" / ".git").mkdir(parents=True)
    
    config = config_mgr.config
    config["wt_root"] = str(wt_root)
    
    monkeypatch.setattr("odoo_wt.main_tui.get_remote", lambda _: "odoo")
    monkeypatch.setattr("odoo_wt.main_tui.discover_system_data", lambda *_, **__: (["master"], ["none"], [{"name": "17.0-fix-pian", "path": str(wt_root / "17.0-fix-pian"), "version": "17.0", "suffix": "pian"}]))
    monkeypatch.setattr("odoo_wt.main_tui.OdooWtApp.run_runbot_checker", lambda self: None)
    
    app = OdooWtApp(config, ["master"], ["none"], [{"name": "17.0-fix-pian", "path": str(wt_root / "17.0-fix-pian"), "version": "17.0", "suffix": "pian"}])
    async with app.run_test() as pilot:
        table = pilot.app.query_one("#wt-table")
        
        cols = [col.label.plain for col in table.columns.values()]
        assert "Branch Name" in cols
        assert "Runbot Status" in cols
        assert "Link" in cols
        
        assert "col-branch" in table.columns
        assert "col-runbot" in table.columns
        assert "col-link" in table.columns

def test_tui_base_branch_minimal_status(monkeypatch):
    from odoo_wt.main_tui import OdooWtApp
    
    app = OdooWtApp(
        config={"wt_root": "/path/root", "suffix": "pian"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[{"name": "master", "path": "/path/root/master", "version": "master"}],
        version_str="dev"
    )
    
    # Mock DataTable and Input elements for synchronous run
    rows_added = []
    class MockDataTable:
        def clear(self): pass
        def add_row(self, *args, **kwargs):
            rows_added.append(args)
            
    def mock_query_one(selector, *args, **kwargs):
        if selector == "#wt-table":
            return MockDataTable()
        class MockSearch:
            value = ""
        return MockSearch()
        
    app.query_one = mock_query_one
    
    # Run the synchronous table populator
    app.populate_table()
    
    # Verify that base branches get minimal symbols
    assert len(rows_added) == 1
    select_cell, branch_name, status, link, comment = rows_added[0]
    assert branch_name == "master"
    assert status == "⚪"
    assert "Board" in link

def test_tui_deleting_row_markup_safety(monkeypatch):
    from odoo_wt.main_tui import OdooWtApp
    
    app = OdooWtApp(
        config={"wt_root": "/path/root", "suffix": "pian"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[{"name": "saas-19.4-my_feature", "path": "/path/root/saas-19.4-my_feature", "version": "saas-19.4"}],
        version_str="dev"
    )
    
    # Mark the path as currently deleting
    app.deleting_paths.add("/path/root/saas-19.4-my_feature")
    
    rows_added = []
    class MockDataTable:
        def clear(self): pass
        def add_row(self, *args, **kwargs):
            rows_added.append(args)
            
    def mock_query_one(selector, *args, **kwargs):
        if selector == "#wt-table":
            return MockDataTable()
        class MockSearch:
            value = ""
        return MockSearch()
        
    app.query_one = mock_query_one
    
    # Populate the table (should format deleting row without raising MarkupError!)
    app.populate_table()
    
    assert len(rows_added) == 1
    select_cell, branch_name, status, link, comment = rows_added[0]
    
    # Assert display_name has the strike-through, but raw name in link does NOT have nested strike!
    assert "[strike]saas-19.4-my_feature[/strike]" in branch_name
    assert "search=saas-19.4-my_feature" in link
    assert "[strike]" not in link  # Symmetrical shield against nested markup crash!

@pytest.mark.asyncio
async def test_wizard_suffix_placeholder(monkeypatch, tmp_path):
    from odoo_wt.setup_wizard import WizardApp
    from odoo_wt.app_config import config_mgr
    
    config_file = tmp_path / "odoo-wt-wizard.json"
    monkeypatch.setattr(config_mgr, "config_file", config_file)
    monkeypatch.setattr(config_mgr, "is_test_mode", True)
    
    app = WizardApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        
        # Suffix-input should be empty initially, but have placeholder set to "pian"
        suffix_input = pilot.app.query_one("#suffix-input")
        assert suffix_input.value == ""
        assert suffix_input.placeholder == "pian"
        
        # Test submission with empty suffix - it should default to "pian"
        # Mock other fields and save call to ensure it runs cleanly
        monkeypatch.setattr(pilot.app, "query_one", lambda selector, *args, **kwargs: (
            type("MockInput", (object,), {"value": "custom", "has_class": lambda *_: False})()
            if selector in ("#root-select", "#custom-root", "#env-path")
            else suffix_input
        ))
        
        saved_config = None
        def mock_save(config):
            nonlocal saved_config
            saved_config = config
        monkeypatch.setattr(config_mgr, "save", mock_save)
        
        pilot.app.on_finish()
        assert saved_config is not None
        assert saved_config["suffix"] == "pian"

@pytest.mark.asyncio
async def test_wizard_root_creation_and_clones_warning(monkeypatch, tmp_path):
    from odoo_wt.setup_wizard import WizardApp
    from odoo_wt.app_config import config_mgr
    
    config_file = tmp_path / "odoo-wt-wizard-warn.json"
    monkeypatch.setattr(config_mgr, "config_file", config_file)
    monkeypatch.setattr(config_mgr, "is_test_mode", True)
    
    # We will target a non-existent directory within tmp_path
    non_existent_root = tmp_path / "new_wt_root"
    assert not non_existent_root.exists()
    
    app = WizardApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        
        # Mock inputs and selectors to return our non-existent root path
        suffix_input = pilot.app.query_one("#suffix-input")
        monkeypatch.setattr(pilot.app, "query_one", lambda selector, *args, **kwargs: (
            type("MockSelect", (object,), {"value": "custom", "has_class": lambda *_: False})()
            if selector == "#root-select"
            else type("MockCustomRoot", (object,), {"value": str(non_existent_root)})()
            if selector == "#custom-root"
            else type("MockEnvPath", (object,), {"value": str(tmp_path / "envs")})()
            if selector == "#env-path"
            else suffix_input
        ))
        
        notifications = []
        def mock_notify(message, severity="info", timeout=3.0):
            notifications.append((message, severity))
        monkeypatch.setattr(pilot.app, "notify", mock_notify)
        
        saved_config = None
        def mock_save(config):
            nonlocal saved_config
            saved_config = config
        monkeypatch.setattr(config_mgr, "save", mock_save)
        
        pilot.app.on_finish()
        
        # Verify that the directory was automatically created on disk!
        assert non_existent_root.exists()
        
        # Verify that correct notifications were raised
        assert any("does not exist. Creating it..." in msg and sev == "information" for msg, sev in notifications)
        assert any("are missing under master/. Remember to clone them!" in msg and sev == "warning" for msg, sev in notifications)

@pytest.mark.asyncio
async def test_wizard_live_path_feedback(monkeypatch, tmp_path):
    from odoo_wt.setup_wizard import WizardApp
    from odoo_wt.app_config import config_mgr
    
    config_file = tmp_path / "odoo-wt-wizard-live.json"
    monkeypatch.setattr(config_mgr, "config_file", config_file)
    monkeypatch.setattr(config_mgr, "is_test_mode", True)
    
    app = WizardApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        
        status_label = pilot.app.query_one("#root-status-label")
        
        # Test 1: Non-existent directory live check
        non_existent = tmp_path / "non_existent_folder_xyz"
        pilot.app.check_root_path(str(non_existent))
        await pilot.pause()
        assert not status_label.has_class("hidden")
        assert "Path does not exist" in str(status_label.render())
        
        # Test 2: Existing folder but missing clones
        existing_folder = tmp_path / "existing_folder_xyz"
        existing_folder.mkdir(parents=True, exist_ok=True)
        pilot.app.check_root_path(str(existing_folder))
        await pilot.pause()
        assert not status_label.has_class("hidden")
        assert "No Odoo base repositories found" in str(status_label.render())
        assert "git clone" in str(status_label.render())
        
        # Test 3: Existing folder and valid clones
        (existing_folder / "master" / "odoo" / ".git").mkdir(parents=True, exist_ok=True)
        (existing_folder / "master" / "enterprise" / ".git").mkdir(parents=True, exist_ok=True)
        pilot.app.check_root_path(str(existing_folder))
        await pilot.pause()
        assert not status_label.has_class("hidden")
        assert "Found Odoo base clones" in str(status_label.render())

@pytest.mark.asyncio
async def test_generate_settings_screenshot():
    config = {
        "wt_root": "/tmp/non_existent_folder_abc",
        "env_root": "/tmp/non_existent_envs_abc",
        "suffix": "pian",
        "default_tab": "tab-settings"
    }
    app = OdooWtApp(config, ["master"], ["pian"], [])
    async with app.run_test() as pilot:
        await pilot.pause()
        screenshot_dir = Path("screenshots")
        screenshot_dir.mkdir(exist_ok=True)
        app.save_screenshot(str(screenshot_dir / "settings_tab.svg"))


@pytest.mark.asyncio
async def test_manual_save_and_discard_buttons(monkeypatch):
    config = {
        "wt_root": "/tmp",
        "env_root": "/tmp/envs",
        "suffix": "pian",
        "default_tab": "tab-settings"
    }
    app = OdooWtApp(config, ["master"], ["pian"], [])
    
    saved_called = False
    def mock_save(self_config):
        nonlocal saved_called
        saved_called = True
    monkeypatch.setattr(config_mgr, "save", mock_save)

    async with app.run_test() as pilot:
        await pilot.pause()
        
        # Find save and discard buttons, verify they start as disabled
        save_btn = pilot.app.query_one("#save-settings-btn")
        discard_btn = pilot.app.query_one("#reset-settings-btn")
        assert save_btn.disabled is True
        assert discard_btn.disabled is True

        # Modify a setting (like changing default suffix input value)
        suffix_input = pilot.app.query_one("#set-suffix")
        suffix_input.value = "test"
        await pilot.pause()

        # Verify buttons are now enabled
        assert save_btn.disabled is False
        assert discard_btn.disabled is False

        # Click save and verify save is called and buttons are disabled again
        await pilot.click("#save-settings-btn")
        await pilot.pause()
        assert saved_called is True
        assert save_btn.disabled is True
        assert discard_btn.disabled is True

        # Now test Discard/Reset button flow
        suffix_input.value = "test-discard"
        await pilot.pause()

        # Buttons should become active again
        assert save_btn.disabled is False
        assert discard_btn.disabled is False

        # Click Discard and wait for the async events to complete
        await pilot.click("#reset-settings-btn")
        await pilot.pause()

        # Value should be restored to original "pian", and buttons must stay disabled!
        assert suffix_input.value == "pian"
        assert save_btn.disabled is True
        assert discard_btn.disabled is True

        # Now verify that a genuine edit made immediately after is NOT ignored (no 200ms gap!)
        suffix_input.value = "changed-again"
        await pilot.pause()

        assert save_btn.disabled is False
        assert discard_btn.disabled is False


@pytest.mark.asyncio
async def test_tui_bulk_selection_toggle(monkeypatch):
    from odoo_wt.main_tui import OdooWtApp
    from textual.widgets import DataTable

    app = OdooWtApp(
        config={"wt_root": "/path/root", "suffix": "pian", "default_tab": "tab-manage"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[
            {"name": "master", "path": "/path/root/master", "version": "master"},
            {"name": "17.0-feature-pian", "path": "/path/root/17.0-feature-pian", "version": "17.0"}
        ],
        version_str="dev"
    )

    monkeypatch.setattr("odoo_wt.main_tui.OdooWtApp.run_runbot_checker", lambda self: None)

    async with app.run_test() as pilot:
        # Initially empty selection
        assert len(pilot.app.selected_wts) == 0

        table = pilot.app.query_one("#wt-table", DataTable)
        
        # Select the feature row (which is at coordinate 1, since master is row 0)
        table.cursor_coordinate = (1, 0)
        
        # Trigger toggle select
        pilot.app.action_toggle_select()
        assert "/path/root/17.0-feature-pian" in pilot.app.selected_wts

        # Toggle again to deselect
        pilot.app.action_toggle_select()
        assert "/path/root/17.0-feature-pian" not in pilot.app.selected_wts

        # Try to select master (row 0)
        table.cursor_coordinate = (0, 0)
        pilot.app.action_toggle_select()
        # Should remain empty because master is protected
        assert "/path/root/master" not in pilot.app.selected_wts


@pytest.mark.asyncio
async def test_tui_select_all_deselect_all(monkeypatch):
    from odoo_wt.main_tui import OdooWtApp

    app = OdooWtApp(
        config={"wt_root": "/path/root", "suffix": "pian", "default_tab": "tab-manage"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[
            {"name": "master", "path": "/path/root/master", "version": "master"},
            {"name": "17.0-feat1-pian", "path": "/path/root/17.0-feat1-pian", "version": "17.0"},
            {"name": "17.0-feat2-pian", "path": "/path/root/17.0-feat2-pian", "version": "17.0"}
        ],
        version_str="dev"
    )

    monkeypatch.setattr("odoo_wt.main_tui.OdooWtApp.run_runbot_checker", lambda self: None)

    async with app.run_test() as pilot:
        # Select All
        pilot.app.action_select_all()
        assert "/path/root/17.0-feat1-pian" in pilot.app.selected_wts
        assert "/path/root/17.0-feat2-pian" in pilot.app.selected_wts
        assert "/path/root/master" not in pilot.app.selected_wts  # protected

        # Deselect All
        pilot.app.action_deselect_all()
        assert len(pilot.app.selected_wts) == 0


@pytest.mark.asyncio
async def test_tui_bulk_delete_routing(monkeypatch):
    from odoo_wt.main_tui import OdooWtApp
    from odoo_wt.custom_screens import DeleteConfirmScreen, BulkDeleteConfirmScreen

    app = OdooWtApp(
        config={"wt_root": "/path/root", "suffix": "pian", "default_tab": "tab-manage"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[
            {"name": "master", "path": "/path/root/master", "version": "master"},
            {"name": "17.0-feat-pian", "path": "/path/root/17.0-feat-pian", "version": "17.0"}
        ],
        version_str="dev"
    )

    monkeypatch.setattr("odoo_wt.main_tui.OdooWtApp.run_runbot_checker", lambda self: None)

    screens_pushed = []
    def mock_push_screen(screen, callback=None):
        screens_pushed.append(screen)

    async with app.run_test() as pilot:
        pilot.app.push_screen = mock_push_screen

        # Scenario 1: selected_wts is empty -> pushes regular DeleteConfirmScreen
        pilot.app.query_one("#wt-table").cursor_coordinate = (1, 0)
        pilot.app.action_delete_wt()
        assert len(screens_pushed) == 1
        assert isinstance(screens_pushed[0], DeleteConfirmScreen)

        # Scenario 2: selected_wts is populated -> pushes BulkDeleteConfirmScreen
        pilot.app.selected_wts.add("/path/root/17.0-feat-pian")
        pilot.app.action_delete_wt()
        assert len(screens_pushed) == 2
        assert isinstance(screens_pushed[1], BulkDeleteConfirmScreen)
        assert screens_pushed[1].wt_names == ["17.0-feat-pian"]


class MockProcess:
    def __init__(self, code=0, stderr=b""):
        self.returncode = code
        self.stderr = stderr
    async def communicate(self):
        return b"", self.stderr


@pytest.mark.asyncio
async def test_do_single_deletion_success(monkeypatch, tmp_path):
    from odoo_wt.main_tui import OdooWtApp

    # Setup directories
    wt_root = tmp_path / "root"
    wt_root.mkdir()
    master_dir = wt_root / "master"
    master_dir.mkdir()
    (master_dir / "odoo").mkdir()
    (master_dir / "enterprise").mkdir()

    feat_dir = wt_root / "17.0-feat-pian"
    feat_dir.mkdir()
    (feat_dir / "odoo").mkdir()
    (feat_dir / "enterprise").mkdir()

    app = OdooWtApp(
        config={"wt_root": str(wt_root), "suffix": "pian"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[],
        version_str="dev"
    )

    subprocess_calls = []
    async def mock_subprocess_exec(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        return MockProcess(0)

    shutil_calls = []
    def mock_rmtree(path, *args, **kwargs):
        shutil_calls.append(path)

    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_subprocess_exec)
    monkeypatch.setattr("shutil.rmtree", mock_rmtree)

    # Call _do_single_deletion directly
    await app._do_single_deletion(str(feat_dir), "17.0-feat-pian")

    # Verify git worktree removes were executed with correct cwd
    git_remove_calls = [c for c in subprocess_calls if "remove" in c[0]]
    assert len(git_remove_calls) == 2
    
    cwds = {c[1]["cwd"] for c in git_remove_calls}
    assert cwds == {master_dir / "odoo", master_dir / "enterprise"}

    # Verify git worktree prunes were executed
    git_prune_calls = [c for c in subprocess_calls if "prune" in c[0]]
    assert len(git_prune_calls) == 2

    # Verify shutil.rmtree was called with the correct target directory
    assert len(shutil_calls) == 1
    assert shutil_calls[0] == feat_dir


@pytest.mark.asyncio
async def test_do_single_deletion_subprocess_failure(monkeypatch, tmp_path):
    from odoo_wt.main_tui import OdooWtApp

    wt_root = tmp_path / "root"
    wt_root.mkdir()
    feat_dir = wt_root / "17.0-feat-pian"
    feat_dir.mkdir()
    (feat_dir / "odoo").mkdir()

    app = OdooWtApp(
        config={"wt_root": str(wt_root), "suffix": "pian"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[],
        version_str="dev"
    )

    # Subprocess fails with code 1 and some stderr
    async def mock_subprocess_exec(*args, **kwargs):
        return MockProcess(1, stderr=b"dirty working tree")

    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_subprocess_exec)

    with pytest.raises(RuntimeError) as exc_info:
        await app._do_single_deletion(str(feat_dir), "17.0-feat-pian")
    assert "git worktree remove failed" in str(exc_info.value)
    assert "dirty working tree" in str(exc_info.value)


@pytest.mark.asyncio
async def test_do_single_deletion_success_even_on_prune_failure(monkeypatch, tmp_path):
    from odoo_wt.main_tui import OdooWtApp

    # Setup directories
    wt_root = tmp_path / "root"
    wt_root.mkdir()
    master_dir = wt_root / "master"
    master_dir.mkdir()
    (master_dir / "odoo").mkdir()
    (master_dir / "enterprise").mkdir()

    feat_dir = wt_root / "17.0-feat-pian"
    feat_dir.mkdir()
    (feat_dir / "odoo").mkdir()
    (feat_dir / "enterprise").mkdir()

    app = OdooWtApp(
        config={"wt_root": str(wt_root), "suffix": "pian"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[],
        version_str="dev"
    )

    subprocess_calls = []
    async def mock_subprocess_exec(*args, **kwargs):
        subprocess_calls.append((args, kwargs))
        if "prune" in args:
            return MockProcess(1, stderr=b"lock error")
        return MockProcess(0)

    shutil_calls = []
    def mock_rmtree(path, *args, **kwargs):
        shutil_calls.append(path)

    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_subprocess_exec)
    monkeypatch.setattr("shutil.rmtree", mock_rmtree)

    # Call _do_single_deletion directly — it must NOT raise an exception on prune failure!
    await app._do_single_deletion(str(feat_dir), "17.0-feat-pian")

    # Verify prune was indeed called and failed
    git_prune_calls = [c for c in subprocess_calls if "prune" in c[0]]
    assert len(git_prune_calls) == 2

    # Verify shutil.rmtree was still successfully executed to physically delete the folder!
    assert len(shutil_calls) == 1
    assert shutil_calls[0] == feat_dir


@pytest.mark.asyncio
async def test_execute_deletion_single_failure_keeps_worktree(monkeypatch, tmp_path):
    from odoo_wt.main_tui import OdooWtApp

    wt_root = tmp_path / "root"
    wt_root.mkdir()
    feat_dir = wt_root / "17.0-feat-pian"

    app = OdooWtApp(
        config={"wt_root": str(wt_root), "suffix": "pian"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[{"name": "17.0-feat-pian", "path": str(feat_dir), "version": "17.0"}],
        version_str="dev"
    )

    monkeypatch.setattr("odoo_wt.main_tui.OdooWtApp.run_runbot_checker", lambda self: None)

    # Force failure
    async def mock_do_single_deletion(target_path_str, name):
        raise PermissionError("Files in use")

    monkeypatch.setattr(app, "_do_single_deletion", mock_do_single_deletion)

    notifications = []
    def mock_notify(message, severity="info", timeout=None):
        notifications.append((message, severity))
    monkeypatch.setattr(app, "notify", mock_notify)

    async with app.run_test() as pilot:
        worker = pilot.app.execute_deletion(str(feat_dir), "17.0-feat-pian")
        await worker.wait()
        await pilot.pause()

        # Check notification reports error
        assert any("Files in use" in msg and sev == "error" for msg, sev in notifications)
        # Verify the worktree path remains in the worktrees list!
        assert any(wt["path"] == str(feat_dir) for wt in pilot.app.worktrees)


@pytest.mark.asyncio
async def test_execute_bulk_deletion_partial_failure(monkeypatch, tmp_path):
    from odoo_wt.main_tui import OdooWtApp

    wt_root = tmp_path / "root"
    wt_root.mkdir()
    feat1 = wt_root / "17.0-feat1-pian"
    feat2 = wt_root / "17.0-feat2-pian"

    app = OdooWtApp(
        config={"wt_root": str(wt_root), "suffix": "pian"},
        v_list=["17.0"], s_list=["pian"],
        worktrees=[
            {"name": "17.0-feat1-pian", "path": str(feat1), "version": "17.0"},
            {"name": "17.0-feat2-pian", "path": str(feat2), "version": "17.0"}
        ],
        version_str="dev"
    )

    monkeypatch.setattr("odoo_wt.main_tui.OdooWtApp.run_runbot_checker", lambda self: None)

    # Force success for feat1, but failure for feat2
    async def mock_do_single_deletion(target_path_str, name):
        if name == "17.0-feat2-pian":
            raise RuntimeError("disk read failure")

    monkeypatch.setattr(app, "_do_single_deletion", mock_do_single_deletion)

    notifications = []
    def mock_notify(message, severity="info", timeout=None):
        notifications.append((message, severity))
    monkeypatch.setattr(app, "notify", mock_notify)

    async with app.run_test() as pilot:
        # Populate selections
        pilot.app.selected_wts.add(str(feat1))
        pilot.app.selected_wts.add(str(feat2))

        worker = pilot.app.execute_bulk_deletion([str(feat1), str(feat2)], ["17.0-feat1-pian", "17.0-feat2-pian"])
        await worker.wait()
        await pilot.pause()

        # Notifications should report successful deletions AND failures
        assert any("Successfully deleted" in msg and sev == "success" for msg, sev in notifications)
        assert any("Failed to delete" in msg and "disk read failure" in msg and sev == "error" for msg, sev in notifications)

        # Selections must be cleared
        assert len(pilot.app.selected_wts) == 0

        # Successful one is removed, failed one remains in self.worktrees
        assert not any(wt["path"] == str(feat1) for wt in pilot.app.worktrees)
        assert any(wt["path"] == str(feat2) for wt in pilot.app.worktrees)


