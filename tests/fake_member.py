"""假成员：照 Claude 命令行的 stream-json 格式输出，回复按名字和上下文包里的提示定。供 test_meet.py 用，不调用模型。

用法：fake_member.py <名字> <启动语> [--resume <会话>]
"""
import json
import os
import re
import sys
import time

name, prompt = sys.argv[1], sys.argv[2]
session = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--resume" else f"fake-{name}-{abs(hash(prompt)) % 10000}"
# FAKE_FAIL_DIR/<名字> 存在时假装「未登录」失败（测试失败和补叫）；FAKE_ENV_DIR 给了就把收到的环境记下来
if os.environ.get("FAKE_ENV_DIR"):
    with open(os.path.join(os.environ["FAKE_ENV_DIR"], f"{name}.env"), "a", encoding="utf-8") as f:
        f.write(json.dumps({k: v for k, v in os.environ.items() if k.startswith(("CLAUDE", "ANTHROPIC", "PATH"))}) + "\n")
if os.environ.get("FAKE_FAIL_DIR") and os.path.exists(os.path.join(os.environ["FAKE_FAIL_DIR"], name)):
    print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in · Please run /login"}), flush=True)
    sys.exit(1)
# FAKE_FAIL_DIR/<会话>.lost 存在时续接这个会话失败，事件格式照真实的 Claude 命令行（result 为空，原因在 errors，也写 stderr）
if os.environ.get("FAKE_FAIL_DIR") and sys.argv[3:4] == ["--resume"] and os.path.exists(os.path.join(os.environ["FAKE_FAIL_DIR"], session + ".lost")):
    print(f"No conversation found with session ID: {session}", file=sys.stderr, flush=True)
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": session,
                      "errors": [f"No conversation found with session ID: {session}"]}), flush=True)
    sys.exit(1)
if "[[无原因失败]]" in prompt:
    print("真正的原因在 stderr", file=sys.stderr, flush=True)
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True}), flush=True)
    sys.exit(1)
first = "这是你第一次发言" in prompt
asked = "点名问你" in prompt
if name == "codex":
    reply = "主张本地缓存。@deepseek 你怎么看风险？" if first else "版本号失效即可。"
else:
    reply = ("主张不缓存。\n<私下 总裁>codex 低估了工期</私下>" if first
             else "一致性风险，@codex 怎么保证？" if asked else "[PASS]")
def emit(o):
    print(json.dumps(o, ensure_ascii=False), flush=True)


def stream(e):
    emit({"type": "stream_event", "event": e})


if "[[慢启动]]" in prompt:  # 进程起来后过一会儿才有第一条输出，初始化之后再过一会儿才有模型的输出（收尾时不用等）
    if "不要再调用任何工具" not in prompt:
        time.sleep(1.5)
emit({"type": "system", "session_id": session})
if "不要再调用任何工具" in prompt:  # 收尾提示：立刻用已有内容发言
    if "[[慢收尾]]" in prompt:
        time.sleep(1.5)
    emit({"type": "result", "session_id": session, "result": f"收尾：{name} 用已有内容发言"})
    sys.exit(0)
# 总裁的话里带 [[工具 N]] 就先调用 N 次工具，[[慢]] 就一段一段慢慢写，[[卡]] 就卡住不动（测试状态、正在写、停止、收尾、上限）
if "[[慢启动]]" in prompt:
    time.sleep(1.5)
if "[[无阶段]]" in prompt:  # 不报阶段的成员（Codex 的 turn.started 这类）
    emit({"type": "turn.started"})
    time.sleep(1.5)
if "[[心跳]]" in prompt:  # 工具不输出，命令行照发心跳
    stream({"type": "message_start"})
    stream({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash"}})
    for _ in range(30):
        emit({"type": "tool_progress", "tool_name": "Bash", "heartbeat": True, "session_id": session})
        time.sleep(0.2)
m = re.search(r"\[\[工具 (\d+)\]\]", prompt)
for n in range(int(m.group(1)) if m else 0):
    stream({"type": "message_start"})
    stream({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash"}})
    time.sleep(0.5)  # 工具跑着
    emit({"type": "assistant", "message": {"id": f"m{n}", "usage": {"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 50},
                                           "content": [{"type": "tool_use", "name": "Bash", "input": {"command": f"echo {n}"}}]}})
    emit({"type": "user"})
    time.sleep(0.4)
if "[[慢]]" in prompt:
    stream({"type": "message_start"})
    stream({"type": "content_block_start", "content_block": {"type": "text"}})
    for piece in ("先写", "一半的", "回复"):
        stream({"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}})
        time.sleep(1.2)
if "[[卡]]" in prompt:
    stream({"type": "message_start"})
    time.sleep(120)
emit({"type": "result", "session_id": session, "result": reply})
