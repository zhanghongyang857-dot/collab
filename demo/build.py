#!/usr/bin/env python3
"""演示案例「万历新政」生成脚本：在固定的模拟时间下，按回目逐条写流转事件，生成一个完整的演示项目。

全部是虚拟数据：不真实派活、不调用任何模型。事件走 core/flow.py 的真实写入路径（校验、锁、渲染），
派活走派活脚本同一套钩子（dispatch_begin / dispatch_end），只有成员「做了什么」是编的。
剧情和每一步演示什么，见同目录的 剧本.md。

用法：python3 demo/build.py [--到 N] [--输出 目录]
  --到 N     只演到第 N 回（1–8，默认 8 即终回），项目停在那一回结束的时刻
  --输出     生成到哪里（默认 demo/万历新政）；目录已存在且是演示案例时先删掉重建
看板：python3 src/board/server.py --port 3101 --project demo/万历新政
只用 Python 标准库。
"""
import argparse
import re
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
KIT = HERE.parent / "src"  # 工具包
sys.path.insert(0, str(KIT / "core"))
import flow  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=8))
YEAR = 1573  # 万历元年
MARK = ".演示案例"
TITLES = {
    "总裁": "陛下", "总管": "内阁", "待你决定": "待批红", "没有需要你拍板的事": "无本上奏", "上报": "奏报", "确认": "核验", "越过": "逾制",
    "偏离": "逾制", "转交": "转呈", "派发": "交办", "交付": "复命", "解除": "准行", "建立": "立案",
    "提交": "进呈", "批准": "批红", "目标验收": "告成", "完成": "结案", "打回": "驳回", "退回": "留中",
    "重开": "重议", "改派": "改委", "进展": "进展", "变更": "更张", "更正": "勘误", "目标": "国事",
    "任务": "差事", "阶段": "节次", "总管建议": "内阁票拟", "规划中": "拟议", "意见": "批注",
}
CHAPTERS = [
    "第一回　河决徐州　内阁票拟",
    "第二回　清丈议起　阁臣会审",
    "第三回　堵口缺银　待批内帑",
    "第四回　朕批内帑　江南阻丈",
    "第五回　北虏求市　廷议和战",
    "第六回　河工告成　巡按核验",
    "第七回　鱼鳞册伪　清丈重开",
    "终　回　朱批定案　新政初成",
]


class Court:
    """模拟朝廷：一个项目、一只时钟。所有写入都经 flow.py。"""

    def __init__(self, root: Path):
        self.root = root
        self.proj: Optional[flow.Project] = None
        self.now = dt.datetime(YEAR, 3, 1, 8, 0, tzinfo=TZ)
        self.runs: Dict[str, int] = {}
        self.logs: List[str] = []
        self.chapter = ""

    # ---------- 搭项目 ----------
    def found(self) -> None:
        env = dict(os.environ, COLLAB_TEAM=str(HERE))
        subprocess.run(["bash", str(KIT / "core" / "init.sh"), "new", str(self.root), "-n", "万历新政", "--no-now"],
                       env=env, check=True, stdout=subprocess.DEVNULL)
        (self.root / MARK).write_text("由 demo/build.py 生成的演示项目，全部是虚拟数据；重新生成会整个删掉重建。\n", encoding="utf-8")
        rule = json.loads((KIT / "core" / "skeletons" / "render.json").read_text(encoding="utf-8"))
        rule["称谓"] = TITLES
        (self.root / "collab" / "内部" / "流程" / "渲染.json").write_text(json.dumps(rule, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        p = self.root / "collab" / "PROGRESS.md"
        text = p.read_text(encoding="utf-8")
        head = next(l for l in text.splitlines() if l.startswith("目标："))
        text = text.replace(head, "目标：万历元年新政：治河、清丈、北边、开海 ｜ 截止：万历元年秋 ｜ 状态：进行中 ｜ 建立于 1573-03-01")
        p.write_text(re.sub(r"^\[← NOW\]\(.*\)\n", "", text, count=1, flags=re.M), encoding="utf-8")  # 演示不挂 NOW
        self.proj = flow.Project(self.root)

    # ---------- 时钟 ----------
    def at(self, when: str) -> None:
        """跳到 MM-DD HH:MM；不倒退。"""
        t = dt.datetime.fromisoformat(f"{YEAR}-{when}:00").replace(tzinfo=TZ)
        self.now = max(t, self.now + dt.timedelta(minutes=1))
        self._env()

    def tick(self, minutes: int = 3) -> None:
        self.now += dt.timedelta(minutes=minutes)
        self._env()

    def _env(self) -> None:
        os.environ["FLOW_NOW"] = self.now.isoformat()

    # ---------- 流转 ----------
    def log(self, obj: str, edge: str, actor: str = "总管", **kw) -> Dict[str, Any]:
        self.tick()
        args = {"发起": actor, "写入者": kw.pop("写入者", "总管" if actor in flow.MANAGERS else "成员"), **kw}
        ev, _ = flow.record(self.proj, obj, edge, args)
        return ev

    def goal(self, title: str, gtype: str, basis: str, fill: Dict[str, str], deps: str = "—", prio: int = 1) -> str:
        self.tick()
        obj, path = flow.create(self.proj, "目标", {"发起": "总管", "写入者": "总管", "标题": title, "类型": gtype, "依据": basis})
        self.fill(path, fill)
        text = path.read_text(encoding="utf-8").replace("\n## 要什么", f"优先：{prio} ｜ 依赖：{deps} ｜ 截止：万历元年秋\n\n## 要什么", 1)
        path.write_text(text, encoding="utf-8")
        return obj

    def frame(self, goal: str, stages: List[Dict[str, Any]], note: str = "") -> None:
        """进呈前把差事都拟好：flow.py 框架，一次写好节次和全部差事卡。"""
        self.tick()
        flow.frame(self.proj, goal, {"阶段": stages}, {"说明": note})

    def task(self, title: str, basis: str, fill: Dict[str, str], goal: Optional[str] = None, stage: Optional[int] = None,
             actor: str = "总管") -> str:
        self.tick()
        states, _, _ = flow.replay_all(self.proj)
        if goal:  # 框架里已拟好的差事，直接拿来用
            ready = next((t for t in flow.goal_tasks(states, goal) if t["标题"] == title), None)
            if ready:
                return ready["编号"]
        args = {"发起": actor, "写入者": "总管", "标题": title, "依据": basis}
        if goal:
            args.update({"目标": goal, "阶段": stage})
        obj, path = flow.create(self.proj, "任务", args)
        self.fill(path, fill)
        return obj

    def fill(self, path: Path, values: Dict[str, str]) -> None:
        text = path.read_text(encoding="utf-8")
        for k, v in values.items():
            text = text.replace(f"- {k}：\n", f"- {k}：{v}\n", 1)
        path.write_text(text, encoding="utf-8")

    def add_people(self, goal: str, stage: int, who, why: str) -> None:
        """框架内换人：在阶段实例里加人选（一人或几人），记一条「变更」。"""
        states, _, _ = flow.replay_all(self.proj)
        stages = [dict(s) for s in states[goal]["阶段实例"]]
        for s in stages:
            if s["序"] == stage:
                s["人选"] = s["人选"] + [w for w in ([who] if isinstance(who, str) else who) if w not in s["人选"]]
        self.log(goal, "变更", 变更项=["人选"], 说明=why, 阶段=stages)

    def evidence(self, obj: str, name: str, body: str) -> str:
        """交付放在所属目标的工作目录下 <工作目录>/<任务>/（见协议「工作区」）。"""
        st = flow.replay_all(self.proj)[0][obj]
        rel = flow.workspace(self.proj, st, "总管")["交付"] + name
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {name.rsplit('.', 1)[0]}\n\n{body}\n\n（演示案例虚拟数据）\n", encoding="utf-8")
        return rel

    def dispatch_live(self, task: str, member: str, note: str, ran: int) -> str:
        """模拟一次还在跑的派活：派活脚本代写派发、接手，运行记录停在「运行中」（演示停在它跑了 ran 分钟的时刻）。"""
        n = self.runs.get(task, 0) + 1
        self.runs[task] = n
        rid = f"{task}-{n:02d}"
        self.tick()
        start = self.now
        flow.dispatch_begin(self.proj, task, "执行", member, rid)
        last = start + dt.timedelta(minutes=ran - 2)
        rec = {"run": rid, "task": task, "seat": "执行", "member": member, "mode": "新会话", "session": f"{member}-{rid.lower()}",
               "continues": "", "prompt": f"（演示）执行 {task}", "steps": 11, "last_action": note, "final": "", "error": "",
               "deviations": [], "override": "", "status": "运行中", "started": start.isoformat(), "last_at": last.isoformat(),
               "ended": None, "exit_code": None, "tokens": {"input": 21000, "cached": 98000, "output": 2600, "total": 121600}}
        rdir = self.root / "collab" / "内部" / "运行记录"
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / f"{rid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self.live_until = start + dt.timedelta(minutes=ran)
        return rid

    def dispatch(self, task: str, member: str, *, seat: str = "执行", minutes: int = 90, outcome: Optional[str] = "交付",
                 note: str = "", doc: Optional[tuple] = None, to: Optional[str] = None, result: Optional[str] = None,
                 override: str = "", tokens: tuple = (42000, 260000, 6000), steps: int = 18) -> str:
        """模拟一次派活：派活脚本代写开头，成员（编的）写结束边，派活脚本补进展；同时写一份运行记录。"""
        n = self.runs.get(task, 0) + 1
        self.runs[task] = n
        rid = f"{task}-{n:02d}"
        self.tick()
        start = self.now
        flow.dispatch_begin(self.proj, task, seat, member, rid, override)
        session = f"{member}-{rid.lower()}"
        self.tick(minutes)
        kw = {"派活": rid, "会话": session, "说明": note}
        if outcome == "交付":
            name, body = doc
            kw["证据"] = [self.evidence(task, name, body)]
            if to:
                kw["给"] = to
            self.log(task, "交付", member, **kw)
        elif outcome == "上报":
            self.log(task, "上报", member, **kw)
        elif outcome == "确认":
            self.log(task, "确认", member, 结果=result, **kw)
        self.tick(1)
        flow.dispatch_end(self.proj, task, member, rid, session, note or "（没有写结束边）", "完成")
        inp, cached, out = tokens
        rec = {"run": rid, "task": task, "seat": seat, "member": member, "mode": "新会话" if n == 1 else "续接",
               "session": session, "continues": f"{task}-{n - 1:02d}" if n > 1 else "", "prompt": f"（演示）{seat} {task}",
               "steps": steps, "last_action": "（演示）", "final": note or "（成员没写结束边）", "error": "",
               "deviations": [], "override": override, "status": "完成", "started": start.isoformat(),
               "last_at": self.now.isoformat(), "ended": self.now.isoformat(), "exit_code": 0,
               "tokens": {"input": inp, "cached": cached, "output": out, "total": inp + cached + out}}
        rdir = self.root / "collab" / "内部" / "运行记录"
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / f"{rid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return rid

    # ---------- 廷议（议题）：走黑板事件，和真实朝会同一条写入路径 ----------
    def issue(self, iid: str, title: str, state: str, question: Dict[str, str], who: List[tuple], rounds: List[List[tuple]],
              summary: Dict[str, str], ruling: Optional[Dict[str, str]], goal: Optional[str] = None, kind: str = "朝会") -> None:
        """一次廷议：内阁立题（陛下口谕为依据）→ 陛下开议 → 各部发言（第 1 轮各自独立；之后的发言可带 @ 和私下）→
        陛下止议 → 内阁收口总结 → 陛下裁决。会审不在这里裁决，随所挂目标的批红一起裁决。
        rounds 里每条是 (谁, 正文) 或 (谁, 正文, {"点名": [...], "私下": True})；谁是「总裁」时是陛下的发言。
        只有陛下公开的 @ 能叫醒人，部院写的 @ 只是文字。("加人", 成员, 视角) 是陛下在朝会页中途加人。"""
        self.tick()
        args = {"发起": "总管", "写入者": "总管", "标题": title, "依据": f"陛下口谕：开廷议「{title}」",
                "与会": [f"{m}:{v}" for m, v in who], "类型": kind}
        if goal:
            args["目标"] = goal
        obj, path = flow.create(self.proj, "议题", args)
        assert obj == iid, (obj, iid)
        self.fill(path, question)
        self.log(iid, "开始", "总裁", 写入者="看板")
        for r in rounds:
            for item in r:
                if item[0] == "加人":
                    self.tick(2)
                    st = flow.replay_all(self.proj)[0][iid]
                    new = [{"成员": x["成员"], "视角": x["视角"]} for x in st["与会"]] + [{"成员": item[1], "视角": item[2]}]
                    flow.record(self.proj, iid, "变更", {"发起": "总裁", "写入者": "看板", "与会": new, "变更项": ["与会"],
                                                       "说明": f"总裁在朝会页加人：{item[1]}"})
                    continue
                m, text, extra = (item + ({},))[:3]
                self.tick(4)
                flow.record(self.proj, iid, "发言", {"发起": m, "写入者": "看板" if m == "总裁" else "派活脚本", "正文": text,
                                                     "点名": extra.get("点名", []), "私下": extra.get("私下")})
        self.tick(10)
        self.log(iid, "结束讨论", "总裁", 写入者="看板")
        text = path.read_text(encoding="utf-8")
        text = (text.replace("- 共识：\n", f"- 共识：{summary['共识']}\n", 1)
                .replace("- 分歧：<各方立场、依据、代价>\n", f"- 分歧：{summary['争议']}\n", 1)
                .replace("- 建议：\n", f"- 建议：{summary['总管建议']}\n", 1))
        path.write_text(text, encoding="utf-8")
        self.log(iid, "总结", 说明=f"共识：{summary['共识']}；分歧：{summary['争议']}", 方案=summary.get("方案", summary["总管建议"]),
                 建议=summary["总管建议"])
        if ruling and kind != "会审":
            self.log(iid, "裁决", "总裁", 写入者="看板", 依据=ruling["决定"], 说明=ruling["决定"])
        st = flow.replay_all(self.proj)[0][iid]["状态"]
        assert kind == "会审" or st == state, (iid, st, state)

    # ---------- 手写文件（决议、日志、PROGRESS 叙述） ----------
    def decide(self, did: str, what: str, why: str, src: str) -> None:
        p = self.root / "collab" / "决议.md"
        p.write_text(p.read_text(encoding="utf-8").rstrip() + f"\n\n## {did}｜{self.now.date().isoformat()}｜{what}\n- 理由：{why}\n- 来源：{src}\n- 取代：无\n",
                     encoding="utf-8")

    def diary(self, line: str) -> None:
        self.logs.append(f"- {self.now.strftime('%m-%d')}｜{line}")

    def narrate(self, chapter: str, nxt: str, status: List[str]) -> None:
        p = self.root / "collab" / "PROGRESS.md"
        text = p.read_text(encoding="utf-8")
        a, b = text.index("## ▶ 下一步\n"), text.index("## 卡点")
        self.chapter = chapter
        body = f"## ▶ 下一步\n{nxt}\n\n## 现状\n" + "\n".join(f"- {s}" for s in status) + "\n\n"
        p.write_text(text[:a] + body + text[b:], encoding="utf-8")
        d = self.root / "collab" / "日志.md"
        d.write_text(d.read_text(encoding="utf-8").rstrip() + "\n\n" + "\n".join(reversed(self.logs)) + "\n", encoding="utf-8")
        self.logs = []

    def close(self) -> None:
        clock = self.root / "collab" / "内部" / "流程" / "时钟.json"
        # 有还在跑的派活时停在它跑到的那一刻，否则停在最后一件事之后一小时
        stop = getattr(self, "live_until", None) or self.now + dt.timedelta(hours=1)
        clock.write_text(json.dumps({"现在": stop.isoformat(), "回目": self.chapter,
                                     "说明": "演示案例停在剧情里的这一刻；检查里跟时间有关的提醒按它算"}, ensure_ascii=False) + "\n",
                         encoding="utf-8")
        flow.render_all(self.proj)


# ---------- 剧情 ----------

def ch1(c: Court) -> None:
    c.at("03-01 09:00")
    g1 = c.goal("黄河决口：赈灾与治河", "开发", "陛下口谕：徐州河决，着内阁速议治河赈灾", {
        "要什么": "堵住徐州决口，疏通运道，灾民有粮", "成功标准": "秋汛前合龙；漕船复通；赈粮按户发放",
        })
    c.diary("徐州河决，内阁立案 G001")
    c.at("03-01 11:00")
    c.log(g1, "起草阶段", 结果="讨论", 说明="陛下问治河两策，先议再定")
    gdir = c.proj.collab / "目标" / g1
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "问题.md").write_text("# G001 问题\n\n## 待解决\n\n## 已解决\n- 束水攻沙还是分流？→ 束水攻沙，见方案\n", encoding="utf-8")
    c.at("03-01 13:00")
    c.log(g1, "起草阶段", 结果="方案", 说明="两策利弊议毕，拟分四节次")
    (gdir / "方案.md").write_text("# G001 方案\n\n方略 → 施工（堵口、钱粮并行）；赈济另起；都察院巡按验收。\n\n## 硬约束\n- 不得加派江南田赋；工料银动用须奏准\n", encoding="utf-8")
    c.at("03-01 15:00")
    c.frame(g1, [
        {"序": 1, "名称": "方略", "类型": "执行", "前置": [], "任务": [
            {"键": "方略", "标题": "治河方略", "执行": "工部", "目的": "比较束水攻沙与分流两策，拟定治河方略", "交付物": "方略疏一道，附两策工料估算", "验收标准": "两策利弊、工料、工期写清，可供廷议"}]},
        {"序": 2, "名称": "施工", "类型": "执行", "可并行": True, "前置": [1], "任务": [
            {"键": "堵口", "标题": "堵口合龙", "执行": "工部", "目的": "按方略堵住徐州决口", "交付物": "合龙奏报、工料清册", "验收标准": "秋汛前合龙"},
            {"键": "钱粮", "标题": "工料钱粮", "执行": "户部", "目的": "核算工料银、调拨赈粮", "交付物": "钱粮清册", "验收标准": "账实相符"}]},
        {"序": 3, "名称": "赈济", "类型": "执行", "可并行": True, "前置": [], "任务": [
            {"键": "诏书", "标题": "拟罪己赈灾诏", "执行": "翰林院", "确认": "总裁", "目的": "以朕名义颁诏，安抚徐淮灾民", "交付物": "诏书定稿", "验收标准": "陛下朱批满意"}]},
        {"序": 4, "名称": "验收", "类型": "验收", "前置": [1, 2, 3], "任务": [
            {"键": "巡按", "标题": "巡按验收", "执行": "都察院", "目的": "巡按御史实地核验河工", "交付物": "核验奏疏", "验收标准": "按成功标准逐条核验"}]}],
        note="河工分方略、施工两段，赈济与河工同时起，都察院巡按验收")
    c.log(g1, "提交", 说明="票拟：先定方略，再分堵口、钱粮两路施工；赈济另起一节，请都察院巡按验收", 建议="准")
    c.at("03-02 10:00")
    c.log(g1, "批准", "总裁", 依据="朱批：准。方略定后即兴工，赈济即办，着都察院巡按验收",
          人选={1: ["工部"], 2: ["工部", "户部"], 3: ["翰林院"]})
    a = c.task("治河方略", "G001 批红", {"目的": "比较束水攻沙与分流两策，拟定治河方略", "交付物": "方略疏一道，附两策工料估算",
                                     "验收标准": "两策利弊、工料、工期写清，可供廷议"}, g1, 1)
    b = c.task("堵口合龙", "G001 批红", {"目的": "按方略堵住徐州决口", "交付物": "合龙奏报、工料清册", "验收标准": "秋汛前合龙"}, g1, 2)
    m = c.task("工料钱粮", "G001 批红", {"目的": "核算工料银、调拨赈粮", "交付物": "钱粮清册", "验收标准": "账实相符"}, g1, 2)
    v = c.task("巡按验收", "G001 批红", {"目的": "巡按御史实地核验河工", "交付物": "核验奏疏", "验收标准": "按成功标准逐条核验"}, g1, 4)
    # 赈济节次：陛下亲交翰林院拟诏、亲自核验，四易其稿（总裁直接派活、直接核验，需补充不计返工次数）
    t1 = c.task("拟罪己赈灾诏", "陛下口谕：着翰林院拟诏，抚慰灾民", {
        "目的": "以朕名义颁诏，安抚徐淮灾民", "交付物": "诏书定稿", "验收标准": "陛下朱批满意"}, g1, 3, actor="总裁")
    c.log(t1, "派发", "总裁", 给="翰林院", 说明="陛下亲交翰林院")
    c.log(t1, "接手", "翰林院")
    drafts = ["初稿：辞藻华丽，少实惠", "二稿：添蠲免钱粮", "三稿：语气过于自责", "四稿：增开仓日期"]
    for k, d in enumerate(drafts):
        c.tick(120)
        c.log(t1, "交付", "翰林院", 给="总裁", 证据=[c.evidence(t1, f"诏书第{k + 1}稿.md", d)], 说明=f"呈{d.split('：')[0]}")
        c.log(t1, "确认", "总裁", 结果="需补充", 说明=f"朱批：{['空言无补，要写开仓几处', '自责太过，有失体统', '开仓日期要写明', '可，再润色一字'][k]}")
    c.tick(90)
    c.log(t1, "交付", "翰林院", 给="总裁", 证据=[c.evidence(t1, "诏书定稿.md", "定稿：蠲免徐淮今年钱粮，开仓七处，三月初五起放赈")], 说明="呈定稿")
    c.log(t1, "确认", "总裁", 结果="通过", 说明="朱批：准颁行")
    c.diary("赈灾诏四易其稿，陛下准颁")
    c.dispatch(a, "工部", minutes=200, note="方略：主束水攻沙，附分流备案", doc=("治河方略.md", "束水攻沙：筑堤束水，以水攻沙；分流：开支河泄洪。工料估算见附表"))
    c.at("03-03 10:00")
    c.issue("I001", "治河方略之争", "已裁决",
            {"要决定什么": "徐州治河用束水攻沙还是分流", "背景与约束": "秋汛前须合龙；工料银有限", "参考资料": "work/G001-黄河决口：赈灾与治河/G001-T1/治河方略.md",
             "已知选项": "束水攻沙；分流；两者兼用"},
            [("工部", "治河工程"), ("户部", "钱粮成本"), ("都察院", "风险与先例")],
            [[("工部", "主束水攻沙：堤成则沙自去，一劳永逸；分流则河道日浅，十年后复决。"),
              ("户部", "分流工省银少，今年即可见效；束水攻沙需银倍之，恐难支应。"),
              ("都察院", "前朝分流屡试屡决，先例不利；束水攻沙需严查堤工，防偷工减料。")],
             [("总裁", "@户部 若分两年摊银，支应得来否？", {"点名": ["户部"]}),
              ("工部", "可分两年筑堤，今年先堵口，银可分摊。"), ("户部", "若分两年摊银，可支应，赞成。"),
              ("都察院", "无新异议，请加巡按专核堤工。")]],
            {"共识": "堵口为先；钱粮可分两年摊", "争议": "无实质分歧，都察院请专核堤工", "总管建议": "采束水攻沙，分两年筑堤，巡按专核",
             "方案": "A 束水攻沙，分两年筑堤；B 分流"},
            {"决定": "朱批：依议，用束水攻沙 → D001", "后续": "G001-T2、G001-T3"}, goal="G001")
    c.decide("D001", "治河用束水攻沙，分两年筑堤，巡按专核堤工", "廷议共识，十年之利", "I001")
    c.at("03-04 10:00")
    c.log(a, "确认", 结果="通过", 说明="依廷议 I001、D001 采束水攻沙")
    c.diary("廷议 I001 定束水攻沙（D001）")
    c.at("03-04 14:00")
    c.dispatch(m, "户部", minutes=300, note="工料银估四十万两，已拨三十万；赈粮开仓七处", doc=("钱粮清册.md", "工料银四十万两，已拨三十万两；赈粮二十万石"))
    c.at("03-05 09:00")
    c.log(b, "派发", 给="工部", 说明="依 D001 兴工")
    c.log(b, "接手", "工部", 说明="徐州开工")
    c.narrate(CHAPTERS[0], "等户部钱粮清册核验；工部堵口施工中",
              ["G001 方略已定（束水攻沙），施工阶段两路并行", "赈灾诏已颁"])


def ch2(c: Court) -> None:
    c.at("03-05 13:00")
    g2 = c.goal("清丈田亩与一条鞭法试点", "调研", "陛下口谕：欲均天下赋役，着内阁议清丈", {
        "要什么": "清丈山东、江南田亩，为一条鞭法试点立账", "成功标准": "两省鱼鳞册更新；试点州县赋役折银可行",}, prio=2)
    QING = [{"序": 1, "名称": "清丈", "类型": "调研", "可并行": True, "前置": [], "任务": [
                {"键": "山东", "标题": "山东清丈", "执行": "户部", "目的": "清丈山东田亩", "交付物": "山东鱼鳞册", "验收标准": "按县造册，误差小于百分之二"},
                {"键": "江南", "标题": "江南清丈", "执行": "户部", "目的": "清丈苏松常镇田亩", "交付物": "江南鱼鳞册", "验收标准": "按县造册，误差小于百分之二"}]},
            {"序": 2, "名称": "试点", "类型": "执行", "前置": [1], "任务": [
                {"键": "试点", "标题": "山东试点一条鞭法", "执行": "户部", "目的": "在山东三县试行赋役折银", "交付物": "试点奏报", "验收标准": "折银可行，民无大扰"}]}]
    c.frame(g2, QING, note="模板为检索、综合成文；清丈需分省并行再试点")
    c.log(g2, "提交", 说明="票拟：两省并行清丈，再择山东试点一条鞭法", 建议="准")
    c.at("03-06 09:00")
    c.issue("I002", "清丈框架会审", "已裁决",
            {"要决定什么": "清丈框架是否可行", "背景与约束": "江南豪强多，数据易作伪", "参考资料": "目标卡 G002", "已知选项": "开放"},
            [("户部", "钱粮"), ("兵部", "地方稳定"), ("都察院", "监察")],
            [[("户部", "支持：两省并行，三月可毕。"), ("兵部", "支持，但江南需防民变。"),
              ("都察院", "反对现框架：清丈数据全凭地方上报，无独立核验，必有作伪。请加科道核验一节。")],
             [("都察院", "地方上报之数，户部凭何核实？"),
              ("总裁", "@户部 都察院所问，作何答？", {"点名": ["户部"]}),
              ("户部", "同意加核验，可放在试点之后。"), ("都察院", "可，核验须在试点后、推行前。")]],
            {"共识": "两省并行清丈", "争议": "都察院坚持加独立核验；户部同意", "总管建议": "批红时加都察院第三方验收",
             "方案": "A 照框架并加都察院验收；B 照原框架"},
            None, goal=g2, kind="会审")
    c.diary("I002 会审：都察院请加独立核验")
    c.at("03-07 09:00")
    c.log(g2, "意见", "总裁", 说明="朱批：依会审所议，清丈后要有都察院独立核验", 写入者="看板")
    c.frame(g2, QING + [{"序": 3, "名称": "验收", "类型": "验收", "前置": [1, 2], "任务": [
        {"键": "核验", "标题": "科道核验", "执行": "都察院", "目的": "独立核验清丈与试点", "交付物": "核验奏疏", "验收标准": "抽查鱼鳞册与实地相符"}]}],
        note="依陛下批注加都察院核验一节")
    c.log(g2, "批准", "总裁", 依据="朱批：准。依会审所议，清丈后着都察院核验", 人选={1: ["户部"], 2: ["户部"]})
    s1 = c.task("山东清丈", "G002 批红", {"目的": "清丈山东田亩", "交付物": "山东鱼鳞册", "验收标准": "按县造册，误差小于百分之二"}, g2, 1)
    s2 = c.task("江南清丈", "G002 批红", {"目的": "清丈苏松常镇田亩", "交付物": "江南鱼鳞册", "验收标准": "按县造册，误差小于百分之二"}, g2, 1)
    c.task("山东试点一条鞭法", "G002 批红", {"目的": "在山东三县试行赋役折银", "交付物": "试点奏报", "验收标准": "折银可行，民无大扰"}, g2, 2)
    c.task("科道核验", "G002 批红 · I002", {"目的": "独立核验清丈与试点", "交付物": "核验奏疏", "验收标准": "抽查鱼鳞册与实地相符"}, g2, 3)
    c.dispatch(s1, "户部", minutes=600, note="山东清丈毕，新增隐田四万顷", doc=("山东鱼鳞册.md", "山东六府清丈完毕，新增隐田四万顷"))
    c.dispatch(s2, "户部", minutes=30, outcome=None, note="")  # 第一轮只开了个头，没写结束边
    c.at("03-07 18:00")
    c.log(s2, "解除", 说明="户部续丈江南")
    c.at("03-06 10:00")
    c.log("G001-T3", "确认", 结果="通过", 说明="钱粮清册账实相符")
    c.at("03-07 20:00")
    t2 = c.task("河南报灾（误记）", "通政司转河南巡抚奏", {"目的": "核报河南灾情"}, "G001", 3)
    c.log(t2, "进展", 说明="误记为河南大旱，实为徐州水灾波及")
    c.log(t2, "更正", 更正=2, 说明="上条记错，作废")
    c.narrate(CHAPTERS[1], "等户部江南清丈；工部堵口施工中",
              ["G002 清丈已批红（加都察院核验），两省并行", "G001 钱粮清册已核验"])


def ch3(c: Court) -> None:
    c.at("03-09 10:00")
    c.dispatch("G001-T2", "工部", minutes=240, outcome="上报", note="工料银尚缺十万两，决口合龙在即而银尽，不能续工")
    c.at("03-10 09:00")
    c.log("G001-T2", "转交", 给="总裁", 说明="内阁无从挪借，奏请圣裁",
          方案="A 拨内帑银十万两，十日可合龙；B 加派河南民夫，省银但误工一月；C 待秋汛后再堵，恐决口扩大", 建议="A")
    c.diary("工部缺银十万两，奏请内帑")
    c.at("03-10 15:00")
    c.log("G001-T6", "取消", 说明="误记，撤销；河南灾情由 G001-T3 钱粮一并核")
    c.at("03-11 10:00")
    c.log("G002-T1", "确认", 结果="通过", 说明="山东鱼鳞册齐备")
    c.narrate(CHAPTERS[2], "请陛下批红：是否拨内帑十万两堵口",
              ["G001 堵口缺银，工部受阻，已奏请圣裁", "G002 山东清丈已毕，江南在丈"])


def ch4(c: Court) -> None:
    c.at("03-12 09:00")
    c.log("G001-T2", "解除", "总裁", 依据="朱批：准拨内帑银十万两，速堵决口")
    c.diary("陛下准拨内帑")
    c.at("03-13 11:00")
    c.dispatch("G002-T2", "户部", minutes=480, outcome="上报", note="苏松豪强匿田阻丈，地方官不敢问")
    c.at("03-14 09:00")
    c.log("G002-T2", "转交", 给="总裁", 说明="非钦差不能压服",
          方案="A 遣钦差持敕督丈苏松；B 暂缓江南，只以山东为试点", 建议="A")
    c.narrate(CHAPTERS[3], "请陛下批红：是否遣钦差督丈苏松",
              ["G001 内帑已拨，堵口续工", "G002 江南豪强阻丈，已奏请圣裁"])


def ch5(c: Court) -> None:
    c.at("03-16 09:00")
    g3 = c.goal("北边：俺答求贡互市", "通用", "宣大总督奏：俺答请封贡互市，着议", {
        "要什么": "定和战之策；若开市，定章程", "成功标准": "边境三年无大警；马市章程可行",}, deps="G002", prio=2)
    c.frame(g3, [
        {"序": 1, "名称": "钱粮核定", "类型": "执行", "前置": [], "任务": [
            {"键": "边饷", "标题": "核定边饷", "执行": "户部", "目的": "核定宣大边饷与马价银", "交付物": "边饷清册", "验收标准": "可支三年"}]},
        {"序": 2, "名称": "互市谈判", "类型": "执行", "前置": [1], "任务": [
            {"键": "章程", "标题": "互市章程", "执行": "兵部", "目的": "与俺答议定互市章程", "交付物": "互市章程", "验收标准": "合 D002 条件"}]}],
        note="边务须先核饷再谈")
    c.log(g3, "提交", 说明="先核边饷，再议互市章程", 建议="准")
    c.log(g3, "批准", "总裁", 依据="朱批：准议", 人选={1: ["户部"], 2: ["兵部"]})
    q1 = c.task("核定边饷", "G003 批红", {"目的": "核定宣大边饷与马价银", "交付物": "边饷清册", "验收标准": "可支三年"}, g3, 1)
    q2 = c.task("互市章程", "G003 批红", {"目的": "与俺答议定互市章程", "交付物": "互市章程", "验收标准": "合 D002 条件"}, g3, 2)
    c.at("03-17 09:00")
    g4 = c.goal("月港开海调研", "调研", "闽抚奏请开海禁，着议", {
        "要什么": "调研月港开海利弊", "成功标准": "利弊、税饷、海防写清，可供廷议"}, prio=3)
    c.frame(g4, [
        {"序": 1, "名称": "检索", "类型": "调研", "可并行": True, "前置": [], "任务": [
            {"键": "检索", "标题": "月港海贸检索", "执行": "户部", "目的": "全开海禁，检索海贸", "交付物": "检索报告", "验收标准": "税饷有据"}]},
        {"序": 2, "名称": "综合成文", "类型": "调研", "前置": [1], "任务": [
            {"键": "成文", "标题": "开海利弊疏", "执行": "户部", "目的": "综合成文，供廷议", "交付物": "利弊疏", "验收标准": "可供廷议"}]}], note="全开海禁")
    c.log(g4, "提交", 说明="票拟：全开海禁", 建议="准")
    c.log(g4, "退回", "总裁", 说明="朱批：海禁祖制，全开不可，限船引再议")
    c.frame(g4, [
        {"序": 1, "名称": "检索", "类型": "调研", "可并行": True, "前置": [], "任务": [
            {"键": "检索", "标题": "月港海贸检索", "执行": "户部", "目的": "检索月港海贸、倭患旧案，只议限船引", "交付物": "检索报告", "验收标准": "税饷、倭患有据"}]},
        {"序": 2, "名称": "综合成文", "类型": "调研", "前置": [1], "任务": [
            {"键": "成文", "标题": "开海利弊疏", "执行": "户部", "目的": "综合成文，供廷议", "交付物": "利弊疏", "验收标准": "可供廷议"}]}], note="改限船引")
    c.log(g4, "提交", 说明="改票：限船引，按调研模板检索、综合成文", 建议="准")
    c.log(g4, "批准", "总裁", 依据="朱批：准议", 人选={1: ["户部"], 2: ["户部"]})
    c.log(g4, "暂停", 说明="进行中国事已四件，部院不敷，奏请开海暂缓")
    c.diary("开海暂缓：国事已四件")
    c.at("03-18 09:00")
    c.log("G002-T2", "解除", "总裁", 依据="朱批：遣钦差持敕督丈苏松")
    c.diary("陛下遣钦差督丈苏松")
    c.at("03-18 14:00")
    c.dispatch(q1, "户部", minutes=360, outcome=None)  # 这一轮没写结束边，派活脚本代写奏报
    c.at("03-19 09:00")
    c.log(q1, "解除", 说明="内阁令户部续核")
    c.dispatch(q2, "兵部", override="陛下特许：边饷未定，先行接洽", minutes=600, outcome="交付",
               note="互市章程初稿：大同、宣府开马市", doc=("互市章程初稿.md", "大同、宣府开马市，岁马不过万匹"))
    c.at("03-20 10:00")
    c.dispatch("G001-T2", "工部", minutes=900, note="决口合龙，运道复通", doc=("合龙奏报.md", "三月二十日合龙，漕船复通"))
    c.at("03-21 09:00")
    c.log("G001-T2", "确认", 结果="通过", 说明="合龙奏报属实")
    c.at("03-22 09:00")
    c.issue("I003", "和战之议", "已裁决",
            {"要决定什么": "准俺答互市，还是闭关备战", "背景与约束": "边饷吃紧；俺答新降", "参考资料": "work/G003-北边：俺答求贡互市/G003-T2/互市章程初稿.md",
             "已知选项": "开市；闭关"},
            [("兵部", "边务"), ("户部", "钱粮"), ("都察院", "风险")],
            [[("兵部", "主开市：以市易战，边军可省三成饷。"), ("户部", "赞成：马市可收税银，边饷可减。"),
              ("都察院", "反对：养虎遗患，一旦负约，边备已弛，悔之无及。")],
             [("加人", "工部", "边墙工料"),
              ("总裁", "@工部 若不开市，宣大边墙再修几处、费银几何？", {"点名": ["工部"]}),
              ("工部", "宣大边墙待修三百里，费银六十万两，三年方毕；开市则可缓修。"),
              ("兵部", "可限马数，违约即闭。"), ("户部", "同意限数。"),
              ("都察院", "仍持异议：请将本人异议原文载入奏疏，三年后复核。"),
              ("都察院", "臣恐边将私市已久，兵部所报马数未必可信。", {"私下": True})]],
            {"共识": "开市须限数，违约即闭", "争议": "都察院持异议，请原文载入并三年复核", "总管建议": "附条件开市，载入异议",
             "方案": "A 附条件开市；B 闭关备战"},
            {"决定": "朱批：附条件开市，岁马不过万匹，违约即闭 → D002；都察院异议存档，三年后复核", "后续": "G003-T2"}, goal="G003")
    c.at("03-24 10:00")
    c.decide("D002", "附条件开俺答马市：岁马不过万匹，违约即闭；都察院异议存档，三年复核", "以市易战，省边饷", "I003")
    c.diary("廷议 I003：附条件开市（D002），都察院异议存档")
    c.narrate(CHAPTERS[4], "核兵部互市章程；户部续核边饷", ["决口合龙", "附条件开市（D002）", "开海暂缓"])


def ch6(c: Court) -> None:
    c.at("03-25 09:00")
    c.dispatch("G001-T5", "都察院", minutes=480, note="核验河工：合龙稳固，堤工无偷减，余银两千两",
               doc=("河工核验疏.md", "抽查堤段十二处，合龙稳固；余银两千两"))
    c.at("03-26 09:00")
    c.log("G001-T5", "确认", 结果="通过", 说明="巡按核验属实")
    c.log("G001", "目标验收", 说明="河工告成：秋汛前合龙，漕运复通，赈粮发放毕",
          方案="A 告成结案，赏工部；B 留工部驻守一汛再结", 建议="A")
    c.diary("河工告成，奏请结案")
    c.at("03-27 10:00")
    c.dispatch("G002-T2", "户部", minutes=720, note="江南清丈毕，新增隐田六万顷", doc=("江南鱼鳞册.md", "苏松常镇清丈完毕，新增隐田六万顷"))
    c.at("03-28 09:00")
    c.log("G002-T2", "确认", 结果="通过", 说明="江南鱼鳞册齐备")
    c.dispatch("G002-T3", "户部", minutes=900, note="山东三县试行折银，民无大扰", doc=("试点奏报.md", "三县赋役折银，征收顺畅"))
    c.at("03-29 10:00")
    c.dispatch("G003-T1", "户部", minutes=300, note="宣大边饷可支三年", doc=("边饷清册.md", "宣大边饷可支三年"))
    c.log("G003-T1", "确认", 结果="通过", 说明="边饷核定")
    c.at("03-31 09:00")
    c.log("G002-T3", "确认", 结果="通过", 说明="试点可行")
    c.log("G003-T2", "确认", 结果="需补充", 给="兵部", 说明="章程未写违约闭市之条，与 D002 不合")
    c.dispatch("G003-T2", "兵部", minutes=240, note="补违约闭市条款", doc=("互市章程.md", "岁马不过万匹；负约即闭市"))
    c.at("04-01 09:00")
    c.log("G001", "完成", "总裁", 依据="朱批：河工告成，赏工部")
    c.log("G004", "恢复", 说明="河工已结，复议开海")
    c.task("月港海贸检索", "G004 批红", {"目的": "检索月港海贸、倭患旧案", "交付物": "检索报告", "验收标准": "税饷、海防各有据"}, "G004", 1)
    c.task("开海利弊疏", "G004 批红", {"目的": "综合成文，供廷议", "交付物": "利弊疏", "验收标准": "可供廷议"}, "G004", 2)
    c.diary("G001 结案；开海复议")
    c.at("04-02 09:00")
    c.dispatch("G002-T4", "都察院", minutes=60, outcome=None)  # 核验刚开工，下一回才有结论
    c.log("G002-T4", "解除", 说明="都察院续核")
    c.log("G002-T4", "进展", "都察院", 说明="抽查苏松三县鱼鳞册")
    c.narrate(CHAPTERS[5], "等都察院核验江南清丈；户部检索月港海贸",
              ["G001 结案", "G002 清丈、试点已毕，都察院核验中", "G004 开海复议"])


def ch7(c: Court) -> None:
    c.at("04-03 09:00")
    c.log("G002-T4", "交付", "都察院", 证据=[c.evidence("G002-T4", "核验疏.md", "苏松三县鱼鳞册数据雷同，疑为抄改；实地抽丈误差达一成")],
          说明="苏松三县鱼鳞册雷同，疑为抄改")
    c.log("G002-T4", "确认", 结果="通过", 说明="核验奏疏属实")
    c.log("G002-T2", "重开", 给="户部", 说明="鱼鳞册造假，江南重丈；后续节次一并作废")
    c.log("G002", "变更", "总管", 变更项=["成功标准"], 说明="复丈误差须在百分之一以内", 依据="朱批：朕览科道所奏，着严查重丈")
    c.diary("鱼鳞册伪，江南重丈，试点、核验作废")
    c.at("04-05 09:00")
    c.dispatch("G002-T2", "户部", minutes=600, note="江南复丈一稿", doc=("复丈一稿.md", "误差百分之三"))
    c.log("G002-T2", "确认", 结果="需补充", 说明="误差百分之三，未达百分之一")
    c.at("04-07 09:00")
    c.dispatch("G002-T2", "户部", minutes=600, note="江南复丈二稿", doc=("复丈二稿.md", "误差百分之二"))
    c.log("G002-T2", "确认", 结果="需补充", 说明="误差仍超")
    c.at("04-08 09:00")
    c.dispatch("G002-T2", "户部", minutes=600, note="江南复丈三稿", doc=("复丈三稿.md", "误差百分之一点五"))
    c.log("G002-T2", "确认", 结果="未通过", 说明="户部连返两次仍超差，返工已到上限")
    c.add_people("G002", 1, "工部", "清丈节次添工部协办（框架内换人）")
    c.log("G002-T2", "改派", 给="工部", 说明="升档：工部以弓步法协办复丈")
    c.at("04-10 09:00")
    c.dispatch("G002-T2", "工部", minutes=900, note="江南复丈毕，误差千分之六", doc=("复丈定稿.md", "工部弓步法复丈，误差千分之六"))
    c.log("G002-T2", "确认", 结果="通过", 说明="复丈合格")
    c.log("G002-T4", "重开", 给="都察院", 说明="复丈后重新核验")
    c.at("04-11 09:00")
    c.dispatch("G002-T4", "都察院", minutes=300, note="复核：复丈属实", doc=("复核疏.md", "抽丈五县，相符"))
    c.log("G002-T4", "确认", 结果="通过", 说明="复核属实")
    c.log("G002", "目标验收", 说明="清丈既实，试点可行", 方案="A 结案，一条鞭法于山东先行；B 再试一年", 建议="A")
    c.narrate(CHAPTERS[6], "请陛下批红：清丈结案、一条鞭法先行山东",
              ["G002 复丈合格（户部返工到上限，改委工部）", "G003 互市章程待核", "G004 开海复议"])


def ch8(c: Court) -> None:
    c.at("04-12 09:00")
    c.log("G002", "完成", "总裁", 依据="朱批：清丈既实，一条鞭法于山东先行")
    c.decide("D003", "一条鞭法先行山东，次年推及天下", "清丈既实，试点可行", "G002")
    c.at("04-13 09:00")
    c.log("G003-T2", "确认", 结果="通过", 说明="章程合 D002")
    c.log("G003", "目标验收", 说明="马市章程定，边境无警", 方案="A 结案；B 观察一季", 建议="A")
    c.at("04-14 09:00")
    c.log("G003", "打回", "总裁", 说明="朱批：章程须载都察院异议与三年复核之期")
    c.log("G003", "变更", 变更项=["交付物"], 说明="章程附载都察院异议与三年复核（依 D002）")
    c.at("04-15 09:00")
    c.log("G003", "目标验收", 说明="章程已附载异议与复核之期", 方案="A 结案；B 观察一季", 建议="A")
    c.at("04-16 09:00")
    c.log("G003", "完成", "总裁", 依据="朱批：依 D002 开马市")
    c.diary("G002、G003 结案")
    c.at("04-17 09:00")
    r1 = "G004-T1"
    c.dispatch(r1, "户部", minutes=480, note="月港海贸岁可征饷两万两", doc=("海贸检索.md", "岁可征饷两万两；倭患多因私贩"))
    c.at("04-18 09:00")
    c.log(r1, "确认", 结果="通过", 说明="检索有据")
    # 综合成文：五部院分头办，终回停在「现在」，关系图上各种情形都有：
    # 户部径交翰林院核验（成员之间的交接）；兵部候塘报奏报（受阻在内阁）；工部料价超估，内阁转呈陛下（待批红）；都察院访察还在跑
    c.add_people("G004", 2, ["兵部", "工部", "都察院"], "综合成文节次添兵部议海防、工部估船料、都察院访私贩（框架内换人）")
    c.task("海防条陈", "G004 批红", {"目的": "议开海后的海防布置", "交付物": "海防条陈", "验收标准": "兵力、汛期各有据"}, "G004", 2)
    c.task("福船料价", "G004 批红", {"目的": "估月港官船造价", "交付物": "料价册", "验收标准": "每艘料价有据"}, "G004", 2)
    c.task("访察月港私贩", "G004 批红", {"目的": "查私贩与倭寇勾连", "交付物": "访察疏", "验收标准": "人证、物证各有据"}, "G004", 2)
    c.dispatch("G004-T2", "户部", minutes=300, note="利弊疏初稿成，径送翰林院润色核验", to="翰林院",
               doc=("开海利弊疏初稿.md", "开海岁可征饷两万两；限船引、设海防同知以防私贩"))
    c.dispatch("G004-T3", "兵部", minutes=120, outcome="上报", note="浙闽塘报未到，倭情不明，请内阁咨行调阅")
    c.dispatch("G004-T4", "工部", minutes=150, outcome="上报", note="福船每艘料价三千两，超原估一倍，工部无此项银")
    c.log("G004-T4", "转交", 给="总裁", 说明="料价超估一倍，奏请圣裁",
          方案="A 准加料价造十艘；B 减为五艘；C 暂缓，先用民船", 建议="A")
    c.dispatch_live("G004-T5", "都察院", note="密访海澄县牙行，抄录私货账簿", ran=48)
    c.diary("开海诸差分头办：利弊疏送翰林院，兵部候塘报，工部料价奏请圣裁，都察院访察中")
    # 每个想法先立案：陛下随口一提也建国事卡，起草中只在「想法」页
    c.at("04-18 15:00")
    g5 = c.goal("考成法：以簿册考课百官", "通用", "陛下口谕：新政行之，须有考课，否则奉行不力", {
        "要什么": "给六部和地方设完成期限的簿册，按月查考，误期者议处", "成功标准": "六部各立考成簿；每月有查考奏报；误期可追到人"}, prio=2)
    c.log(g5, "起草阶段", 结果="讨论", 说明="考课由谁主持、查到何级，先议")
    gdir = c.proj.collab / "目标" / g5
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "问题.md").write_text(
        "# G005 问题\n\n## 待解决\n- 考成簿由内阁查，还是六科查？\n- 地方州县是否一并考课？\n\n"
        "## 已解决\n- 按月还是按季查考？→ 按月，见方案\n", encoding="utf-8")
    (gdir / "方案.md").write_text("# G005 方案\n\n每事立限期，一簿送六科、一簿送内阁；按月注销，误期者参。\n", encoding="utf-8")
    c.goal("漕粮改折银", "调研", "陛下口谕：漕运耗费太多，可否改折", {
        "要什么": "调研江南漕粮部分改征银两的利弊", "成功标准": "算清运费省多少、京仓够不够、粮价会不会涨"}, prio=3)
    c.diary("陛下提考成法、漕粮改折，内阁各立一卡（起草中）")
    c.narrate(CHAPTERS[7], "请陛下批红福船料价；咨行浙闽调阅塘报",
              ["G001、G002、G003 已结案", "G004 开海：翰林院核利弊疏，兵部候塘报，工部待批红，都察院访察中"])


STORY = [ch1, ch2, ch3, ch4, ch5, ch6, ch7, ch8]


def build(out: Path, upto: int = len(STORY)) -> Path:
    if out.exists():
        if not (out / MARK).exists():
            sys.exit(f"{out} 已存在且不是演示案例，不覆盖")
        shutil.rmtree(out)
    c = Court(out)
    c.found()
    for step in STORY[:upto]:
        step(c)
    c.close()
    os.environ.pop("FLOW_NOW", None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="生成演示案例「万历新政」（虚拟数据）")
    ap.add_argument("--到", dest="upto", type=int, default=len(STORY), help=f"演到第几回（1–{len(STORY)}）")
    ap.add_argument("--输出", dest="out", default=str(HERE / "万历新政"))
    a = ap.parse_args()
    if not 1 <= a.upto <= len(STORY):
        sys.exit(f"--到 要在 1–{len(STORY)} 之间")
    out = build(Path(a.out).expanduser().resolve(), a.upto)
    print(f"已生成：{out}（演到{CHAPTERS[a.upto - 1].replace('　', ' ')}）")
    print(f"看板：python3 {KIT / 'board/server.py'} --port 3101 --project {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
