"""Cấu hình cục bộ: API key và model, lưu trong data/config.json (chỉ trên máy bạn)."""
import json
import os

from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULT_MODEL = "gemini-3.6-flash"

os.makedirs(DATA_DIR, exist_ok=True)


def load_config(overrides=None):
    if not os.path.exists(CONFIG_PATH):
        cfg = {
            "api_key": os.environ.get("GOOGLE_API_KEY", ""),
            "model": DEFAULT_MODEL,
            "provider": "auto",
            "openai_api_key": os.environ.get("OPENAI_API_KEY", ""),
            "openai_model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", ""),
            "openrouter_model": os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
            "openrouter_vision_model": os.environ.get("OPENROUTER_VISION_MODEL", "google/gemini-2.0-flash-001"),
            "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
            "anthropic_model": os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
            "github_token": os.environ.get("GITHUB_TOKEN", ""),
        }
    else:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("model", DEFAULT_MODEL)
        cfg.setdefault("provider", "auto")
        cfg.setdefault("openai_api_key", os.environ.get("OPENAI_API_KEY", ""))
        cfg.setdefault("openai_model", os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
        cfg.setdefault("openrouter_api_key", os.environ.get("OPENROUTER_API_KEY", ""))
        cfg.setdefault("openrouter_model", os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"))
        cfg.setdefault("openrouter_vision_model", os.environ.get("OPENROUTER_VISION_MODEL", "google/gemini-2.0-flash-001"))
        cfg.setdefault("anthropic_api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
        cfg.setdefault("anthropic_model", os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"))
        cfg.setdefault("github_token", os.environ.get("GITHUB_TOKEN", ""))
        if not cfg.get("api_key"):
            cfg["api_key"] = os.environ.get("GOOGLE_API_KEY", "")

    if overrides:
        for key, value in overrides.items():
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
            cfg[key] = value
    return cfg


def save_config(api_key=None, model=None, provider=None, openai_api_key=None, openai_model=None,
                openrouter_api_key=None, openrouter_model=None, anthropic_api_key=None,
                anthropic_model=None, github_token=None):
    cfg = load_config()
    if api_key is not None:
        cfg["api_key"] = api_key
    if model is not None:
        cfg["model"] = model
    if provider is not None:
        cfg["provider"] = provider
    if openai_api_key is not None:
        cfg["openai_api_key"] = openai_api_key
    if openai_model is not None:
        cfg["openai_model"] = openai_model
    if openrouter_api_key is not None:
        cfg["openrouter_api_key"] = openrouter_api_key
    if openrouter_model is not None:
        cfg["openrouter_model"] = openrouter_model
    if anthropic_api_key is not None:
        cfg["anthropic_api_key"] = anthropic_api_key
    if anthropic_model is not None:
        cfg["anthropic_model"] = anthropic_model
    if github_token is not None:
        cfg["github_token"] = github_token
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return cfg
