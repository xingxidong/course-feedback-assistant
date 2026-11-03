"""Fallback WeChat GUI automation for WeChat builds with a hidden AX tree."""
from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "data" / "bin"
CLICK = BIN / "cgevent-click"
OCR = BIN / "vision-ocr"

SEARCH_MENU_SCRIPT = r'''
tell application "System Events"
 tell process "WeChat"
  repeat with mb in menu bar items of menu bar 1
   try
    repeat with mi in menu items of menu 1 of mb
     if name of mi is "搜索" then
      click mi
      return "clicked"
     end if
    end repeat
   end try
  end repeat
 end tell
end tell
'''

def _run(cmd, *, timeout=20, input_text=None):
    return subprocess.run(cmd, input=input_text, capture_output=True, text=True, timeout=timeout)

def _build_helpers() -> None:
    BIN.mkdir(parents=True, exist_ok=True)
    sources = [(ROOT / "scripts" / "cgevent-click.swift", CLICK), (ROOT / "scripts" / "vision-ocr.swift", OCR)]
    for source, target in sources:
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            continue
        p = _run(["/usr/bin/swiftc", str(source), "-o", str(target)], timeout=120)
        if p.returncode:
            raise RuntimeError("辅助程序编译失败：" + p.stderr[-300:])

def _osascript(script: str, timeout=15) -> str:
    p = _run(["/usr/bin/osascript", "-e", script], timeout=timeout)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "AppleScript执行失败")
    return p.stdout.strip()

def _clipboard_set(text: str) -> None:
    p = _run(["/usr/bin/pbcopy"], input_text=text)
    if p.returncode: raise RuntimeError("无法写入剪贴板")

def _clipboard_get() -> str:
    return _run(["/usr/bin/pbpaste"]).stdout

def _keys(lines: list[str]) -> None:
    body = "\n".join(lines)
    _osascript(f'tell application "System Events"\n{body}\nend tell')

def _window_bounds() -> tuple[int, int, int, int]:
    raw = _osascript('tell application "System Events" to tell process "WeChat" to return {position of window 1, size of window 1}')
    nums = [int(x) for x in re.findall(r"-?\d+", raw)]
    if len(nums) < 4: raise RuntimeError("无法读取微信窗口位置")
    return nums[0], nums[1], nums[2], nums[3]

def _ensure_window() -> None:
    _osascript('tell application "WeChat" to reopen\ntell application "WeChat" to activate')
    time.sleep(0.5)
    _window_bounds()

def _normalize_title(value: str) -> str:
    value = re.sub(r"\s*[（(]\s*\d+\s*[)）]\s*$", "", value.strip())
    return re.sub(r"[^\w\u3400-\u9fff]", "", value).lower()

def _ocr_region(x: int, y: int, w: int, h: int, name: str) -> list[str]:
    image = Path("/tmp") / f"wechat-feedback-{name}.png"
    p = _run(["/usr/sbin/screencapture", "-x", "-R", f"{x},{y},{w},{h}", str(image)], timeout=20)
    if p.returncode: raise RuntimeError("无法截取微信窗口")
    p = _run([str(OCR), str(image)], timeout=45)
    if p.returncode: raise RuntimeError("微信标题识别失败")
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]

def _open_verified_chat(chat: str) -> dict:
    _ensure_window(); _build_helpers()
    _clipboard_set(chat)
    _osascript(SEARCH_MENU_SCRIPT)
    time.sleep(0.25)
    _keys(['keystroke "a" using command down', 'keystroke "v" using command down'])
    time.sleep(0.8)
    # Return opens WeChat's first local exact match; title OCR below is authoritative.
    _keys(['key code 36'])
    time.sleep(0.9)
    x, y, w, h = _window_bounds()
    # Main chat header lies between the left conversation list and any optional right-side panel.
    header_lines = _ocr_region(x + int(w * 0.15), y, int(w * 0.48), min(110, h), "header")
    wanted = _normalize_title(chat)
    matched = any(wanted == _normalize_title(line) or wanted in _normalize_title(line) for line in header_lines)
    if not matched:
        raise RuntimeError(f"未能核验微信会话“{chat}”，已停止写入")
    return {"chat": chat, "header": header_lines, "bounds": [x, y, w, h]}

def _focus_input(bounds: list[int]) -> None:
    x, y, w, h = bounds
    point_x = x + int(w * 0.43)
    point_y = y + int(h * 0.88)
    p = _run([str(CLICK), str(point_x), str(point_y)], timeout=10)
    if p.returncode: raise RuntimeError("无法聚焦微信输入框")
    time.sleep(0.15)

def _write_and_verify(text: str, bounds: list[int]) -> None:
    _focus_input(bounds)
    _clipboard_set(text)
    _keys(['keystroke "a" using command down', 'keystroke "v" using command down'])
    time.sleep(0.25)
    marker = "__EMPTY__" + uuid.uuid4().hex
    _clipboard_set(marker)
    _keys(['keystroke "a" using command down', 'keystroke "c" using command down'])
    time.sleep(0.15)
    copied = _clipboard_get()
    if copied != text:
        # Never send when the exact draft cannot be read back.
        _keys(['key code 51'])
        raise RuntimeError("微信输入框内容校验失败，已停止发送")

def prepare(chat: str, text: str) -> dict:
    try:
        selected = _open_verified_chat(chat)
        _write_and_verify(text, selected["bounds"])
        return {"ok": True, "chat": chat, "draftVerified": True, "fallback": "gui-ocr"}
    except Exception as e:
        return {"ok": False, "error": "WECHAT_GUI_FALLBACK_FAILED", "detail": str(e)}

def send(chat: str, text: str) -> dict:
    try:
        selected = _open_verified_chat(chat)
        _write_and_verify(text, selected["bounds"])
        _keys(['key code 36'])
        time.sleep(0.6)
        return {"ok": True, "chat": chat, "inputCleared": True, "deliveryAttempted": True, "fallback": "gui-ocr"}
    except Exception as e:
        return {"ok": False, "error": "WECHAT_GUI_FALLBACK_FAILED", "detail": str(e)}
