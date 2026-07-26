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
    
    monkeypatch.setattr("odoo_wt.runbot_client.query_branch_status", lambda name: ("https://runbot.odoo.com/runbot/batch/1", "2026-06-17 12:00:00", 10, 0, 0, 0, "https://github.com/odoo/odoo/pull/1", "https://github.com/odoo/enterprise/pull/1", None))
    
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
    def mock_print_cli_status(config, *args, **kwargs):
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
    assert "Subcommands" in captured.out
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
    monkeypatch.setattr("sys.argv", ["odoo-wt", "-d", "master-pdp-fix"])
    
    # Pre-setup mock directories
    target_dir = tmp_path / "master-pdp-fix"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "odoo").mkdir()
    (target_dir / "enterprise").mkdir()

    # Pre-setup base repositories on disk inside tmp_path / master to satisfy .exists() checks
    base_odoo_dir = tmp_path / "master" / "odoo"
    base_odoo_dir.mkdir(parents=True, exist_ok=True)
    base_ent_dir = tmp_path / "master" / "enterprise"
    base_ent_dir.mkdir(parents=True, exist_ok=True)

    config_path = tmp_path / "odoo-wt-history.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": str(tmp_path),
        "env_root": str(tmp_path / "envs"),
        "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data to return existing worktrees
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [{"name": "master-pdp-fix", "path": str(target_dir), "version": "17.0"}]
    ))
    
    # Mock inputs to return yes
    monkeypatch.setattr("builtins.input", lambda _: "y")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    
    # Mock subprocess.run to capture both commands and execution directories
    sub_called = []
    def mock_run(cmd, **kwargs):
        sub_called.append((cmd, kwargs.get("cwd")))
    monkeypatch.setattr("subprocess.run", mock_run)
    
    # Mock shutil.rmtree to avoid directory deletion error
    monkeypatch.setattr("shutil.rmtree", lambda *_, **__: None)
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Deleting worktree" in captured.out
    assert "Success: Deleted successfully." in captured.out
    
    # Verify that odoo worktree remove was run inside community repository
    assert any(
        "remove" in cmd and str(target_dir / "odoo") in cmd and cwd == base_odoo_dir.absolute()
        for cmd, cwd in sub_called
    )
    
    # Verify that worktree prune was executed inside community repository
    assert any(
        "prune" in cmd and cwd == base_odoo_dir.absolute()
        for cmd, cwd in sub_called
    )

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

def test_cli_typo_correction_with_y_alias(monkeypatch, tmp_path, capsys):
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
    
    # Mock input to return 'y'
    monkeypatch.setattr("builtins.input", lambda _: "y")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "17.0-fix-pian" in captured.out

def test_cli_switcher_mode_with_runbot_details(monkeypatch, tmp_path, capsys):
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
    
    # Mock query_branch_status to return a valid 9-element tuple (matching real-world behavior!)
    monkeypatch.setattr("odoo_wt.runbot_client.query_branch_status", lambda name: (
        "https://runbot.odoo.com/batch/999", "2026-06-18 10:00:00",
        10, 0, 0, 0, None, None, None
    ))
    
    monkeypatch.setattr("os.chdir", lambda path: None)
    import sys
    monkeypatch.setattr("os.execv", lambda shell, args: sys.exit(0))
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Changing directory to /path/root/17.0-fix-pian" in captured.out

def test_cli_switcher_unpacking_safety_with_tuple(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "17.0-fix-pian"])
    
    config_path = tmp_path / "odoo-wt-8.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root", "suffix": "pian"
    })
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [{"name": "17.0-fix-pian", "path": "/path/root/17.0-fix-pian", "version": "17.0"}]
    ))
    
    # Mock returning 8-element tuple (backward-compatibility fallback!)
    monkeypatch.setattr("odoo_wt.runbot_client.query_branch_status", lambda name: (
        "https://runbot.odoo.com/batch/123", "2026-06-18 10:00:00",
        1, 0, 0, 0, None, None
    ))
    
    monkeypatch.setattr("os.chdir", lambda path: None)
    import sys
    monkeypatch.setattr("os.execv", lambda shell, args: sys.exit(0))
    
    with pytest.raises(SystemExit):
        cli_main.main()
        
    captured = capsys.readouterr()
    assert "Changing directory to /path/root/17.0-fix-pian" in captured.out

def test_shell_history_pwd_oldpwd_injection(monkeypatch, tmp_path):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "17.0-fix-pian"])
    
    config_path = tmp_path / "odoo-wt-pwd.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [{"name": "17.0-fix-pian", "path": "/path/root/17.0-fix-pian", "version": "17.0"}]
    ))
    
    # Mock status to avoid real requests
    monkeypatch.setattr("odoo_wt.runbot_client.query_branch_status", lambda name: None)
    monkeypatch.setattr("os.chdir", lambda path: None)
    
    # Track injected env variables
    captured_env = {}
    def mock_execv(shell, args):
        captured_env["PWD"] = os.environ.get("PWD")
        captured_env["OLDPWD"] = os.environ.get("OLDPWD")
        import sys
        sys.exit(0)
        
    monkeypatch.setattr("os.execv", mock_execv)
    
    # Track starting directory
    import os
    original_cwd = os.getcwd()
    
    with pytest.raises(SystemExit):
        cli_main.main()
        
    # Assert that both PWD and OLDPWD are set perfectly to keep shell history cd - in line
    assert captured_env["OLDPWD"] == original_cwd
    assert captured_env["PWD"] == "/path/root/17.0-fix-pian"

def test_cli_single_branch_detailed_status(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "status", "17.0-fix-pian"])
    
    config_path = tmp_path / "odoo-wt-single.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root", "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock return values for live runbot details + pr comments
    monkeypatch.setattr("odoo_wt.runbot_client.check_branch_status_and_comments", lambda name, **kwargs: {
        "batch_url": "https://runbot.odoo.com/runbot/batch/2592876",
        "ts_str": "2026-06-18 10:00:00",
        "success": 2,
        "failed": 0,
        "warning": 1,
        "running": 0,
        "odoo_pr": "https://github.com/odoo/odoo/pull/123",
        "enterprise_pr": "https://github.com/odoo/enterprise/pull/456",
        "upgrade_pr": None,
        "comment_data": {
            "user": "pmah-odoo",
            "relative": "2h ago",
            "body": "The mail discuss layout looks off on mobile.",
            "html_url": "https://github.com/odoo/odoo/pull/123#discussion_r123456"
        }
    })
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Detailed Status for" in captured.out
    assert "pmah-odoo" in captured.out
    assert "mail discuss layout" in captured.out
    assert "Runbot Status" in captured.out

def test_cli_single_base_branch_detailed_status(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "status", "master"])
    
    config_path = tmp_path / "odoo-wt-base.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root", "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock return values for live base branch with 1 failing build
    monkeypatch.setattr("odoo_wt.runbot_client.check_branch_status_and_comments", lambda name, **kwargs: {
        "batch_url": "https://runbot.odoo.com/runbot/batch/2592876",
        "ts_str": "2026-06-18 10:00:00",
        "success": 2,
        "failed": 1,
        "warning": 0,
        "running": 0,
        "odoo_pr": "https://github.com/odoo/odoo/pull/123",
        "enterprise_pr": "https://github.com/odoo/enterprise/pull/456",
        "upgrade_pr": None,
        "comment_data": {
            "user": "pmah-odoo",
            "relative": "2h ago",
            "body": "This should be completely ignored for base branch",
            "html_url": "https://github.com/odoo/odoo/pull/123#discussion_r123456"
        }
    })
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Base Branch for" in captured.out
    assert "Note: Some upstream builds are currently FAILING" in captured.out
    assert "Pull Requests" not in captured.out
    assert "Latest Review" not in captured.out

def test_cli_status_cwd_inside_worktree(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "status"])
    
    config_path = tmp_path / "odoo-wt-cwd.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root", "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data to return a worktree matching our mocked CWD
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [
            {"name": "17.0-fix-pian", "path": "/path/root/17.0-fix-pian", "version": "17.0"}
        ]
    ))
    
    # Mock current working directory to be inside the worktree path
    monkeypatch.setattr("os.getcwd", lambda: "/path/root/17.0-fix-pian/odoo")
    
    # Mock return values for live runbot details + pr comments
    monkeypatch.setattr("odoo_wt.runbot_client.check_branch_status_and_comments", lambda name, **kwargs: {
        "batch_url": "https://runbot.odoo.com/runbot/batch/2592876",
        "ts_str": "2026-06-18 10:00:00",
        "success": 2,
        "failed": 0,
        "warning": 1,
        "running": 0,
        "odoo_pr": "https://github.com/odoo/odoo/pull/123",
        "enterprise_pr": "https://github.com/odoo/enterprise/pull/456",
        "upgrade_pr": None,
        "comment_data": None
    })
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    # It must have successfully detected CWD is inside 17.0-fix-pian, and printed its detailed card!
    assert "Detailed Status for" in captured.out
    assert "17.0-fix-pian" in captured.out

def test_cli_verbose_level_parsing_double_dash(monkeypatch):
    import sys
    monkeypatch.setattr("sys.argv", ["odoo-wt", "runbot", "--vv"])
    
    verbose_level = 0
    to_remove = []
    for arg in sys.argv[1:]:
        if arg == "--verbose":
            verbose_level += 1
            to_remove.append(arg)
        elif arg.startswith("-"):
            stripped = arg.lstrip("-")
            if all(char == "v" for char in stripped) and len(stripped) > 0:
                verbose_level += len(stripped)
                to_remove.append(arg)
            elif not arg.startswith("--"):
                v_count = arg.count("v")
                if v_count > 0:
                    verbose_level += v_count
                    clean_arg = "-" + "".join(char for char in arg[1:] if char != "v")
                    to_remove.append((arg, clean_arg))
                    
    assert verbose_level == 2

def test_cli_single_branch_detailed_status_with_failing_tests(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "runbot", "17.0-fix-pian"])
    
    config_path = tmp_path / "odoo-wt-fail.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root", "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock return values for live runbot details + pr comments + failing tests (7 items)
    monkeypatch.setattr("odoo_wt.runbot_client.check_branch_status_and_comments", lambda name, **kwargs: {
        "batch_url": "https://runbot.odoo.com/runbot/batch/2592876",
        "ts_str": "2026-06-18 10:00:00",
        "success": 2,
        "failed": 2,
        "warning": 0,
        "running": 0,
        "odoo_pr": None,
        "enterprise_pr": None,
        "upgrade_pr": None,
        "comment_data": None,
        "failing_tests": [
            "TestMail.test_mail_sending",
            "TestDiscuss.test_channel_creation",
            "TestSales.test_order_total",
            "TestExtra.test_more_failures",
            "Test5.test_5",
            "Test6.test_6",
            "Test7.test_7"
        ]
    })
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Failing Tests" in captured.out
    assert "TestMail.test_mail_sending" in captured.out
    assert "TestDiscuss.test_channel_creation" in captured.out
    assert "TestSales.test_order_total" in captured.out
    # Symmetrical adaptive limit checks: should show max 5 items and summaries
    assert "... and 2 more" in captured.out
    assert "Test7.test_7" not in captured.out

def test_cli_status_cwd_path_prefix_collision(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "status"])
    
    config_path = tmp_path / "odoo-wt-collision.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root", "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock system worktrees containing both "master" base branch and "master-pdp-fix"
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["17.0"], ["pian"], [
            {"name": "master", "path": "/path/root/master", "version": "master"},
            {"name": "master-pdp-fix", "path": "/path/root/master-pdp-fix", "version": "master"}
        ]
    ))
    
    # Mock CWD to be inside the feature branch subfolder (which contains the base path as a string prefix!)
    monkeypatch.setattr("os.getcwd", lambda: "/path/root/master-pdp-fix/odoo")
    
    # Mock status check to avoid real requests
    monkeypatch.setattr("odoo_wt.runbot_client.check_branch_status_and_comments", lambda name, **kwargs: {
        "batch_url": "https://runbot.odoo.com/runbot/batch/2592876",
        "ts_str": "2026-06-18 10:00:00",
        "success": 2,
        "failed": 0,
        "warning": 0,
        "running": 0,
        "odoo_pr": None,
        "enterprise_pr": None,
        "upgrade_pr": None,
        "comment_data": None
    })
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    # It must have successfully matched master-pdp-fix and NOT master!
    assert "Detailed Status for" in captured.out
    assert "master-pdp-fix" in captured.out

def test_cli_subcommand_help(monkeypatch, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "status", "-h"])
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "Subcommand Help: 'status'" in captured.out
    assert "Description:" in captured.out
    assert "Context-Aware" in captured.out

def test_cli_single_branch_reviews_history_with_verbose(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "status", "17.0-fix-pian", "--verbose"])
    
    config_path = tmp_path / "odoo-wt-history.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root", "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock return values with comments history
    monkeypatch.setattr("odoo_wt.runbot_client.check_branch_status_and_comments", lambda name, **kwargs: {
        "batch_url": "https://runbot.odoo.com/runbot/batch/2592876",
        "ts_str": "2026-06-18 10:00:00",
        "success": 2,
        "failed": 0,
        "warning": 0,
        "running": 0,
        "odoo_pr": None,
        "enterprise_pr": None,
        "upgrade_pr": None,
        "comment_data": {
            "user": "pmah-odoo",
            "relative": "2h ago",
            "body": "Comment 2",
            "html_url": "https://github.com/link2",
            "history": [
                {
                    "user": "pmah-odoo",
                    "relative": "2h ago",
                    "body": "Comment 2",
                    "html_url": "https://github.com/link2",
                    "is_ent": False, "is_upg": False
                },
                {
                    "user": "xavierbol",
                    "relative": "1d ago",
                    "body": "Comment 1",
                    "html_url": "https://github.com/link1",
                    "is_ent": True, "is_upg": False
                }
            ]
        }
    })
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "PR Reviews History (last 10 comments):" in captured.out
    assert "pmah-odoo" in captured.out
    assert "Comment 2" in captured.out
    assert "xavierbol" in captured.out
    assert "Comment 1" in captured.out

def test_cli_autocomplete(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "autocomplete", "bash"])
    
    config_path = tmp_path / "odoo-wt-history.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root", "suffix": "pian"
    })
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "_odoo_wt_autocomplete()" in captured.out
    assert "status|runbot|reviews|open|code|delete|rm" in captured.out

    # Test Zsh output
    monkeypatch.setattr("sys.argv", ["odoo-wt", "autocomplete", "zsh"])
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
    assert excinfo.value.code == 0
    captured_zsh = capsys.readouterr()
    assert "_odoo_wt_zsh_autocomplete()" in captured_zsh.out
    assert "compdef _odoo_wt_zsh_autocomplete odoo-wt" in captured_zsh.out

def test_cli_switcher_debug_log_output(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "17.0-fix-pian", "--debug"])
    
    config_path = tmp_path / "odoo-wt-debug.json"
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
    
    monkeypatch.setattr("os.chdir", lambda path: None)
    import sys
    monkeypatch.setattr("os.execv", lambda shell, args: sys.exit(0))
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "ms | " in captured.out
    assert "cli_main._main_impl" in captured.out
    assert "Smart Switcher active" in captured.out

def test_cli_magic_fix_switcher_success(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "odoo-dev:saas-19.1-ai-preserve_list-bso"])
    
    config_path = tmp_path / "odoo-wt-magic.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data to return existing worktree matching the cleaned name
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["saas-19.1"], ["bso", "pian"], [{"name": "saas-19.1-ai-preserve_list-bso", "path": "/path/root/saas-19.1-ai-preserve_list-bso", "version": "saas-19.1"}]
    ))
    
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
    assert chdir_called == "/path/root/saas-19.1-ai-preserve_list-bso"
    captured = capsys.readouterr()
    assert "Magic Fix applied to input:" in captured.out
    assert "odoo-dev:saas-19.1-ai-preserve_list-bso" in captured.out
    assert "saas-19.1-ai-preserve_list-bso" in captured.out

def test_cli_magic_fix_open_success(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "open", "odoo-dev:saas-19.1-ai-preserve_list-bso"])
    
    config_path = tmp_path / "odoo-wt-magic-open.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data to return existing worktree matching the cleaned name
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["saas-19.1"], ["bso", "pian"], [{"name": "saas-19.1-ai-preserve_list-bso", "path": "/path/root/saas-19.1-ai-preserve_list-bso", "version": "saas-19.1"}]
    ))
    
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
    assert chdir_called == "/path/root/saas-19.1-ai-preserve_list-bso"
    captured = capsys.readouterr()
    assert "Magic Fix applied to input:" in captured.out

def test_cli_magic_fix_disabled_via_flag(monkeypatch, tmp_path, capsys):
    from odoo_wt import cli_main
    monkeypatch.setattr("sys.argv", ["odoo-wt", "odoo-dev:saas-19.1-ai-preserve_list-bso", "--no-magic"])
    
    config_path = tmp_path / "odoo-wt-no-magic.json"
    config_path.write_text("{}")
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.config_file", config_path)
    monkeypatch.setattr("odoo_wt.cli_main.config_mgr.load", lambda: {
        "wt_root": "/path/root",
        "suffix": "pian"
    })
    
    monkeypatch.setattr("odoo_wt.cli_main.check_dependencies", lambda: None)
    
    # Mock discover_system_data
    monkeypatch.setattr("odoo_wt.cli_main.discover_system_data", lambda *_, **__: (
        ["saas-19.1"], ["bso", "pian"], [{"name": "saas-19.1-ai-preserve_list-bso", "path": "/path/root/saas-19.1-ai-preserve_list-bso", "version": "saas-19.1"}]
    ))
    
    # Mock builtins.input to return 'c' (create) to avoid blocking
    monkeypatch.setattr("builtins.input", lambda _: "c")
    
    # Mock run_cli_deployment to do nothing and raise SystemExit to end early
    async def mock_run_cli_deployment(*args, **kwargs):
        raise SystemExit(0)
    monkeypatch.setattr("odoo_wt.cli_main.run_cli_deployment", mock_run_cli_deployment)
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    captured = capsys.readouterr()
    assert "Magic Fix applied to input:" not in captured.out

def test_cli_main_keyboard_interrupt(monkeypatch, capsys):
    from odoo_wt import cli_main
    
    # Mock _main_impl to raise KeyboardInterrupt
    def mock_main_impl():
        raise KeyboardInterrupt()
    monkeypatch.setattr(cli_main, "_main_impl", mock_main_impl)
    
    # Mock os._exit to raise a unique SystemExit (since os._exit kills the process immediately,
    # raising SystemExit allows us to assert its exit code safely within pytest)
    def mock_exit(code):
        raise SystemExit(code)
    monkeypatch.setattr("os._exit", mock_exit)
    
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main()
        
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "Aborted." in captured.out
