# 30 - 本地 API 网关

## 负责文件

- `1.1/package/app/openai_hub_api_gateway.py`

## 当前职责

1. 提供本地 OpenAI 兼容网关。
2. 提供本地 Anthropic Messages 兼容网关。
3. 复用现有账号池、自动切号、Token 刷新和模型探测逻辑。
4. 统一把本地请求转成 Codex 上游 `/responses` 请求。

## 当前接口面

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/messages`

## 认证规则

- OpenAI 兼容请求继续支持 `Authorization: Bearer <apiKey>`。
- Anthropic 兼容请求同时支持 `Authorization: Bearer <apiKey>` 和 `x-api-key: <apiKey>`。
- `/v1/messages` 需要 `anthropic-version` 请求头，缺失时返回 Anthropic 风格错误体。
- API key 仍然走本地状态文件热更新，不需要重启网关。

## Anthropic -> Codex 映射规则

- `system` -> `instructions`
- `messages[].content[type=text]` -> `input_text` / `output_text`
- user `messages[].content[type=image]` -> Responses `input_image`
- assistant `tool_use` -> `function_call`
- user `tool_result` -> `function_call_output`
- `tools[].input_schema` -> Codex `tools[].parameters`
- `tool_choice`
  - `auto` -> `auto`
  - `none` -> `none`
  - `any` -> `required`
  - `tool` -> 强制指定函数名
- `max_tokens` 当前不再向 Codex 上游透传，因为 `/responses` 实测会对 `max_output_tokens` 返回 400
- `thinking.budget_tokens` 或显式 `reasoning_effort` -> `reasoning.effort`

## 推理强度规则

- 目标是把 Claude / Anthropic 入口收到的思考强度稳定映射到 Codex 的推理档位。
- 当前保留 Codex 档位：`low`、`medium`、`high`、`xhigh`。
- 如果调用方直接传 `reasoning_effort`，优先使用该值。
- 如果调用方传 Anthropic `thinking.budget_tokens`，则按预算映射到对应 effort。
- `gpt-5.3-codex` 不接受 `none`，需要在映射时做校验。

## Anthropic 返回规则

- 非流式 `/v1/messages` 返回 Anthropic `message` 对象。
- 文本输出映射成 `content[type=text]`。
- 函数调用映射成 `content[type=tool_use]`。
- `stop_reason` 在出现工具调用时返回 `tool_use`，否则返回 `end_turn`。
- `usage` 统一转成 `input_tokens` / `output_tokens` / `total_tokens`。

## Anthropic 流式规则

- 网关输出 Anthropic 风格 SSE 事件：
  - `message_start`
  - `content_block_start`
  - `content_block_delta`
  - `content_block_stop`
  - `message_delta`
  - `message_stop`
- 文本块按完整文本块输出，保证最终文本与完成态一致。
- `tool_use` 以标准内容块形式输出，工具入参通过 `input_json_delta` 发出。
- 当前实现偏“兼容优先”，事件粒度可能比上游 Codex delta 更粗。

## 状态与缓存

- 模型列表继续做动态探测，并带 TTL 缓存。
- 新增 Anthropic `tool_use_id -> call_id` 本地短 TTL 缓存，用于后续工具环路对齐。

## 修改这里时必须同步检查

- `1.1/tests/test_local_api_gateway.py`
- `1.1/tests/test_api_commands.py`
- `1.1/README.md` 的“本地 API 功能”部分

## 已知边界

- 这是 Anthropic Messages 兼容层，不是 Anthropic 原生后端。
- 不提供 Anthropic prompt caching 语义。
- 不模拟 Anthropic 私有/内建 server tools；当前只桥接通用函数工具调用。
- 真正的工具能力上限仍取决于 Codex 上游 `/responses` 的工具能力与账号状态。
- `max_tokens` 目前不会硬性限制上游输出；这是为了兼容当前 Codex `/responses` 参数约束。

## 2026-04 Claude Code Notes

- Do not forward Anthropic `max_tokens` as Codex `max_output_tokens`; upstream `/responses` returns HTTP 400 for that field.
- Do not forward `tool_result.is_error` into Codex `function_call_output`; upstream `/responses` rejects unknown `is_error`.
- Claude Code effort slider is sent as `output_config.effort`, not only `reasoning_effort`.
- Map Claude Code `low/medium/high/xhigh` directly to Codex `reasoning.effort`.
- Map Claude Code `max` down to Codex `xhigh` in this gateway, because the gateway currently treats `xhigh` as the highest supported Codex reasoning tier.
- When Claude Code sends `thinking.type=adaptive` without an explicit `output_config.effort`, map it to Codex `reasoning.effort=high` instead of falling through to the upstream provider default.
- Claude Code can start with a tool call instead of plain text. In that case upstream may emit only:
  - `response.output_item.added`
  - `response.function_call_arguments.delta`
  - `response.function_call_arguments.done`
  - `response.output_item.done`
  - `response.completed`
- The Anthropic bridge must still emit `content_block_start/delta/stop` with `type=tool_use` for that sequence, otherwise Claude Code shows a blank turn and cannot continue the tool loop.
- The Anthropic bridge must never stop an assistant turn without at least one content block. If Codex `/responses` completes with empty `output` and no text/tool call, emit a minimal text block before `message_delta stop_reason=end_turn`; otherwise cc-haha / Claude Code can show `[dec_diagnostic] result_type=assistant last_content_type=none stop_reason=end_turn`.
- Claude Code / cc-haha can send screenshots as Anthropic `image` content blocks. The request mapper must convert base64 image sources to Responses `input_image.image_url` data URLs, otherwise `/v1/messages` returns `unsupported anthropic content block: image`.
- `cc-haha` source confirms that native Claude Code requests carry more than plain `messages/tools/thinking`, including `output_config`, `context_management`, beta headers, prompt-caching markers, and task-budget metadata.
- This gateway currently preserves the core cross-provider pieces that matter most for Codex compatibility:
  - `system` / `messages`
  - `tools` / `tool_choice`
  - `tool_use` / `tool_result`
  - Claude Code `output_config.effort`
- For Claude Code-like payloads that include `output_config` / `context_management`, the gateway now also:
  - adds a small Claude-Code-specific agentic compatibility preamble ahead of user/system instructions
  - injects a best-effort task-budget note into `instructions` when Claude Code sends `output_config.task_budget`
  - sets OpenAI `/responses` `parallel_tool_calls=true` when tools are present
- This gateway does not yet emulate Anthropic-native prompt caching, `context_management`, or `output_config.task_budget` semantics on the Codex side.
- As a result, this bridge can get close to Claude Code behavior, but it cannot be a bit-for-bit replacement for Anthropic first-party backend behavior.
