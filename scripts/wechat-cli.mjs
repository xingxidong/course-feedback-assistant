#!/usr/bin/env node
import { NativeBridge } from "../vendor/wechat-fastbridge/bridge/native-runner.mjs";

const argv = process.argv.slice(2);
const action = argv[0] || "status";
const option = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : ""; };
const chat = option("--chat");
const text = option("--text");
const bridge = new NativeBridge({ timeoutMs: 12_000 });

try {
  let result;
  if (action === "status") result = await bridge.status();
  else if (action === "read") result = await bridge.read({ chat, limit: 8, autoSelect: true, allowFocus: true });
  else if (action === "prepare") {
    const selection = await bridge.selectChat({ chat, allowFocus: true });
    result = await bridge.run("draft", ["--chat", chat, "--text", text], 12_000);
    result.selection = selection;
  } else if (action === "send") result = await bridge.send({ chat, text, autoSelect: true, allowFocus: true });
  else throw Object.assign(new Error("UNKNOWN_ACTION"), { error: "UNKNOWN_ACTION" });
  console.log(JSON.stringify(result));
} catch (error) {
  console.log(JSON.stringify({ ok: false, error: error.error || error.message || "BRIDGE_ERROR", detail: error.detail || "" }));
  process.exitCode = 2;
}
