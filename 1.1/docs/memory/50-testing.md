# 50 - 测试与验证策略

## 原则

- 改动后必须做针对性回归，不只看“能跑”。
- 先测受影响模块，再补关键链路测试。

## 常用测试集合

- 启动与模式：`test_launcher_variant.py`
- 切号与配额：`test_dashboard_auth_tolerance.py`、`test_init_gatekeeping.py`
- API 网关：`test_local_api_gateway.py`、`test_api_commands.py`
- Hermes 模式回归也并入 `test_launcher_variant.py` 与 `test_init_gatekeeping.py`

## 最小验证清单

1. 相关单测通过
2. 关键命令输出正确（如 `--version`）
3. 发布后做线上版本查询校验
4. 模式新增/扩展时，至少验证单独模式边界和 full 联动边界都没破

## 出现失败时

- 先定位根因，再修复；避免盲改。
- 新增回归测试覆盖真实故障场景。
- 没有 `pytest` 时，可先跑 `python -m unittest tests.test_launcher_variant tests.test_init_gatekeeping` 作为最小回归。 
