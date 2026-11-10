#!/usr/bin/env python3
"""旧路径兼容：archive.py 已随安排模块移到 modules/schedule/archive.py，这里原样转过去。"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[2] / "modules" / "schedule" / "archive.py"), run_name="__main__")
