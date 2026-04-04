import json
import datetime
import os
import shutil
from pathlib import Path

# --- DEFAULT LOCATIONS ---
DEFAULT_CONFIG_FILE = Path.home() / ".config" / "odoo-wt.json"
DEFAULT_LOG_FILE = Path.home() / ".config" / "odoo-wt-logs.jsonl"
MAX_LOG_LINES = 1000

# These are the current active paths (globals used by the rest of the app)
CONFIG_FILE = DEFAULT_CONFIG_FILE
LOG_FILE = DEFAULT_LOG_FILE

def append_log(action: str, details: dict = None):
    if details is None: details = {}
    entry = {"timestamp": datetime.datetime.now().isoformat(), "action": action, "details": details}
    try:
        # Ensure parent directory exists before writing
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # 1. Read existing lines
        lines = []
        if LOG_FILE.exists():
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()
        
        # 2. Append new entry and limit to 1000
        lines.append(json.dumps(entry) + "\n")
        if len(lines) > MAX_LOG_LINES:
            lines = lines[-MAX_LOG_LINES:]
            
        # 3. Write back
        with open(LOG_FILE, "w") as f:
            f.writelines(lines)
    except (OSError, IOError):
        pass

def load_config():
    global CONFIG_FILE, LOG_FILE
    
    default_config = {
        "wt_root": str(Path.home() / "repos" / "Odoo" / "wt"),
        "env_root": str(Path.home() / ".envs"),
        "suffix": "pian",
        "remote_name": "odoo-dev",
        "community_dir": "odoo",
        "enterprise_dir": "enterprise",
        "default_tab": "tab-create",
        "ignored_versions": [],
        "ignored_suffixes": [],
        "config_path": str(DEFAULT_CONFIG_FILE),
        "log_path": str(DEFAULT_LOG_FILE),
        "show_prefix": True,
        "show_suffix": True
    }

    # 1. First load from the primary/default location
    if DEFAULT_CONFIG_FILE.exists():
        try:
            with open(DEFAULT_CONFIG_FILE, "r") as f:
                data = json.load(f)
                default_config.update(data)
        except (OSError, IOError, json.JSONDecodeError):
            pass

    # 2. Update globals based on loaded config
    CONFIG_FILE = Path(default_config["config_path"]).expanduser().absolute()
    LOG_FILE = Path(default_config["log_path"]).expanduser().absolute()

    # 3. If the user specified a custom config path that isn't the default, 
    # and that custom file exists, load FROM THERE instead (it takes precedence)
    if CONFIG_FILE != DEFAULT_CONFIG_FILE.absolute() and CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                default_config.update(data)
        except (OSError, IOError, json.JSONDecodeError):
            pass

    return default_config

def save_config(config):
    global CONFIG_FILE, LOG_FILE
    
    raw_config_path = str(config.get("config_path", "")).strip()
    raw_log_path = str(config.get("log_path", "")).strip()
    
    if not raw_config_path:
        raw_config_path = str(DEFAULT_CONFIG_FILE)
    if not raw_log_path:
        raw_log_path = str(DEFAULT_LOG_FILE)
        
    new_config_path = Path(raw_config_path).expanduser().absolute()
    new_log_path = Path(raw_log_path).expanduser().absolute()
    
    # Prevent saving directly to a directory
    if new_config_path.is_dir():
        new_config_path = new_config_path / "odoo-wt.json"
    if new_log_path.is_dir():
        new_log_path = new_log_path / "odoo-wt-logs.jsonl"

    # Handle Log File Migration
    if new_log_path != LOG_FILE and LOG_FILE.exists():
        try:
            new_log_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(LOG_FILE), str(new_log_path))
            append_log("Log file migrated", {"old": str(LOG_FILE), "new": str(new_log_path)})
        except Exception as e:
            append_log("Failed to move log file", {"error": str(e)})

    # Handle Config File Migration
    # We always keep a copy or a pointer at DEFAULT_CONFIG_FILE so the app can find it next time
    if new_config_path != CONFIG_FILE:
        try:
            new_config_path.parent.mkdir(parents=True, exist_ok=True)
            # If the old custom config file exists, move it to the new one
            if CONFIG_FILE.exists():
                shutil.move(str(CONFIG_FILE), str(new_config_path))
            
            # Update the pointer in the default location so we know where to look next boot
            DEFAULT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(DEFAULT_CONFIG_FILE, "w") as f:
                json.dump({"config_path": str(new_config_path), "log_path": str(new_log_path)}, f, indent=4)
                
            append_log("Config file migrated", {"old": str(CONFIG_FILE), "new": str(new_config_path)})
        except Exception as e:
            append_log("Failed to move config file", {"error": str(e)})

    # Update active globals
    CONFIG_FILE = new_config_path
    LOG_FILE = new_log_path

    # Final save to the active config file
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)
