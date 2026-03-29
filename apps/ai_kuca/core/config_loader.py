import os
import yaml


class ConfigLoader:
    """Simple YAML config loader for ai_kuca modules."""

    def __init__(self, app, root_dir=None):
        self.app = app
        self.root_dir = root_dir or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.config_dir = os.path.join(self.root_dir, "config")

    def path(self, filename):
        return os.path.abspath(os.path.join(self.config_dir, filename))

    def load_yaml(self, filename):
        path = self.path(filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def save_yaml(self, filename, data):
        path = self.path(filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)

    @staticmethod
    def env(name, default=None):
        return os.getenv(name, default)
