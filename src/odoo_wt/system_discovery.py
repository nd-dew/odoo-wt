import os
import subprocess
from pathlib import Path

def shorten_path(path_str):
    home = str(Path.home())
    if path_str.startswith(home):
        return path_str.replace(home, "~", 1)
    return path_str

def expand_path(path_str):
    if path_str.startswith("~/"):
        return str(Path.home() / path_str[2:])
    return path_str

def fast_scan():
    home = Path.home()
    found_roots = []
    
    # Strategy 1: Check highly likely paths first (Fastest)
    likely_dirs = ["repos", "Projects", "src", "workspace", "Documents/repos"]
    for d in likely_dirs:
        p = home / d
        if p.exists() and p.is_dir():
            if _check_is_root_container(p):
                found_roots.append(str(p))

    # Strategy 2: If nothing found, do a shallow walk (max depth 3)
    if not found_roots:
        ignore = {".cache", ".local", ".cargo", ".rustup", ".npm", ".mozilla", ".config", "node_modules", ".vscode", "Library"}
        for entry in home.iterdir():
            if entry.is_dir() and not entry.name.startswith(".") and entry.name not in ignore:
                if _check_is_root_container(entry):
                    found_roots.append(str(entry))
    
    return [shorten_path(p) for p in found_roots]

def _check_is_root_container(path: Path):
    """Checks if a directory contains any folder with an odoo/.git subfolder."""
    try:
        for sub in path.iterdir():
            if sub.is_dir() and (sub / "odoo" / ".git").exists():
                return True
    except OSError:
        pass
    return False

def parse_branch_name(name):
    if name.startswith("saas-"):
        parts = name.split("-")
        v = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else name
    else:
        v = name.split("-")[0]
    s = ""
    if "-" in name:
        s_candidate = name.rsplit("-", 1)[-1]
        if s_candidate and len(s_candidate) <= 12 and " " not in s_candidate:
            s = s_candidate
    return v, s

def discover_system_data(wt_root, default_suffix):
    versions = set()
    suffixes = set([default_suffix, "test", "none"])
    worktrees = []
    wt_path = Path(wt_root).expanduser().absolute()
    if wt_path.exists():
        try:
            for entry in wt_path.iterdir():
                if entry.is_dir() and not entry.name.startswith("."):
                    v, s = parse_branch_name(entry.name)
                    is_wt = (entry / "odoo" / ".git").exists()
                    if is_wt:
                        worktrees.append({"name": entry.name, "path": str(entry), "version": v, "suffix": s})
                    if v == "master" or v.startswith("saas-") or (v and v[0].isdigit()):
                        versions.add(v)
                    if s: suffixes.add(s)
        except OSError: pass

    v_list = sorted(list(versions))
    if "master" in v_list: v_list.remove("master")
    v_list.insert(0, "master")
    v_list.append("none")
    v_list.append("custom...")
    
    s_list = sorted(list(suffixes))
    if default_suffix in s_list: s_list.remove(default_suffix)
    if "none" in s_list: s_list.remove("none")
    s_list.insert(0, default_suffix)
    s_list.append("none")
    s_list.append("custom...")
    return v_list, s_list, worktrees

def run_git(args, cwd=None, capture=False):
    cmd = ["git"] + args
    if capture:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        return res.returncode == 0, res.stdout
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

def check_remote(repo, branch, dev_remote):
    success, out = run_git(["ls-remote", "--heads", dev_remote, branch], cwd=repo, capture=True)
    return success and f"refs/heads/{branch}" in out

def check_local(repo, branch):
    return run_git(["rev-parse", "--verify", branch], cwd=repo)

def get_remote(repo):
    success, out = run_git(["remote"], cwd=repo, capture=True)
    return "odoo" if (success and "odoo\n" in out) else "origin"
