#!/usr/bin/env python3
"""假 agy：原样回放 tests/样例/agy/ 里录的真实输出，不调用模型。供 test_agy.py 用。
直接作为程序启动（不经 python），这样派活脚本把 --effort 加在程序名后面时和真 agy 一样。

新会话回放 start-tools.jsonl，带 --conversation 回放 resume-effort.jsonl（两份是同一个会话）。
FAKE_ENV_DIR 给了就把收到的参数记到 agy.argv（每次一行 JSON）。
"""
import json
import os
import sys
from pathlib import Path

argv = sys.argv[1:]
if os.environ.get("FAKE_ENV_DIR"):
    with open(os.path.join(os.environ["FAKE_ENV_DIR"], "agy.argv"), "a", encoding="utf-8") as f:
        f.write(json.dumps(argv, ensure_ascii=False) + "\n")
sample = Path(__file__).resolve().parent / "样例" / "agy" / ("resume-effort.jsonl" if "--conversation" in argv else "start-tools.jsonl")
sys.stdout.write(sample.read_text(encoding="utf-8"))
