"""Read the search settings from app_settings.json (the app's sliders write to the same file).

If the file or a setting is missing, the default given in the script is used,
so every script still runs on its own.
"""
import json
from pathlib import Path

SETTINGS_FILE = Path("app_settings.json")


def load():
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}


def setting(name, default):
    return load().get(name, default)


def save(values):
    current = load()
    current.update(values)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
