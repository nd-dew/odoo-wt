import json
import datetime
import os
from pathlib import Path

# --- CONFIGURATION ---
CONFIG_FILE = Path.home() / ".config" / "odoo-wt.json"
LOG_FILE = Path.home() / ".config" / "odoo-wt-logs.jsonl"

def append_log(action: str, details: dict = None):
    if details is None: details = {}
    entry = {"timestamp": datetime.datetime.now().isoformat(), "action": action, "details": details}
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except: pass

def load_config():
    default_config = {
        "wt_root": str(Path.home() / "repos" / "Odoo" / "wt"),
        "env_root": str(Path.home() / ".envs"),
        "suffix": "pian",
        "remote_name": "odoo-dev"
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                default_config.update(json.load(f))
        except:
            pass
    return default_config

def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
