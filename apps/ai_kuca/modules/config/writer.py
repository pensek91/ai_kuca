import yaml


def write_yaml_file(path, yaml_text):
    """Validate and persist YAML text."""
    data = yaml.safe_load(yaml_text) or {}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    return True
