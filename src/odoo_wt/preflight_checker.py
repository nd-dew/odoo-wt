import shutil
import subprocess
from pathlib import Path
import os

class DiagnosticResult:
    def __init__(self, key: str, title: str, status: str, value: str, advice: str):
        self.key = key       # "git", "gh", "uv", "repos"
        self.title = title   # e.g. "Git Configuration"
        self.status = status # "ok" (green), "warn" (yellow), "error" (red)
        self.value = value   # e.g. "Installed (pian@odoo.com)" or "Missing"
        self.advice = advice # e.g. "Run git config --global user.name ..."

def run_preflight_checks(config: dict) -> list[DiagnosticResult]:
    results = []
    
    # 1. Check Git Version Control
    git_path = shutil.which("git")
    if not git_path:
        results.append(DiagnosticResult(
            "git", "Git Version Control", "error", "Missing",
            "Please install Git on your system first! (e.g., sudo apt install git)"
        ))
    else:
        try:
            name = subprocess.check_output(["git", "config", "--global", "user.name"], text=True, errors="ignore").strip()
            email = subprocess.check_output(["git", "config", "--global", "user.email"], text=True, errors="ignore").strip()
        except Exception:
            name, email = "", ""
            
        if not name or not email:
            results.append(DiagnosticResult(
                "git", "Git Configuration", "warn", "Incomplete",
                "Git user.name or user.email is missing! Run: git config --global user.name 'Your Name'"
            ))
        else:
            results.append(DiagnosticResult(
                "git", "Git Version Control", "ok", f"Ready ({email})", ""
            ))
            
    # 2. Check Astral UV
    uv_path = shutil.which("uv")
    if not uv_path:
        results.append(DiagnosticResult(
            "uv", "Astral UV Manager", "warn", "Missing",
            "Astral 'uv' is missing! We highly recommend installing it: curl -LsSf https://astral.sh/uv/install.sh | sh"
        ))
    else:
        results.append(DiagnosticResult(
            "uv", "Astral UV Manager", "ok", "Ready", ""
        ))
        
    # 3. Check GitHub CLI (gh)
    gh_path = shutil.which("gh")
    if not gh_path:
        results.append(DiagnosticResult(
            "gh", "GitHub CLI Integration", "warn", "Missing",
            "GitHub CLI 'gh' is missing! Inline PR reviews will be disabled. Run: sudo apt install gh"
        ))
    else:
        try:
            status_proc = subprocess.run(["gh", "auth", "status"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="ignore", timeout=15)
            is_authed = status_proc.returncode == 0
        except Exception:
            is_authed = False
            
        if not is_authed:
            results.append(DiagnosticResult(
                "gh", "GitHub CLI Integration", "warn", "Not Authenticated",
                "GitHub CLI is installed but not authenticated! Run: _gh auth login_"
            ))
        else:
            results.append(DiagnosticResult(
                "gh", "GitHub CLI Integration", "ok", "Authenticated", ""
            ))
            
    # 4. Check Odoo Base Repositories Clones
    wt_root_val = config.get("wt_root")
    if not wt_root_val or "Select." in str(wt_root_val) or not str(wt_root_val).strip():
        results.append(DiagnosticResult(
            "repos", "Worktree Root Path", "error", "Invalid or Empty",
            "The configured Worktree Root is empty or invalid! Run 'odoo-wt settings' to re-configure."
        ))
    else:
        wt_root = Path(wt_root_val).expanduser().absolute()
        comm_dir = config.get("community_dir", "odoo")
        ent_dir = config.get("enterprise_dir", "enterprise")
        
        base_odoo = wt_root / "master" / comm_dir
        base_ent = wt_root / "master" / ent_dir
        
        missing_repos = []
        if not base_odoo.exists() or not (base_odoo / ".git").exists():
            missing_repos.append(comm_dir)
        if not base_ent.exists() or not (base_ent / ".git").exists():
            missing_repos.append(ent_dir)
            
        if missing_repos:
            advice_lines = []
            if comm_dir in missing_repos:
                advice_lines.append(f"git clone --depth 1 https://github.com/odoo/odoo.git {wt_root}/master/{comm_dir}")
            if ent_dir in missing_repos:
                advice_lines.append(f"git clone --depth 1 https://github.com/odoo/enterprise.git {wt_root}/master/{ent_dir}")
                
            advice = (
                f"Base clones for {', '.join(missing_repos)} are missing inside {wt_root}/master/!\n"
                f"       -> Please run:\n          " + "\n          ".join(advice_lines)
            )
            results.append(DiagnosticResult(
                "repos", "Odoo Base Repositories", "error", f"Missing {', '.join(missing_repos)}",
                advice
            ))
        else:
            results.append(DiagnosticResult(
                "repos", "Odoo Base Repositories", "ok", "Found & Valid", ""
            ))
            
    return results
