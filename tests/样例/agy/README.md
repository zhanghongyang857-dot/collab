# agy 真实样本（G058-T1，2026-11-14，agy 1.5.9）

在临时目录 `/tmp/agy-rec` 录制，原样保存。`dispatch.py` 的 `parse_agy`、`usage_agy` 只按这里出现的字段写，`tests/test_agy.py` 用它们做夹具。

| 文件 | 命令（都是 `agy -p "<启动语>" --output-format stream-json …`） | 看什么 |
|---|---|---|
| start-read.jsonl | `--model gemini-4-argon-low --dangerously-skip-permissions` | 一次 read_file 工具调用 |
| resume.jsonl | 上一条的 `--conversation <id> --model gemini-4-argon-low …` | 续接：同一 conversation_id，step_index 接着往下，result.usage 是会话累计 |
| start-tools.jsonl | `--model gemini-4-argon --dangerously-skip-permissions` | write_file、run_command 两次工具调用 |
| resume-effort.jsonl | 上一条的 `--conversation <id> --effort high --dangerously-skip-permissions`（没给 --model） | 续接时加档位可行；没给 --model 时 init 里没有 model，走 agy 默认型号 |
| effort-base-id.jsonl | `--model gemini-4-argon --effort high` | 不带档位后缀的 ID 加 --effort 可行（thinking_tokens 27，low 后缀为 0） |
| effort-conflict.jsonl / .err | `--model gemini-4-argon-low --effort high` | 带后缀的 ID 再给不同档位：退出码 1，只有一条 result，status ERROR |
| effort-unsupported.jsonl / .err | `--model claude-opus-5-5 --effort xhigh` | 型号不支持的档位：同上，error 里列出可用档位 |
| denied.jsonl / .err | `--model gemini-4-argon-low`（不加 --dangerously-skip-permissions），要它写文件 | 无人值守时写文件被自动拒：status 仍是 SUCCESS，response 空，denied_actions 列出被拒的工具 |
| lost.jsonl / .err | `--conversation 00000000-0000-0000-0000-000000000000` | 续接不存在的会话：不报错，开新会话（新 conversation_id），只在 stderr 打 warning，退出码 0 |
| json-format.json | `--output-format json` | 只有最后一个对象，字段同 stream-json 的 result；没有过程，派活不用 |
| models.txt | `agy models` | 可用型号；ID 带档位后缀（-low/-medium/-high/-xhigh），各型号档位不同 |

实测结论：

- 事件：`init`（conversation_id、init.model 只在给了 --model 时有）→ `step_update`（step_type 为 user_input / system_message / agent_response / tool，state 为 ACTIVE / DONE；回复是 agent_response 的 text_delta 片段；工具在 tool_name 和 tool_info.parameters，参数名是 `Path`、`CommandLine` 这样的大写开头）→ `result`（status、response、error、num_turns、usage、denied_actions）。
- 用量：每个 agent_response 的 DONE 带一次调用的 usage；`input_tokens` 不含 `cache_read_tokens`；`total_tokens` = input + output，所以 output 已含 thinking。result.usage 是整个会话的累计（续接时含前几次），派活按步相加。
- 档位：`--model` 用不带后缀的 ID（gemini-4-hydrogen、gemini-4-argon、claude-opus-5-5、claude-sonnet-5-5 都能直接用）时可以加 `--effort`；不加 `--effort` 走该型号默认档。带后缀的 ID 和 `--effort` 一致时可用、不一致报错。Claude 型号只有 low/medium/high。
- 续接要带上 `--model`，否则换成 agy 默认型号。
