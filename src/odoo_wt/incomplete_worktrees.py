"""Detection, rollback and pruning of half-made worktree folders.

A deployment writes MARKER_NAME into the target folder before doing anything else and
removes it only once everything succeeded, so a folder still holding the marker is a
deployment that never finished (Ctrl-C, crash, killed terminal...).

Folders created before the marker existed are recognised heuristically: no valid git
worktree link in the community/enterprise subfolders and nothing inside except what
odoo-wt itself generates. Anything containing user files is never reported.
"""
import shutil
import subprocess
from pathlib import Path

from .system_discovery import is_deletion_protected

MARKER_NAME = ".odoo-wt-incomplete"

# Entries odoo-wt generates itself inside a worktree folder
_GENERATED_ENTRIES = {MARKER_NAME, ".venv", ".vscode", "run", "odoo.log"}


def _repo_dirs(config):
    return (
        config.get("community_dir", "odoo"),
        config.get("enterprise_dir", "enterprise"),
        config.get("upgrade_dir", "upgrade"),
    )


def _has_valid_worktree_link(sub_path: Path) -> bool:
    git_file = sub_path / ".git"
    if not git_file.is_file():
        return False
    try:
        content = git_file.read_text().strip()
    except OSError:
        return False
    if not content.startswith("gitdir:"):
        return False
    return Path(content[len("gitdir:"):].strip()).exists()


def is_incomplete_worktree(path, config) -> bool:
    path = Path(path)
    if not path.is_dir() or path.is_symlink() or path.name.startswith("."):
        return False
    if is_deletion_protected(path):
        return False
    if (path / MARKER_NAME).exists():
        return True

    comm_dir, ent_dir, upg_dir = _repo_dirs(config)
    if _has_valid_worktree_link(path / comm_dir) or _has_valid_worktree_link(path / ent_dir):
        return False

    try:
        entries = list(path.iterdir())
    except OSError:
        return False
    allowed = _GENERATED_ENTRIES | {comm_dir, ent_dir, upg_dir}
    for entry in entries:
        if entry.name not in allowed:
            return False
        # A real (non-symlinked) virtualenv was made by the user, not by odoo-wt
        if entry.name == ".venv" and not entry.is_symlink():
            return False
        # A repo subfolder without a git link but with content could be user work
        if entry.name in (comm_dir, ent_dir, upg_dir) and entry.is_dir() and not _has_valid_worktree_link(entry):
            try:
                if any(entry.iterdir()):
                    return False
            except OSError:
                return False
    return True


def find_incomplete_worktrees(config) -> list:
    wt_root = Path(config.get("wt_root", "~/repos/Odoo/wt")).expanduser().absolute()
    if not wt_root.is_dir():
        return []
    try:
        candidates = sorted(wt_root.iterdir())
    except OSError:
        return []
    kept = set(config.get("prune_ignore", []))
    return [p for p in candidates if p.name not in kept and is_incomplete_worktree(p, config)]


def remove_worktree_folder(path, config) -> None:
    """Unregister the folder's git worktrees from the master repos, prune, then delete it."""
    path = Path(path)
    if is_deletion_protected(path):
        raise ValueError(f"Refusing to delete protected worktree '{path.name}'")
    wt_root = path.parent
    for sub in _repo_dirs(config):
        base_repo = wt_root / "master" / sub
        if not base_repo.exists():
            continue
        if (path / sub).exists():
            subprocess.run(
                ["git", "worktree", "remove", "-f", "-f", str(path / sub)],
                cwd=base_repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        subprocess.run(["git", "worktree", "prune"], cwd=base_repo,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def mark_started(path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)
    (Path(path) / MARKER_NAME).touch()


def mark_finished(path) -> None:
    try:
        (Path(path) / MARKER_NAME).unlink()
    except FileNotFoundError:
        pass


def incomplete_hint(config):
    """One-line hint naming leftover folders, or None when there are none."""
    leftovers = find_incomplete_worktrees(config)
    if not leftovers:
        return None
    names = ", ".join(p.name for p in leftovers[:3]) + (", ..." if len(leftovers) > 3 else "")
    plural = "s" if len(leftovers) > 1 else ""
    return f"⚠ {len(leftovers)} half-made worktree{plural} ({names}) — run 'odoo-wt prune' to clean up"
