"""Safe subprocess wrapper around the vendored macOS WeChat bridge."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import wechat_gui

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "wechat-cli.mjs"

def run(action: str, chat: str = "", text: str = "", timeout: int = 30) -> dict:
    cmd = ["node", str(CLI), action]
    if chat: cmd += ["--chat", chat]
    if text: cmd += ["--text", text]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "WECHAT_TIMEOUT", "detail": f"{action} 超时"}
    raw = (p.stdout or p.stderr).strip()
    try:
        result = json.loads(raw.splitlines()[-1])
    except Exception:
        result = {"ok": False, "error": "WECHAT_BRIDGE_BAD_OUTPUT", "detail": raw[-500:]}
    if p.returncode and result.get("ok") is not False:
        result = {"ok": False, "error": "WECHAT_BRIDGE_FAILED", "detail": raw[-500:]}
    return result

def status() -> dict:
    return run("status", timeout=10)

def prepare(chat: str, text: str) -> dict:
    # This WeChat build hides its Accessibility tree; use the exact-title OCR path only.
    return wechat_gui.prepare(chat, text)

def send(chat: str, text: str) -> dict:
    # Never cascade from an ambiguous native failure into a second send attempt.
    return wechat_gui.send(chat, text)

def read(chat: str) -> dict:
    return run("read", chat, timeout=25)
