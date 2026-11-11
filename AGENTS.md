# 给贡献者和 AI 助手

- 开工先读 [src/README.md](src/README.md)（英文 [src/README.en.md](src/README.en.md)），再按需读 `src/core/README.md`、`src/board/README.md`。
- `src/` 是工具包本身；`tests/`、`demo/` 是测试和演示，不随工具包发布。
- 改动后跑全量测试：`python3 -m unittest discover -s tests`；改了流转或看板，再跑 `python3 demo/build.py` 确认演示能重建。
- 测试和演示只用虚构数据，不要写入任何真实的个人信息或本机绝对路径。
- 本仓库由作者的私有开发仓库按白名单导出，历史从导出开始；欢迎提 issue 和 PR，合并后会同步回开发仓库。
