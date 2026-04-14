# 10 - 启动与模式分发

## 负责文件

- `1.1/package/app/openai_launcher.py`

## 关注点

1. 启动参数解析
2. 模式判定（full / OpenCode / OpenClAW / Hermes）
3. 版本号展示（与 `package/version.txt` 同源）

## 关键规则

- 模式隔离必须严格，不能互相依赖错误的登录态。
- `full` 模式代表多目标联动，当前包含 OpenCode + OpenClAW + Hermes。
- `opencode` / `openclaw` / `hermes` 三个单独模式必须彼此隔离，只初始化和切换自己负责的目标。
- `--version` 输出必须与发布版本一致。

## 常见改动

- 增加启动选项
- 修复模式误判
- 修复版本显示不一致
- 调整 full 模式覆盖范围或新增独立模式

## 回归检查

- `python 1.1/package/app/openai_launcher.py --version`
- `1.1/tests/test_launcher_variant.py`
