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
