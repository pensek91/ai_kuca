import os
import yaml


class ConfigLoader:
    """Simple YAML config loader for ai_kuca modules."""

    def __init__(self, app, root_dir=None):
        self.app = app
        self.root_dir = root_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.config_dir = os.path.join(self.root_dir, "config")

    def path(self, filename):
        candidate = os.path.abspath(os.path.join(self.config_dir, filename))
        config_root = os.path.abspath(self.config_dir)
        if not (candidate == config_root or candidate.startswith(config_root + os.sep)):
            raise ValueError(f"Invalid config path outside config dir: {filename}")
        return candidate

    def load_yaml(self, filename, default=None):
        path = self.path(filename)
        if default is None:
            default = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            self._log(f"Config file missing: {path}", level="WARNING")
            return default
        except yaml.YAMLError as ex:
            self._log(f"YAML parse error in {path}: {ex}", level="ERROR")
            return default
        except Exception as ex:
            self._log(f"Failed to load config {path}: {ex}", level="ERROR")
            return default

    def save_yaml(self, filename, data):
        path = self.path(filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

    def _log(self, message, level="INFO"):
        try:
            self.app.log(f"[CONFIG] {message}", level=level)
        except Exception:
            pass

    @staticmethod
    def env(name, default=None):
        return os.getenv(name, default)
