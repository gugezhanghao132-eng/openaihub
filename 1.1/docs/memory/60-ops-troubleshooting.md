# 60 - 运维与常见问题排查

## 安装版本不一致

### 现象

- 某些机器安装到旧版本，另一些机器是最新版。

### 常见原因

- npm registry 指向镜像源（如 `npmmirror`）导致同步延迟。

### 排查命令

- `npm config get registry`
- `npm config list`
- `npm view openaihub version --registry https://registry.npmjs.org`
- `npm view openaihub version --registry https://registry.npmmirror.com`

### 建议

- 安装统一使用官方源：
  - `npm install -g openaihub --registry https://registry.npmjs.org`
- GitHub 页面、README、npm 说明里的公开安装命令都必须写成官方源版本，不能只写简短版。

## 发布时明明有 token 但 npm 仍报 ENEEDAUTH

### 现象

- `token.txt` 明明存在且内容正确。
- `npm publish` 或 `npm whoami` 仍报：
  - `ENEEDAUTH`
  - `This command requires you to be logged in`
- 某些情况下还会出现：
  - `Unknown user config "<token>"`

### 根因

- Windows PowerShell 如果没有显式按 UTF-8 读取 `token.txt`，可能因为中文冒号或编码差异导致正则没有正确提取 token。
- 直接用脚本手写临时 `.npmrc` 的某些写法会被当前 npm 版本错误解析，导致 `_authToken` 没有真正生效。

### 处理方式

- 用显式 UTF-8 方式读取 `token.txt`。
- 用临时 `userconfig` 文件配合：
  - `npm config set registry https://registry.npmjs.org/ --userconfig <path>`
  - `npm config set //registry.npmjs.org/:_authToken <token> --userconfig <path>`
- 然后再执行：
  - `npm whoami --registry https://registry.npmjs.org`
  - `npm publish --access public --registry https://registry.npmjs.org`

## 发布时忘记凭据文件

### 现象

- 准备发布 npm / GitHub Release 时忘记先检查本机凭据位置。

### 固定规则

- 发布任务开始时，先检查仓库根目录 `token.txt`。
- 未检查 `token.txt` 之前，不应进入发布执行步骤。

### 处理方式

- 若忘记，立即回到发布前检查清单重新执行。
- 发布流程文档与记忆文档要同步更新，防止重复遗忘。

## 配额显示异常 / 误切号

### 现象

- 只显示 `7d` 不显示 `5h`，并触发错误自动切号。

### 排查方向

- 检查 dashboard row 是否拿到完整窗口。
- 检查切号决策是否正确忽略不完整窗口数据。
- 对比实时 usage 与缓存快照。

## 本地 API 第二轮对话报 input_text 错误

### 现象

- 第一轮请求正常。
- 带上历史上下文后的下一轮请求返回 400。
- 错误文案包含：`Invalid value: 'input_text'. Supported values are: 'output_text' and 'refusal'.`

### 根因

- 本地 API 网关把 assistant 历史消息错误映射成了 `input_text`。
- 上游 Responses/Codex 接口要求 assistant 历史消息使用 `output_text`（或 `refusal`）。

### 处理方式

- 检查 `1.1/package/app/openai_hub_api_gateway.py` 中 `build_codex_chat_request` 的角色映射。
- 确保 user 消息使用 `input_text`，assistant 消息使用 `output_text`。
- 回归测试同步覆盖 user/assistant 两种 content type。

## Claude Code 连接本地 `/v1/messages` 后无输出或先报 `max_output_tokens`

### 现象

- Claude Code 能连上本地 API，但提问后没有正文输出。
- 或者先报：`Unsupported parameter: 'max_output_tokens'`。
- 本地 `/v1/messages` 返回 200，但 `content` 为空，只剩 `usage`。

### 根因

- 网关曾把 Anthropic `max_tokens` 错误透传成 Codex 上游不接受的 `max_output_tokens`。
- 真实 Codex `/responses` 流里会持续发送 `response.output_text.delta`，但 `response.completed.response.output` 可能是空数组。
- 如果桥接层只依赖完成态 `output` 提取文本，Anthropic 响应就会丢正文，Claude Code 看起来像“卡住但没字”。

### 处理方式

- 检查 `1.1/package/app/openai_hub_api_gateway.py`：
  - `build_codex_chat_request`
  - `build_codex_anthropic_request`
  - `collect_stream_response`
  - `stream_anthropic_message_events`
- 不要再向 Codex 上游透传 `max_output_tokens`。
- 当 `response.completed.response.output` 为空但已经收到了 `response.output_text.delta` 时，必须用 delta 文本重建 assistant 输出。
- 修改后重启正在运行的 OpenAI Hub / 本地网关进程；旧进程不会自动加载新代码。

## 状态文件损坏 (Extra data JSON 解析错误)

### 现象

- 启动时报 `初始化失败 - Extra data: line xxx column 1 (char xxxx)`。
- `~/.openaihub/openai-hub-state.json` 文件末尾出现重复残留数据。

### 根因

- `write_json` 函数使用 `open("w")` 直接写入，无原子保护。
- 后台刷新线程并发调用 `write_json` 写同一个文件时，两个文件句柄的缓冲区可能交叉刷盘。
- 结果：前一次写入的残留数据追加到后一次写入的完整 JSON 后面，导致文件损坏。

### 修复 (v1.1.24)

- `write_json` 改为原子写入：先写 `.tmp` → `fsync` → `os.replace()`。
- 即使并发写入，也不会出现半写状态。

### 临时恢复方法

- 用 Python 的 `json.loads(content[:error_pos])` 截取有效部分，重新写入即可恢复。
- 账号数据不在这个文件里（在 `openai-codex-accounts.json`），所以状态文件损坏不会丢账号。

## Hermes 凭据被测试写脏

### 现象

- `~/.hermes/auth.json` 或 `\\wsl$\HermesUbuntu\root\.hermes\auth.json` 里的真实 token 被替换成测试值。
- 常见脏值包括：`bad-access / bad-refresh / bad-account`、`good-access / good-refresh / good-account`。
- `hermes status` 仍可能显示 `OpenAI Codex ✓ logged in`，但真实请求 usage 会返回 `401 Unauthorized`。

### 根因

- 在 `full` 模式接入 Hermes 之后，旧的 `full` 模式测试会额外走 Hermes 分支。
- 如果测试没有把 `HERMES_AUTH_FILE` 显式重定向到临时路径，`probe_hermes_switch_target()`、`switch_alias()`、`apply_profile_to_hermes()` 就会落到真实 Hermes 凭据文件。
- 因为旧测试本来就使用 `good-*` / `bad-*` 这类占位 token，最终会把真实 Hermes auth 写脏。

### 处理方式

- 对所有 `full` / `hermes` 相关测试统一设置临时 `HERMES_AUTH_FILE`，不要只覆盖 Hermes 专用测试。
- 回归测试前先确认测试类默认 Hermes 路径已指向 `TemporaryDirectory()` 下的临时 `auth.json`。
- 如果真实 Hermes 已被写脏：
  1. 先修测试隔离，避免再次污染。
  2. 再从 `~/.openaihub/openai-codex-accounts.json` 里挑选真实账号恢复到 `~/.hermes/auth.json`。
  3. 用 `https://chatgpt.com/backend-api/wham/usage` 实测当前 Hermes token，而不是只看 `hermes status`。

## 2026-04 Claude Code blank first turn

### Symptom

- Claude Code can connect to local `/v1/messages`, but the first turn appears blank.
- `claude -p` may show only `message_start/message_delta/message_stop`.
- In some sessions the next tool-result turn fails with:
  - `400 Unknown parameter: ''input[...].is_error''`

### Root cause

- Claude Code often starts with a `Skill` tool call, not plain text.
- Older bridge logic did not reliably convert Codex function-call streaming events into Anthropic `tool_use` blocks.
- The request mapper also forwarded `tool_result.is_error`, which Codex upstream rejects.

### How to verify

- Capture one real Claude Code request shape. Typical top-level Anthropic payload fields include:
  - `stream: true`
  - `tools`
  - `thinking`
  - `output_config`
  - `context_management`
- Replay that exact payload against the gateway.
- If upstream emits only function-call events, the gateway response must still include:
  - `content_block_start` with `type=tool_use`
  - `content_block_delta` with `input_json_delta`
  - `content_block_stop`

### Fix

- Update `stream_anthropic_message_events` so function-call-only upstream streams become Anthropic `tool_use` blocks.
- Remove `is_error` from `function_call_output` in `build_codex_anthropic_request`.
- Restart the running local gateway after code changes; old background processes do not hot-reload code.

## 2026-04 Claude Code feels weaker on GPT/OpenAI backends

### Symptom

- Claude Code can connect and run, but compared with Codex/OpenCode on the same GPT model it feels less proactive or less willing to continue an agentic task by itself.
- Users may describe this as "the model got dumber after going through the Anthropic gateway".

### Root cause

- `cc-haha` source shows that native Claude Code sends a richer Anthropic request than most third-party proxies preserve:
  - `thinking`
  - `output_config.effort`
  - `output_config.task_budget`
  - `context_management`
  - beta headers
  - prompt-caching markers such as `cache_control`
- `cc-haha`'s own third-party-model docs explicitly say OpenAI/DeepSeek/Ollama paths usually need parameter dropping, lose extended thinking, lose prompt caching, and may have tool-calling compatibility gaps.
- Its desktop/server OpenAI proxy only forwards a reduced subset of Anthropic fields when translating to OpenAI Chat/Responses, so even `cc-haha` itself is not a proof that third-party backends keep full Claude-native behavior.
- Therefore the "weaker" feeling is usually not a single bug in the UI. It is a semantic loss during Anthropic -> OpenAI translation, plus the fact that Claude Code's prompting/loop is tuned for Claude-family backends rather than native OpenAI clients.

### Practical takeaway

- Fix obvious protocol bugs first:
  - blank first turn
  - missing `tool_use`
  - dropped Claude Code effort slider
- After the core protocol bugs are fixed, two safe best-effort improvements on Codex `/responses` are:
  - enable `parallel_tool_calls=true` when Claude Code-compatible requests expose tools
  - prepend a small agentic compatibility instruction for Claude Code-like payloads so GPT-style backends are less likely to stop after merely restating intent
- Another concrete semantic mismatch from `cc-haha` source:
  - Claude Code's adaptive-thinking path defaults to a high-effort mindset when the user has not explicitly changed the effort slider
  - if the bridge drops that and lets Codex choose its own reasoning default, the session can feel noticeably weaker even on the same GPT model
- Another safe best-effort compatibility layer:
  - when Claude Code sends `output_config.task_budget`, inject a short task-budget note into Codex `instructions`
  - this does not reproduce Anthropic-native budgeting semantics, but it preserves part of the pacing signal instead of dropping it entirely
- Real upstream probe result:
  - `chatgpt.com/backend-api/codex/responses` accepts `parallel_tool_calls`
  - but a probe with `stream=false` can fail early with `400 Stream must be set to true`, so feature probes should mimic the real streaming path
- After those are fixed, remaining differences are expected unless the bridge also models more Anthropic-native semantics.
- "Perfectly identical to Anthropic first-party backend" is not realistic on top of Codex `/responses`; the target should be best-effort behavioral compatibility, not byte-identical parity.
