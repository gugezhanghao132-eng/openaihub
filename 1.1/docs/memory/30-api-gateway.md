# 30 - 本地 OpenAI 兼容 API

## 负责文件

- `1.1/package/app/openai_hub_api_gateway.py`

## 核心能力

1. OpenAI 兼容路由
2. 模型列表返回（动态探测）
3. 流式返回（SSE）
4. 本地 API key 热更新

## 关键规则

- 模型列表不要写死单模型。
- codex 系列模型不能被先验过滤。
- 探测请求参数需与上游兼容，避免误判模型不可用。

## 常见改动

- `/v1/models` 口径修正
- `stream=true` 兼容修复
- API key 刷新逻辑增强
- 多轮对话 assistant 历史消息必须映射为 `output_text`，不能继续沿用 `input_text`

## 回归检查

- `1.1/tests/test_local_api_gateway.py`
- `1.1/tests/test_api_commands.py`
