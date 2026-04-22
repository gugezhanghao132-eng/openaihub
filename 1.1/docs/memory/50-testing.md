# 50 - 测试与验证策略

## 原则

- 改功能后必须补针对性的回归测试。
- 先覆盖实际故障链路，再补一般性 happy path。
- API 网关变更必须同时验证 OpenAI 兼容路径和 Anthropic 兼容路径。

## 本项目常用验证入口

- 启动与模式分发：`1.1/tests/test_launcher_variant.py`
- 账号池 / 切号 / 容错：`1.1/tests/test_dashboard_auth_tolerance.py`
- 启动守门：`1.1/tests/test_init_gatekeeping.py`
- 本地 API 网关：`1.1/tests/test_local_api_gateway.py`
- API 命令层：`1.1/tests/test_api_commands.py`

## 本地 API 网关的最小回归

执行：

```bash
python 1.1/tests/test_local_api_gateway.py -v
```

注意：

- 这个仓库目录名是 `1.1`，不适合直接写成 `python -m unittest 1.1.tests...`。
- 优先按文件路径直接运行测试文件。

## `/v1/messages` 新增覆盖点

- Anthropic messages -> Codex request 转换
- `tool_use` / `tool_result` 工具环路转换
- Codex 输出 -> Anthropic `message` 响应转换
- Anthropic SSE 事件桥接
- `x-api-key` 鉴权
- `anthropic-version` 请求头约束
- `tool_use_id` 状态缓存

## 发布前最小验证清单

1. 相关单测通过。
2. 关键 CLI 命令输出正确，例如 `openaihub --version`。
3. 本地 API 至少验证一次 `GET /v1/models`。
4. 如果改了兼容层，至少验证一次 `POST /v1/chat/completions` 和 `POST /v1/messages`。

## 出现失败时

- 先确认是映射错误、鉴权错误、上游错误，还是流式桥接错误。
- 不要只修表面报错，必须把对应回归用例补上或补全。
- 如果是工具调用问题，优先检查：
  - `build_codex_anthropic_request`
  - `build_anthropic_message_response`
  - `stream_anthropic_message_events`
  - `/v1/messages` 路由分发与鉴权

## 2026-04 real-client check

- For `/v1/messages`, unit tests are necessary but not sufficient.
- Add request-mapping coverage for Claude Code `output_config.effort`, especially `high` and `max`.
- Add request-mapping coverage for:
  - Claude Code `thinking.type=adaptive` with no explicit effort -> Codex `reasoning.effort=high`
  - `parallel_tool_calls` on Claude Code-style Anthropic requests with tools
  - Claude Code `output_config.task_budget` -> best-effort task-budget note in Codex `instructions`
  - Claude-Code-specific agentic compatibility preamble injection
- After changing Anthropic compatibility, run one real Claude Code smoke test:
  - `claude -p "hi" --settings <temp-settings.json> --output-format stream-json --include-partial-messages --verbose`
- Required success criteria:
  - first turn can surface a `tool_use` block when Claude Code invokes `Skill`
  - tool_result round-trip does not trigger upstream 400 errors
  - a later assistant text turn renders non-empty output
- Useful upstream probe:
  - when probing `chatgpt.com/backend-api/codex/responses`, remember this backend expects `stream=true`; probing with `stream=false` can return `400 Stream must be set to true`
