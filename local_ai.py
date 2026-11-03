"""Talk to the AI model (the 'brain') chosen in ai_settings.json.

Shared by write_application.py (cover letters, competency answers) and
tailor_cv.py (CV rewording). To change brain, edit "active" in ai_settings.json,
or set the AI_PROFILE environment variable for one run. Two API styles are
supported, which covers LM Studio and most cloud services:
  openai     - LM Studio, and any service with an OpenAI-compatible chat API
  anthropic  - Anthropic's Claude API
API keys are read from environment variables, never from files in this project.
The safety checks in the other scripts run the same way whichever brain is used.
"""
import json
import os
from pathlib import Path

import requests

SETTINGS = Path("ai_settings.json")
_warned = False


def load_profile():
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    name = os.environ.get("AI_PROFILE") or settings["active"]
    if name not in settings["profiles"]:
        raise SystemExit(f"AI profile '{name}' not found in {SETTINGS}. "
                         f"Choose one of: {', '.join(settings['profiles'])}")
    profile = dict(settings["profiles"][name], name=name)
    profile["temperature"] = settings.get("temperature", 0.3)
    return profile


def describe():
    p = load_profile()
    return f"{p['model']} ({p['name']}: {p['description']})"


def _api_key(profile):
    var = profile.get("api_key_env")
    if not var:
        return ""
    key = os.environ.get(var, "")
    if not key:
        raise SystemExit(f"Profile '{profile['name']}' needs an API key in the environment variable {var}.\n"
                         "See README > Choosing the AI model, or switch back to the 'local' profile.")
    return key


def ask_model(prompt, max_tokens=1500):
    """Send one prompt to the active brain and return its reply as text."""
    global _warned
    profile = load_profile()
    key = _api_key(profile)
    if profile.get("sends_data_off_device") and not _warned:
        print(f"  Note: profile '{profile['name']}' sends your CV evidence to an outside service.")
        _warned = True

    if profile["format"] == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = {"model": profile["model"], "max_tokens": max_tokens, "temperature": profile["temperature"],
                "messages": [{"role": "user", "content": prompt}]}
    else:  # openai-style: LM Studio and OpenAI-compatible services
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        # All instructions go in the user message: some models (e.g. Gemma) have no 'system' role
        body = {"model": profile["model"], "messages": [{"role": "user", "content": prompt}],
                "temperature": profile["temperature"], "max_tokens": max_tokens}
    try:
        response = requests.post(profile["url"], json=body, headers=headers, timeout=600)
        response.raise_for_status()
    except requests.RequestException as error:
        detail = getattr(error.response, "text", "")[:300] if getattr(error, "response", None) is not None else ""
        raise SystemExit(f"Could not get a reply from '{profile['name']}' at {profile['url']}.\n{error}\n{detail}")
    data = response.json()
    if profile["format"] == "anthropic":
        return "".join(part.get("text", "") for part in data["content"]).strip()
    return data["choices"][0]["message"]["content"].strip()
