# 批红（collab）

**AI 票拟，你来批红。**

把几个 AI 助手（Claude、Codex、DeepSeek 等）组织成一个小班子，替你推进真实项目：你定目标、拍板；助手们在各自的原生应用里分工执行、互相验收，进度写进项目里的共享 Markdown 文件，在本机看板上一目了然。全部是本地文件和 Python 标准库脚本，不需要数据库、账号或云服务。

工具包的完整说明、上手步骤和目录见 [src/README.md](src/README.md)。

## 仓库里有什么

```
src/      工具包本身：流转引擎、看板服务、看板模块、装进项目的工作台
tests/    测试和期望输出
demo/     演示案例「万历新政」：用真实的 init.sh 和 flow.py 生成的虚拟项目，也是最大的一组回归测试
```

## 快速试用

需要 Python 3（只用标准库），目前只在 macOS 上用过。

```bash
python3 -m unittest discover -s tests     # 全量测试
python3 demo/build.py                     # 生成演示项目 demo/万历新政/
```

日常使用时把 `src/` 发布成一份独立拷贝（`src/core/publish.sh <NOW 所在目录>/NOW/系统`），步骤见 [src/README.md](src/README.md)「上手」。

## 状态

早期版本，接口和文件格式还会变。文档目前只有中文。

## 许可证

[MIT](LICENSE)
