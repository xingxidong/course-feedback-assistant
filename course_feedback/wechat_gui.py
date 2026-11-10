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

_WINLIST_SRC = r'''
import Cocoa
let opts = CGWindowListOption(arrayLiteral: .excludeDesktopElements)
let list = CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as! [[String: Any]]
for w in list {
    let owner = w[kCGWindowOwnerName as String] as? String ?? "?"
    guard owner == "WeChat" || owner == "微信" else { continue }
    let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    let x = b["X"] as? Double ?? -1, y = b["Y"] as? Double ?? -1
    let ww = b["Width"] as? Double ?? -1, hh = b["Height"] as? Double ?? -1
    let layer = w[kCGWindowLayer as String] as? Int ?? -1
    let onscreen = w[kCGWindowIsOnscreen as String] as? Bool ?? false
    let alpha = w[kCGWindowAlpha as String] as? Double ?? -1
    if ww >= 400 && hh >= 300 && layer == 0 && onscreen && alpha > 0.05 {
        print(String(format: "%d %d %d %d", Int(x), Int(y), Int(ww), Int(hh)))
    }
}
'''

def _build_winlist() -> None:
    BIN.mkdir(parents=True, exist_ok=True)
    source = ROOT / "scripts" / "wechat-winlist.swift"
    target = BIN / "wechat-winlist"
    if target.exists() and source.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return
    if source.exists():
        p = _run(["/usr/bin/swiftc", str(source), "-o", str(target)], timeout=120)
        if p.returncode:
            raise RuntimeError("窗口定位程序编译失败：" + p.stderr[-300:])

def _visually_frontmost_window() -> tuple[int, int, int, int] | None:
    """Ask the window server which WeChat window is actually visible on screen.

    screencapture -R grabs whatever is drawn at those pixels, so a stale or
    occluded window rect silently OCRs a different app. This is the ground truth.
    """
    _build_winlist()
    tool = BIN / "wechat-winlist"
    if not tool.exists():
        return None
    p = _run([str(tool)], timeout=10)
    if p.returncode:
        return None
    rect = None
    for line in p.stdout.splitlines():
        nums = [int(v) for v in re.findall(r"-?\d+", line)]
        if len(nums) >= 4:
            rect = (nums[0], nums[1], nums[2], nums[3])  # front-to-back; first hit wins
            break
    return rect

def _window_bounds() -> tuple[int, int, int, int]:
    """Accessibility-reported frame, used only as a cross-check."""
    raw = _osascript('tell application "System Events" to tell process "WeChat" to return {position of window 1, size of window 1}')
    nums = [int(x) for x in re.findall(r"-?\d+", raw)]
    if len(nums) < 4: raise RuntimeError("无法读取微信窗口位置")
    return nums[0], nums[1], nums[2], nums[3]

def _frontmost_app() -> str:
    try:
        return _osascript('tell application "System Events" to return name of first process whose frontmost is true', timeout=8)
    except Exception:
        return ""

def _ensure_window() -> tuple[int, int, int, int]:
    """Bring WeChat to the front and verify it really is drawn there."""
    _build_helpers()
    for attempt in range(3):
        try:
            _osascript('tell application "WeChat" to reopen', timeout=8)
            _osascript('tell application "WeChat" to activate', timeout=8)
        except Exception:
            pass
        time.sleep(0.4 + 0.3 * attempt)
        rect = _visually_frontmost_window()
        if rect:
            ax = _window_bounds()
            # Trust the window server rect; AX can report a stale position.
            return rect if rect[2] >= 400 else ax
    front = _frontmost_app()
    raise RuntimeError(
        f"微信窗口未能显示在最前面（当前前台：{front or '未知'}）。"
        "请先把微信主窗口切到当前桌面并置于最前，再重试。")


def _normalize_title(value: str) -> str:
    value = re.sub(r"\s*[（(]\s*\d+\s*[)）]\s*$", "", value.strip())
    return re.sub(r"[^\w\u3400-\u9fff]", "", value).lower()

def _title_equiv(line: str, wanted: str) -> bool:
    """Emoji/decorated group names: WeChat shows the full title, the DB may hold a
    plainer form. Accept exact equality after stripping non-word chars, plus a
    containment check on a long enough prefix so '金秋十月' matches '金秋十月🍂'."""
    got = _normalize_title(line)
    if not wanted:
        return False
    if got == wanted:
        return True
    if len(wanted) >= 4 and (wanted in got or got in wanted):
        return True
    return False


def _ocr_region(x: int, y: int, w: int, h: int, name: str) -> list[str]:
    image = Path("/tmp") / f"wechat-feedback-{name}.png"
    p = _run(["/usr/sbin/screencapture", "-x", "-R", f"{x},{y},{w},{h}", str(image)], timeout=20)
    if p.returncode: raise RuntimeError("无法截取微信窗口")
    p = _run([str(OCR), str(image)], timeout=45)
    if p.returncode: raise RuntimeError("微信标题识别失败")
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]

def _open_verified_chat(chat: str) -> dict:
    bounds = _ensure_window()
    x, y, w, h = bounds
    _clipboard_set(chat)
    if _osascript(SEARCH_MENU_SCRIPT) != "clicked":
        raise RuntimeError("未能打开微信本地搜索，已停止")
    time.sleep(0.35)
    _keys(['keystroke "a" using command down', 'keystroke "v" using command down'])
    time.sleep(1.1)
    # Reactivating after the menu click could have pushed another app forward.
    if _frontmost_app() not in ("WeChat", "微信"):
        bounds = _ensure_window()
        x, y, w, h = bounds
    wanted = _normalize_title(chat)
    search_lines = _ocr_region(x, y, max(220, int(w * 0.22)), min(360, int(h * 0.45)), "search")

    # The local "最常使用" panel lists the matching chat directly; the "群聊"
    # section header only appears for broad/multi-hit queries, so it is NOT
    # required. Requiring it rejected every uniquely-named group.
    exact_result = any(_title_equiv(line, wanted) for line in search_lines)
    if not exact_result:
        # If focus was wrong, remove only the text just pasted; never press Return.
        _keys(['keystroke "a" using command down', 'key code 51'])
        hint = "请确认微信已登录且主窗口在最前面"
        raise RuntimeError(f"未在微信本地搜索结果中找到“{chat}”，已停止（{hint}）")
    # Only after an exact local result is visible may Return open it.
    _keys(['key code 36'])
    time.sleep(1.1)
    # Main chat header lies between the left conversation list and any optional right-side panel.
    header_lines = _ocr_region(x + int(w * 0.15), y, int(w * 0.48), min(110, h), "header")
    matched = any(_title_equiv(line, wanted) for line in header_lines)
    if not matched:
        raise RuntimeError(f"未能精确核验微信会话“{chat}”，已停止写入")
    return {"chat": chat, "header": header_lines, "bounds": [x, y, w, h]}


def _focus_input(bounds: list[int]) -> None:
    if _frontmost_app() not in ("WeChat", "微信"):
        bounds = list(_ensure_window())
    x, y, w, h = bounds
    point_x = x + int(w * 0.43)
    point_y = y + int(h * 0.88)
    p = _run([str(CLICK), str(point_x), str(point_y)], timeout=10)
    if p.returncode: raise RuntimeError("无法聚焦微信输入框")
    time.sleep(0.25)
    # A blind coordinate click lands on whatever window owns those pixels. If the
    # click stole focus to another app, refuse to paste into it.
    front = _frontmost_app()
    if front not in ("WeChat", "微信"):
        raise RuntimeError(f"点击输入框后前台变成了“{front or '未知'}”，为防误粘贴已停止。请把微信窗口切到最前再试。")


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
