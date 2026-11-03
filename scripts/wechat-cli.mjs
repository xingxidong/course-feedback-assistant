#!/usr/bin/env node
import { NativeBridge } from "../vendor/wechat-fastbridge/bridge/native-runner.mjs";
import { execFileSync } from "node:child_process";

const argv = process.argv.slice(2);
const action = argv[0] || "status";
const option = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : ""; };
const chat = option("--chat");
const text = option("--text");
const bridge = new NativeBridge({ timeoutMs: 12_000 });
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function mainWindowCount() {
  const debug = await bridge.run("debug", [], 5_000);
  return (debug.apps || []).reduce((sum, app) => sum + Number(app.windows?.count || 0), 0);
}

async function ensureMainWindow() {
  if (await mainWindowCount()) return;
  execFileSync("/usr/bin/osascript", [
    "-e", 'tell application id "com.tencent.xinWeChat" to reopen',
    "-e", 'tell application id "com.tencent.xinWeChat" to activate',
  ]);
  await delay(700);
  if (!(await mainWindowCount())) {
    throw Object.assign(new Error("WECHAT_WINDOW_NOT_FOUND"), {
      error: "WECHAT_WINDOW_NOT_FOUND",
      detail: "微信已运行，但主聊天窗口没有打开",
    });
  }
}

try {
  let result;
  if (action === "status") {
    result = await bridge.status();
    const windowReady = result.ok ? Boolean(await mainWindowCount()) : false;
    result.windowReady = windowReady;
    if (result.ok && !windowReady) {
      result.ok = false;
      result.error = "WECHAT_WINDOW_NOT_FOUND";
      result.detail = "微信已登录，但主聊天窗口尚未打开；发送时会自动打开";
    }
  } else {
    await ensureMainWindow();
    if (action === "read") result = await bridge.read({ chat, limit: 8, autoSelect: true, allowFocus: true });
    else if (action === "prepare") {
      const selection = await bridge.selectChat({ chat, allowFocus: true });
      result = await bridge.run("draft", ["--chat", chat, "--text", text], 12_000);
      result.selection = selection;
    } else if (action === "send") result = await bridge.send({ chat, text, autoSelect: true, allowFocus: true });
    else throw Object.assign(new Error("UNKNOWN_ACTION"), { error: "UNKNOWN_ACTION" });
  }
  console.log(JSON.stringify(result));
} catch (error) {
  console.log(JSON.stringify({ ok: false, error: error.error || error.message || "BRIDGE_ERROR", detail: error.detail || "" }));
  process.exitCode = 2;
}
