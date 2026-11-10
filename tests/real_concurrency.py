#!/usr/bin/env python3
"""真实模型的并发实测（手动运行，不属于 unittest）：对一个已搭好的会议室，每轮由总裁同时 @ 两位成员，连续 N 轮，
检查：每人每轮恰好一次运行和一条公开发言；会话不串（每人始终一个会话、两人不同）；发言正文各自对应自己的问题。
用法：real_concurrency.py <看板端口> <项目ID> <议题> <项目目录> [轮数] [成员A 成员B]  结果打印为 JSON，退出码 0 才算通过。"""
import json
import sys
import time
import urllib.request
from pathlib import Path

port, pid, iid, root = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
rounds = int(sys.argv[5]) if len(sys.argv) > 5 else 3
A, B = (sys.argv[6], sys.argv[7]) if len(sys.argv) > 7 else ("claude-sonnet", "claude-opus")
base = f"http://127.0.0.1:{port}/api/p/{pid}/meet/{iid}"


def post(body):
    req = urllib.request.Request(base, json.dumps(body).encode(), {"Content-Type": "application/json", "X-Board": "1"})
    return json.load(urllib.request.urlopen(req))


def get():
    return json.load(urllib.request.urlopen(base))


def runs():
    d = root / "collab" / "内部" / "运行记录"
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob(f"{iid}-*.json"))]


problems = []
t_all = time.time()
for n in range(1, rounds + 1):
    qa, qb = n * 11, n * 7
    t0 = time.time()
    post({"action": "发言", "text": f"@{A} @{B} 第{n}轮：{A} 请只回答 {qa}+1 的结果；{B} 请只回答 {qb}+2 的结果。各答各的，一个数字，不调用工具。"})
    while time.time() - t0 < 240:
        time.sleep(2)
        rs = [r for r in runs() if r.get("status") != "运行中"]
        if len(rs) >= 2 * n and not any(r.get("status") == "运行中" for r in runs()):
            break
    print(f"第{n}轮用时 {time.time() - t0:.0f} 秒", flush=True)

rs = runs()
d = get()
msgs = [m for m in d["issue"]["消息"] if m["发起"] in (A, B)]
for who in (A, B):
    mine = [r for r in rs if r["member"] == who]
    if len(mine) != rounds:
        problems.append(f"{who} 运行 {len(mine)} 次，应为 {rounds}")
    if any(r["status"] != "完成" for r in mine):
        problems.append(f"{who} 有未完成的运行：{[(r['run'], r['status'], r.get('error')) for r in mine if r['status'] != '完成']}")
    sess = {r["session"] for r in mine if r.get("session")}
    if len(sess) != 1:
        problems.append(f"{who} 会话不止一个：{sess}")
    said = [m for m in msgs if m["发起"] == who]
    if len(said) != rounds:
        problems.append(f"{who} 发言 {len(said)} 条，应为 {rounds}（丢或重）")
    expect = [str(n * (11 if who == A else 7) + (1 if who == A else 2)) for n in range(1, rounds + 1)]
    for e, m in zip(expect, said):
        if e not in m["正文"]:
            problems.append(f"{who} 第 {expect.index(e) + 1} 轮应含 {e}，实际：{m['正文'][:40]}")
sa = {r["session"] for r in rs if r["member"] == A}
sb = {r["session"] for r in rs if r["member"] == B}
if sa & sb:
    problems.append("两人共用了会话")
seqs = [m["项目序"] for m in d["issue"]["消息"]]
if len(seqs) != len(set(seqs)):
    problems.append("项目序重复")
out = {"轮数": rounds, "总用时秒": round(time.time() - t_all), "问题": problems,
       "运行": [{k: r.get(k) for k in ("run", "member", "status", "mode", "session", "started", "ended", "tokens")} for r in rs],
       "发言": [(m["项目序"], m["发起"], m["正文"][:60]) for m in d["issue"]["消息"]]}
print(json.dumps(out, ensure_ascii=False, indent=1))
sys.exit(1 if problems else 0)
