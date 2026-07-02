import pytest
import asyncio
from pathlib import Path
from odoo_wt.system_discovery import decompose_branch
from odoo_wt.main_tui import OdooWtApp
from odoo_wt.app_config import config_mgr

# --- UNIT TESTS (The Brain) ---

def test_decompose_github_format():
    r, v, d, s = decompose_branch("odoo-dev:master-fix-bug-pian")
    assert r == "odoo-dev"
    assert v == "master"
    assert d == "fix-bug"
    assert s == "pian"

def test_decompose_saas_version():
    r, v, d, s = decompose_branch("saas-17.1-ui-cleanup-mate", known_versions=["saas-17.1"])
    assert v == "saas-17.1"
    assert d == "ui-cleanup"
    assert s == "mate"

def test_decompose_redundancy():
    # If the description starts with the version, it should be stripped
    # 17.0-17.0-logic-fix -> v=17.0, d=logic, s=fix (since fix is a 3-letter alphanumeric)
    r, v, d, s = decompose_branch("17.0-17.0-logic-fix", known_versions=["17.0"])
    assert v == "17.0"
    assert d == "logic"
    assert s == "fix"

def test_decompose_no_remote():
    r, v, d, s = decompose_branch("master-cool-feature-pian")
    assert r == ""
    assert v == "master"
    assert d == "cool-feature"
    assert s == "pian"

def test_decompose_ignored_suffix_fw():
    # Forward port branches ending with -fw should not have 'fw' extracted as developer suffix
    r, v, d, s = decompose_branch("odoo-dev:saas-19.1-19.0-16565-529424-fw", known_versions=["saas-19.1"])
    assert r == "odoo-dev"
    assert v == "saas-19.1"
    assert d == "19.0-16565-529424-fw"
    assert s == ""

# --- INTEGRATION TESTS (The UI) ---

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
    monkeypatch.setattr(config_mgr, "is_test_mode", True)
    
    config_mgr.config = config_mgr._get_defaults()
    config_mgr.config["auto_magic_fix"] = True # Default behavior
    return config_file

@pytest.mark.asyncio
async def test_magic_fix_ui_auto(tmp_path, monkeypatch):
    # Setup mock env
    wt_root = tmp_path / "wt"
    wt_root.mkdir()
    (wt_root / "master" / "odoo" / ".git").mkdir(parents=True)
    
    config = config_mgr.config
    config["wt_root"] = str(wt_root)
    
    monkeypatch.setattr("odoo_wt.main_tui.get_remote", lambda _: "odoo")
    monkeypatch.setattr("odoo_wt.main_tui.discover_system_data", lambda *args, **kwargs: (["master", "17.0", "saas-19.1"], ["pian", "mate", "none", "custom..."], []))

    app = OdooWtApp(config, ["master", "17.0", "saas-19.1"], ["pian", "mate", "none", "custom..."], [])
    async with app.run_test() as pilot:
        # 1. Paste a messy branch
        pilot.app.query_one("#desc").value = "odoo-dev:17.0-fix-bug-mate"
        
        # Debounce + Magic Fix execution
        await pilot.pause(0.8)
        
        # 2. Check if UI redistributed the parts
        assert pilot.app.query_one("#version").value == "17.0"
        assert pilot.app.query_one("#suffix").value == "mate"
        assert pilot.app.query_one("#desc").value == "fix-bug"

        # 3. Now paste a suffixless forward port branch to verify that the suffix is reset to "none"
        pilot.app.query_one("#desc").value = "odoo-dev:saas-19.1-19.0-16565-529424-fw"
        await pilot.pause(0.8)

        assert pilot.app.query_one("#version").value == "saas-19.1"
        assert pilot.app.query_one("#suffix").value == "none"
        assert pilot.app.query_one("#desc").value == "19.0-16565-529424-fw"

@pytest.mark.asyncio
async def test_magic_fix_ui_manual(tmp_path, monkeypatch):
    # Disable auto-fix to test the button
    config = config_mgr.config
    config["auto_magic_fix"] = False
    
    wt_root = tmp_path / "wt"
    wt_root.mkdir()
    (wt_root / "master" / "odoo" / ".git").mkdir(parents=True)
    config["wt_root"] = str(wt_root)
    
    monkeypatch.setattr("odoo_wt.main_tui.get_remote", lambda _: "odoo")
    monkeypatch.setattr("odoo_wt.main_tui.discover_system_data", lambda *args, **kwargs: (["master", "17.0"], ["pian", "mate"], []))

    app = OdooWtApp(config, ["master", "17.0"], ["pian", "mate"], [])
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#desc")
        await pilot.press(*"odoo-dev:17.0-new-logic-mate")
        await pilot.pause(0.6)
        
        # Values should still be defaults (auto is OFF)
        assert pilot.app.query_one("#version").value == "master"
        
        # Magic button should be visible
        btn = pilot.app.query_one("#magic-btn")
        assert "hidden" not in btn.classes
        
        # Click it
        await pilot.click("#magic-btn")
        await pilot.pause(0.1)
        
        # Now it should be fixed
        assert pilot.app.query_one("#version").value == "17.0"
        assert pilot.app.query_one("#desc").value == "new-logic"
        assert pilot.app.query_one("#suffix").value == "mate"
