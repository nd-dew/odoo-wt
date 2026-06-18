import pytest
from odoo_wt.main_tui import OdooWtApp
from odoo_wt.setup_wizard import WizardApp
from odoo_wt.app_config import config_mgr
from odoo_wt.system_discovery import parse_branch_name, shorten_path, expand_path
from textual.widgets import TabbedContent, Select
from pathlib import Path
import json

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

def test_worktree_discovery_with_known_lists(tmp_path):
    from odoo_wt.system_discovery import discover_system_data
    
    wt_root = tmp_path / "wt"
    wt_root.mkdir()
    
    v_list, s_list, worktrees = discover_system_data(
        str(wt_root), 
        "pian", 
        known_versions=["18.0", "saas-18.2"], 
        known_suffixes=["mate", "elco"]
    )
    
    assert "18.0" in v_list
    assert "saas-18.2" in v_list
    assert "master" in v_list
    
    assert "mate" in s_list
    assert "elco" in s_list
    assert "pian" in s_list

def test_config_management(mock_config_path):
    # This test specifically tests writing, so we temporarily allow it
    config_mgr.is_test_mode = False
    
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
    # This test specifically tests writing, so we temporarily allow it
    config_mgr.is_test_mode = False
    
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

    # Test 3: Dynamic Fallback base version extraction
    # If version dropdown is "none" or empty, but description is "saas-19.3"
    engine_fallback = DeployEngine(config, {"version": "", "desc": "saas-19.3", "suffix": ""})
    assert engine_fallback.base_v == "saas-19.3"
    assert engine_fallback.branch_name == "saas-19.3"
    commands_run.clear()
    async for _ in engine_fallback.deploy_repo(Path("/tmp"), "odoo", "odoo"):
        pass
    # It should dynamically fetch saas-19.3
    assert ["git", "fetch", "odoo", "saas-19.3"] in commands_run


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

def test_runbot_client(monkeypatch):
    from odoo_wt.runbot_client import find_runbot_batch_url, check_batch_details
    
    class MockResponse:
        def __init__(self, data):
            self.data = data
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
            
    def mock_urlopen_search(req, *args, **kwargs):
        return MockResponse(b'<html><body><a href="/runbot/batch/2588843" title="2026-06-17 06:14:59">Batch</a></body></html>')
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_search)
    res = find_runbot_batch_url("17.0-fix-pian")
    assert res == ("https://runbot.odoo.com/runbot/batch/2588843", "2026-06-17 06:14:59")
    
    def mock_urlopen_batch(req, *args, **kwargs):
        return MockResponse(
            b'class="btn-success" btn-success btn-success '
            b'class="btn-danger" '
            b'class="fa-spinner" fa-spinner'
        )
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_batch)
    success, failed, warning, running = check_batch_details("https://runbot.odoo.com/runbot/batch/2588843")
    assert success == 3
    assert failed == 1
    assert warning == 0
    assert running == 2

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

def test_query_branch_status(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    
    class MockResponse:
        def __init__(self, data):
            self.data = data
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
            
    def mock_urlopen_search(req, *args, **kwargs):
        return MockResponse(
            b'<html><body><a href="/runbot/batch/2588843" title="2026-06-17 06:14:59">Batch</a>'
            b'<div class="batch_slots">'
            b'class="btn-success" '
            b'class="btn-danger" '
            b'class="fa-spinner"'
            b'</div>'
            b'<a class="dropdown-item" href="https://github.com/odoo-dev/odoo/pull/5161" title="View PR">'
            b'<a class="fa-sign-in btn btn-info" href="https://github.com/odoo-dev/enterprise/pull/1356" title="View PR">'
            b'</body></html>'
        )
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_search)
    res = query_branch_status("17.0-fix-pian")
    assert res == (
        "https://runbot.odoo.com/runbot/batch/2588843", 
        "2026-06-17 06:14:59", 
        1, 1, 0, 1,
        "https://github.com/odoo-dev/odoo/pull/5161",
        "https://github.com/odoo-dev/enterprise/pull/1356"
    )

def test_print_cli_status(monkeypatch, tmp_path):
    from odoo_wt.cli_main import print_cli_status
    
    config = {
        "wt_root": str(tmp_path),
        "suffix": "pian"
    }
    
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: ([], [], [
        {"name": "master", "path": "/path/master", "version": "master"},
        {"name": "17.0-fix-pian", "path": "/path/17.0-fix-pian", "version": "17.0"}
    ]))
    
    monkeypatch.setattr("odoo_wt.runbot_client.query_branch_status", lambda name: ("https://runbot.odoo.com/runbot/batch/1", "2026-06-17 12:00:00", 10, 0, 0, 0, "https://github.com/odoo/odoo/pull/1", "https://github.com/odoo/enterprise/pull/1"))
    
    # Invoke CLI status function to verify it runs error-free
    print_cli_status(config)

def test_cli_typo_correction(monkeypatch, tmp_path):
    from odoo_wt import cli_main
    
    # Mock sys.argv
    monkeypatch.setattr("sys.argv", ["odoo-wt", "statu"])
    # Mock TTY
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    
    # Mock check_dependencies
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock config exists and load
    config_path = tmp_path / "odoo-wt.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    
    # Mock discover_system_data to avoid actual path errors
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], []
    ))
    
    # Mock input to select the status option
    monkeypatch.setattr("builtins.input", lambda _: "status")
    
    # Track if print_cli_status was called
    called = False
    def mock_print_cli_status(config):
        nonlocal called
        called = True
        
    monkeypatch.setattr("odoo_wt.cli_main.print_cli_status", mock_print_cli_status)
    
    # Intercept sys.exit(0)
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
    assert excinfo.value.code == 0
    assert called == True

def test_worktree_recency_sorting(tmp_path):
    from odoo_wt.main_tui import OdooWtApp
    
    config = {
        "wt_root": str(tmp_path),
        "suffix": "pian",
        "worktree_recency": {
            "/path/wt_old": "2026-06-17T12:00:00",
            "/path/wt_new": "2026-06-17T15:00:00"
        }
    }
    
    app = OdooWtApp(config, ["master"], ["pian"], [
        {"name": "wt_old", "path": "/path/wt_old", "version": "17.0"},
        {"name": "wt_new", "path": "/path/wt_new", "version": "17.0"}
    ])
    
    def recency_sort_key(wt_dict):
        path_str = wt_dict["path"]
        ts = app.config.get("worktree_recency", {}).get(path_str, "")
        return (ts, app._version_sort_key(wt_dict), wt_dict["name"])
        
    sorted_wts = sorted(app.worktrees, key=recency_sort_key, reverse=True)
    
    assert sorted_wts[0]["name"] == "wt_new"
    assert sorted_wts[1]["name"] == "wt_old"

def test_cli_help_flag(monkeypatch, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "--help"])
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Usage:" in captured.out
    assert "Primary Subcommands" in captured.out
    assert "Options & Flags" in captured.out

def test_cli_version_flag(monkeypatch, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "--version"])
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "odoo-wt v" in captured.out

def test_cli_config_path_flag(monkeypatch, capsys, tmp_path):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "--config-path"])
    
    config_path = tmp_path / "odoo-wt.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {})
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert str(config_path.absolute()) in captured.out.strip()

def test_cli_switcher_mode(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "17.0-fix-pian"])
    
    config_path = tmp_path / "odoo-wt.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data to return existing worktree
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [{"name": "17.0-fix-pian", "path": "/path/root/17.0-fix-pian", "version": "17.0"}]
    ))
    
    # Mock query_branch_status to return None or dummy
    monkeypatch.setattr("odoo_wt.runbot_client.query_branch_status", lambda name: None)
    
    # Assert that os.chdir and os.execv are called with correct target path and shell
    chdir_called = None
    def mock_chdir(path):
        nonlocal chdir_called
        chdir_called = path
    monkeypatch.setattr("os.chdir", mock_chdir)
    
    execv_called = None
    def mock_execv(shell, args):
        nonlocal execv_called
        execv_called = (shell, args)
        # Raise SystemExit to break out of main() cleanly
        raise SystemExit(0)
    monkeypatch.setattr("os.execv", mock_execv)
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    assert chdir_called == "/path/root/17.0-fix-pian"
    assert execv_called is not None

def test_cli_list_command(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "list"])
    
    config_path = tmp_path / "odoo-wt.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data to return existing worktrees
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [
            {"name": "17.0-fix-pian", "path": "/path/root/17.0-fix-pian", "version": "17.0"},
            {"name": "master-bug-pian", "path": "/path/root/master-bug-pian", "version": "master"}
        ]
    ))
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    assert "master-bug-pian" in lines
    assert "17.0-fix-pian" in lines

def test_cli_delete_command(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "-d", "17.0-fix-pian"])
    
    config_path = tmp_path / "odoo-wt.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data to return existing worktrees
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [{"name": "17.0-fix-pian", "path": "/path/root/17.0-fix-pian", "version": "17.0"}]
    ))
    
    # Mock inputs to return yes
    monkeypatch.setattr("builtins.input", lambda _: "y")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    
    # Mock subprocess.run to avoid actual shell command triggers
    sub_called = []
    def mock_run(cmd, **kwargs):
        sub_called.append(cmd)
    monkeypatch.setattr("subprocess.run", mock_run)
    
    # Mock shutil.rmtree to avoid directory deletion error
    monkeypatch.setattr("shutil.rmtree", lambda *_, **__: None)
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    assert len(sub_called) > 0
    captured = capsys.readouterr()
    assert "🧹 Deleting worktree" in captured.out
    assert "✨ Deleted successfully." in captured.out

def test_cli_switcher_multiple_matches(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "debrief"])
    
    config_path = tmp_path / "odoo-wt.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data to return two debrief matching worktrees
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [
            {"name": "master-call_debrief-design-brd", "path": "/path/root/master-call_debrief-design-brd", "version": "master"},
            {"name": "17.0-debrief-pian", "path": "/path/root/17.0-debrief-pian", "version": "17.0"}
        ]
    ))
    
    # Mock input to select the first one [1]
    monkeypatch.setattr("builtins.input", lambda _: "1")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    
    # Mock query_branch_status to return None
    monkeypatch.setattr("odoo_wt.runbot_client.query_branch_status", lambda name: None)
    
    chdir_called = None
    def mock_chdir(path):
        nonlocal chdir_called
        chdir_called = path
    monkeypatch.setattr("os.chdir", mock_chdir)
    
    execv_called = None
    def mock_execv(shell, args):
        nonlocal execv_called
        execv_called = (shell, args)
        raise SystemExit(0)
    monkeypatch.setattr("os.execv", mock_execv)
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    assert chdir_called == "/path/root/17.0-debrief-pian"
    assert execv_called is not None
    captured = capsys.readouterr()
    assert "Direct Matches" in captured.out

def test_cli_subcommand_typo_correction(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "lis"])
    
    config_path = tmp_path / "odoo-wt.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data to return existing worktrees
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [
            {"name": "17.0-fix-pian", "path": "/path/root/17.0-fix-pian", "version": "17.0"}
        ]
    ))
    
    # Mock input to return list
    monkeypatch.setattr("builtins.input", lambda _: "list")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "17.0-fix-pian" in captured.out

def test_get_latest_pr_comment(monkeypatch):
    from odoo_wt.runbot_client import get_latest_pr_comment
    
    # Mock authentication status
    monkeypatch.setattr("odoo_wt.runbot_client.is_gh_authenticated", lambda: True)
    
    # Mock fetch_repo_comments to return custom fake comments
    def mock_fetch_repo_comments(repo_name, pr_number):
        if repo_name == "odoo/odoo":
            return [
                {"user": "robodoo", "created_at": "2026-06-18T10:00:00Z", "html_url": "link1", "is_ent": False},
                {"user": "Matthieu", "created_at": "2026-06-18T08:00:00Z", "html_url": "link2", "is_ent": False}
            ]
        elif repo_name == "odoo/enterprise":
            return [
                {
                    "user": "xavierbol", 
                    "created_at": "2026-06-18T09:00:00Z", 
                    "html_url": "link3", 
                    "is_ent": True,
                    "body": "This is an extremely long code review comment written by xavierbol to test the 50-char ellipses truncation guard inside odoo-wt!"
                }
            ]
        return []
        
    monkeypatch.setattr("odoo_wt.runbot_client.fetch_repo_comments", mock_fetch_repo_comments)
    
    # Call comment resolver with simulated Community and Enterprise links
    latest = get_latest_pr_comment(
        "https://github.com/odoo/odoo/pull/12345",
        "https://github.com/odoo/enterprise/pull/5678"
    )
    
    assert latest is not None
    # xavierbol (09:00:00) is newer than Matthieu (08:00:00) and robodoo (10:00:00) is filtered as a bot!
    assert latest["user"] == "xavierbol"
    assert latest["html_url"] == "link3"
    assert latest["is_ent"] is True
    # Truncate at exactly 50 chars + "..."
    assert latest["body_clean"] == "This is an extremely long code review comment writ..."

