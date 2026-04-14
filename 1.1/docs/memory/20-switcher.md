# 20 - 账号池 / 切号 / 配额逻辑

## 负责文件

- `1.1/package/app/openclaw_oauth_switcher.py`

## 核心职责

1. 账号池管理（读写本地状态）
2. 面板配额行构建
3. 自动切号决策
4. 按模式把凭据写回 OpenClAW / OpenCode / Hermes

## 当前关键策略

- 不完整配额窗口（缺 `5h` 或 `7d`）不得触发误切号。
- 当前账号若窗口缺失，优先保持，不直接切走。
- 使用可用完整快照兜底，避免瞬时脏数据导致错误决策。
- 共享账号池统一写入 `~/.openaihub/openai-codex-accounts.json`。
- `switch_alias()` 是总切号入口：
  - `openclaw` 只写 OpenClAW
  - `opencode` 只写 OpenCode
  - `hermes` 只写 Hermes
  - `full` 同时写 OpenClAW + OpenCode + Hermes
- 初始化门禁与切号目标探测必须按当前模式收缩/扩展，不能让单独模式被其他目标阻塞。

## 常见改动

- 新增配额容错规则
- 调整候选排序逻辑
- 修复 token 同步覆盖问题
- 新增或调整目标写回器（如 OpenCode / Hermes）

## 回归检查

- `1.1/tests/test_dashboard_auth_tolerance.py`
- `1.1/tests/test_init_gatekeeping.py`
