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
    if _osascript(SEARCH_MENU_SCRIPT) != "clicked":
        raise RuntimeError("未能打开微信本地搜索，已停止")
    time.sleep(0.25)
    _keys(['keystroke "a" using command down', 'keystroke "v" using command down'])
    time.sleep(0.8)
    x, y, w, h = _window_bounds()
    wanted = _normalize_title(chat)
    search_lines = _ocr_region(x, y, max(220, int(w * 0.22)), min(360, int(h * 0.45)), "search")
    exact_result = any(_normalize_title(line) == wanted for line in search_lines)
    local_group_section = any("群聊" in line for line in search_lines)
    if not (exact_result and local_group_section):
        # If focus was wrong, remove only the text just pasted; never press Return.
        _keys(['keystroke "a" using command down', 'key code 51'])
        raise RuntimeError(f"未在微信本地群聊结果中找到“{chat}”，已停止")
    # Only after an exact local result is visible may Return open it.
    _keys(['key code 36'])
    time.sleep(0.9)
    # Main chat header lies between the left conversation list and any optional right-side panel.
    header_lines = _ocr_region(x + int(w * 0.15), y, int(w * 0.48), min(110, h), "header")
    matched = any(_normalize_title(line) == wanted for line in header_lines)
    if not matched:
        raise RuntimeError(f"未能精确核验微信会话“{chat}”，已停止写入")
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
    # Collapse the Select-All range so the user can edit normally and Return cannot replace it.
    _keys(['key code 124'])

def _input_value(bounds: list[int]) -> str:
    _focus_input(bounds)
    marker = "__EMPTY__" + uuid.uuid4().hex
    _clipboard_set(marker)
    _keys(['keystroke "a" using command down', 'keystroke "c" using command down'])
    time.sleep(0.15)
    copied = _clipboard_get()
    _keys(['key code 124'])
    return "" if copied == marker else copied

def _normalize_message(value: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]", "", value).lower()

def _verify_posted(text: str, bounds: list[int]) -> bool:
    x, y, w, h = bounds
    lines = _ocr_region(x + int(w * 0.15), y + 80, int(w * 0.48), max(220, int(h * 0.72)), "delivery")
    seen = _normalize_message("".join(lines))
    wanted = _normalize_message(text)
    if len(wanted) < 8:
        return wanted in seen
    # The tail of the newest long bubble remains visible at the bottom of the chat.
    return wanted[-10:] in seen or wanted[-16:-6] in seen

def prepare(chat: str, text: str) -> dict:
    try:
        selected = _open_verified_chat(chat)
        _write_and_verify(text, selected["bounds"])
        return {"ok": True, "chat": chat, "draftVerified": True, "fallback": "gui-ocr"}
    except Exception as e:
        return {"ok": False, "error": "WECHAT_GUI_FALLBACK_FAILED", "detail": str(e)}

def send(chat: str, text: str) -> dict:
    send_triggered = False
    try:
        selected = _open_verified_chat(chat)
        bounds = selected["bounds"]
        _write_and_verify(text, bounds)
        shortcuts = [(['key code 36'], "Return"),
                     (['key code 36 using command down'], "Command+Return"),
                     (['key code 36 using control down'], "Control+Return")]
        for keys, name in shortcuts:
            send_triggered = True
            _keys(keys)
            time.sleep(0.5)
            if not _input_value(bounds).strip():
                time.sleep(0.8)
                if _verify_posted(text, bounds):
                    return {"ok": True, "chat": chat, "inputCleared": True,
                            "deliveryConfirmed": True, "shortcut": name, "fallback": "gui-ocr"}
                return {"ok": False, "error": "WECHAT_DELIVERY_UNCERTAIN", "uncertain": True,
                        "detail": "输入框已清空，但未能在聊天区核验到刚发送的正文。请先人工检查微信，切勿直接重发。"}
        return {"ok": False, "error": "WECHAT_DELIVERY_UNCERTAIN", "uncertain": True,
                "detail": "已经触发发送快捷键，但无法确认发送结果。请先人工检查微信，切勿直接重发。"}
    except Exception as e:
        if send_triggered:
            return {"ok": False, "error": "WECHAT_DELIVERY_UNCERTAIN", "uncertain": True,
                    "detail": f"已经触发发送动作，但后续核验异常：{e}。请先人工检查微信，切勿直接重发。"}
        return {"ok": False, "error": "WECHAT_GUI_FALLBACK_FAILED", "detail": str(e)}
