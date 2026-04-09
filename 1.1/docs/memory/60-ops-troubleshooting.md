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
