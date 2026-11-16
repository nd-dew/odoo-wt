import asyncio
import subprocess
from pathlib import Path

import pytest

from odoo_wt import incomplete_worktrees as iw


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def wt_root(tmp_path):
    root = tmp_path / "wt"
    for sub in ("odoo", "enterprise"):
        repo = root / "master" / sub
        repo.mkdir(parents=True)
        _git("init", "-q", "-b", "master", cwd=repo)
        _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    return root


@pytest.fixture
def config(wt_root):
    return {"wt_root": str(wt_root), "community_dir": "odoo", "enterprise_dir": "enterprise"}


def _make_worktree(wt_root, name):
    target = wt_root / name
    for sub in ("odoo", "enterprise"):
        _git("worktree", "add", "-q", "-b", name, str(target / sub), cwd=wt_root / "master" / sub)
    return target


def test_master_and_complete_worktrees_are_not_reported(wt_root, config):
    _make_worktree(wt_root, "master-feature-pian")
    assert iw.find_incomplete_worktrees(config) == []


def test_marker_flags_folder_even_with_valid_worktrees(wt_root, config):
    target = _make_worktree(wt_root, "master-feature-pian")
    iw.mark_started(target)
    assert iw.find_incomplete_worktrees(config) == [target]
    iw.mark_finished(target)
    assert iw.find_incomplete_worktrees(config) == []


def test_legacy_leftover_with_only_generated_files_is_reported(wt_root, config, tmp_path):
    leftover = wt_root / "iso"
    leftover.mkdir()
    (leftover / ".venv").symlink_to(tmp_path)
    (leftover / ".vscode").mkdir()
    (leftover / "run").write_text("#!/bin/bash\n")
    assert iw.find_incomplete_worktrees(config) == [leftover]


@pytest.mark.parametrize("extra", ["notes.md", "Dockerfile"])
def test_folders_with_user_files_are_never_reported(wt_root, config, extra):
    folder = wt_root / "my_stuff"
    folder.mkdir()
    (folder / extra).write_text("keep me")
    assert iw.find_incomplete_worktrees(config) == []


def test_real_venv_or_non_empty_repo_dir_is_never_reported(wt_root, config):
    a = wt_root / "a"
    (a / ".venv").mkdir(parents=True)
    b = wt_root / "b"
    (b / "odoo").mkdir(parents=True)
    (b / "odoo" / "file.py").write_text("x")
    assert iw.find_incomplete_worktrees(config) == []


def test_remove_unregisters_git_worktrees_and_deletes_folder(wt_root, config):
    target = _make_worktree(wt_root, "master-feature-pian")
    iw.mark_started(target)
    iw.remove_worktree_folder(target, config)
    assert not target.exists()
    out = subprocess.run(["git", "worktree", "list"], cwd=wt_root / "master" / "odoo",
                         capture_output=True, text=True).stdout
    assert "master-feature-pian" not in out


def test_remove_refuses_master(wt_root, config):
    with pytest.raises(ValueError):
        iw.remove_worktree_folder(wt_root / "master", config)
    assert (wt_root / "master").exists()


def _engine_stub(monkeypatch, wt_root, fail_with):
    from odoo_wt import deployment_engine

    class FakeEngine:
        def __init__(self, config, data):
            self.config = config
            self.wt_root = wt_root
            self.target_dir = wt_root / "iso"
            self.comm_dir, self.ent_dir = "odoo", "enterprise"
            self.has_errors = False

        async def deploy_repo(self, repo, dest, category):
            (self.target_dir / dest).mkdir(parents=True, exist_ok=True)
            if fail_with:
                raise fail_with
            yield  # pragma: no cover

        async def setup_uv(self):
            return
            yield  # pragma: no cover

        async def setup_vscode(self):
            pass

    monkeypatch.setattr(deployment_engine, "DeployEngine", FakeEngine)


def test_cli_deploy_rolls_back_folder_it_created_on_interrupt(monkeypatch, wt_root, config):
    from odoo_wt.cli_main import run_cli_deployment
    _engine_stub(monkeypatch, wt_root, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(run_cli_deployment(config, {"version": "", "desc": "iso", "suffix": ""}))
    assert not (wt_root / "iso").exists()


def test_cli_deploy_never_deletes_pre_existing_folder(monkeypatch, wt_root, config):
    from odoo_wt.cli_main import run_cli_deployment
    existing = wt_root / "iso"
    existing.mkdir()
    (existing / "precious.md").write_text("keep")
    _engine_stub(monkeypatch, wt_root, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(run_cli_deployment(config, {"version": "", "desc": "iso", "suffix": ""}))
    assert (existing / "precious.md").exists()


def test_parse_selection():
    from odoo_wt.cli_main import _parse_selection
    assert _parse_selection("1,3-4", 5) == [0, 2, 3]
    assert _parse_selection(" 2 ", 3) == [1]
    assert _parse_selection("4-2", 5) == [1, 2, 3]
    assert _parse_selection("0", 3) is None
    assert _parse_selection("6", 5) is None
    assert _parse_selection("x", 5) is None


def _leftover(wt_root, name):
    p = wt_root / name
    (p / ".vscode").mkdir(parents=True)
    return p


def _run_prune(monkeypatch, config, args, answers):
    from odoo_wt import cli_main
    saved = []
    monkeypatch.setattr(cli_main.config_mgr, "save", lambda c: saved.append(dict(c)))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))
    cli_main.run_prune_command(config, args)
    return saved


def test_prune_deletes_only_selected(monkeypatch, wt_root, config):
    a, b, c = (_leftover(wt_root, n) for n in ("a", "b", "c"))
    _run_prune(monkeypatch, config, [], ["1,3"])
    assert not a.exists() and b.exists() and not c.exists()


def test_prune_keep_never_flags_again(monkeypatch, wt_root, config):
    a, b = _leftover(wt_root, "a"), _leftover(wt_root, "b")
    saved = _run_prune(monkeypatch, config, [], ["k 1", ""])
    assert a.exists() and b.exists()
    assert saved[-1]["prune_ignore"] == ["a"]
    assert [p.name for p in iw.find_incomplete_worktrees(config)] == ["b"]


def test_prune_by_name_only_considers_those(monkeypatch, wt_root, config):
    a, b = _leftover(wt_root, "a"), _leftover(wt_root, "b")
    _run_prune(monkeypatch, config, ["b"], ["a"])
    assert a.exists() and not b.exists()
