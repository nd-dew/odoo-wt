import json
import datetime
import os
import shutil
from pathlib import Path

DEFAULT_CONFIG_FILE = Path.home() / ".config" / "odoo-wt.json"
DEFAULT_LOG_FILE = Path.home() / ".config" / "odoo-wt-logs.jsonl"
MAX_LOG_LINES = 1000

class ConfigManager:
    def __init__(self):
        self.config_file = DEFAULT_CONFIG_FILE
        self.log_file = DEFAULT_LOG_FILE
        self.config = self._get_defaults()

    def _get_defaults(self):
        return {
            "wt_root": str(Path.home() / "repos" / "Odoo" / "wt"),
            "env_root": str(Path.home() / ".envs"),
            "suffix": "pian",
            "remote_name": "odoo-dev",
            "community_dir": "odoo",
            "enterprise_dir": "enterprise",
            "python_version": "3.12",
            "default_tab": "tab-create",
            "ignored_versions": [],
            "ignored_suffixes": [],
            "config_path": str(DEFAULT_CONFIG_FILE),
            "log_path": str(DEFAULT_LOG_FILE),
            "show_prefix": True,
            "show_suffix": True
        }

    def append_log(self, action: str, details: dict = None):
        if details is None: details = {}
        entry = {"timestamp": datetime.datetime.now().isoformat(), "action": action, "details": details}
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            lines = []
            if self.log_file.exists():
                with open(self.log_file, "r") as f:
                    lines = f.readlines()
            
            lines.append(json.dumps(entry) + "\n")
            if len(lines) > MAX_LOG_LINES:
                lines = lines[-MAX_LOG_LINES:]
                
            with open(self.log_file, "w") as f:
                f.writelines(lines)
        except (OSError, IOError):
            pass

    def load(self):
        # 1. Load from default location first to find pointer to custom config
        if DEFAULT_CONFIG_FILE.exists():
            try:
                with open(DEFAULT_CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    self.config.update(data)
            except (OSError, IOError, json.JSONDecodeError):
                pass

        # 2. Update active paths
        self.config_file = Path(self.config["config_path"]).expanduser().absolute()
        self.log_file = Path(self.config["log_path"]).expanduser().absolute()

        # 3. Load from custom location if it exists and is different
        if self.config_file != DEFAULT_CONFIG_FILE.absolute() and self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    self.config.update(data)
            except (OSError, IOError, json.JSONDecodeError):
                pass
        return self.config

    def save(self, new_config):
        raw_config_path = str(new_config.get("config_path", "")).strip() or str(DEFAULT_CONFIG_FILE)
        raw_log_path = str(new_config.get("log_path", "")).strip() or str(DEFAULT_LOG_FILE)
        
        new_config_path = Path(raw_config_path).expanduser().absolute()
        new_log_path = Path(raw_log_path).expanduser().absolute()
        
        if new_config_path.is_dir(): new_config_path = new_config_path / "odoo-wt.json"
        if new_log_path.is_dir(): new_log_path = new_log_path / "odoo-wt-logs.jsonl"

        # Handle Migrations
        if new_log_path != self.log_file and self.log_file.exists():
            try:
                new_log_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(self.log_file), str(new_log_path))
            except Exception: pass

        if new_config_path != self.config_file:
            try:
                new_config_path.parent.mkdir(parents=True, exist_ok=True)
                if self.config_file.exists():
                    shutil.move(str(self.config_file), str(new_config_path))
                
                # Update pointer
                DEFAULT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(DEFAULT_CONFIG_FILE, "w") as f:
                    json.dump({"config_path": str(new_config_path), "log_path": str(new_log_path)}, f, indent=4)
            except Exception: pass

        self.config_file = new_config_path
        self.log_file = new_log_path
        self.config = new_config
        
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

# Global Instance
config_mgr = ConfigManager()
