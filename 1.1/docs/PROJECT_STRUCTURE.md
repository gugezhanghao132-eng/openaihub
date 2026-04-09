# OpenAI Hub 1.1 目录结构说明

本文档用于快速理解 `1.1` 的目录职责，便于后续维护和改动。

## 顶层结构

```text
1.1/
├─ .github/                 # GitHub Actions 工作流
│  └─ workflows/
├─ docs/                    # 文档
│  ├─ memory/               # 模块化记忆库（按需加载）
│  ├─ plans/                # 历史/当前计划文档
│  └─ PROJECT_STRUCTURE.md  # 当前文件（结构说明）
├─ npm/                     # npm 发布包目录
│  ├─ bin/                  # CLI 入口脚本（openaihub / OAH）
│  ├─ lib/                  # 安装/运行逻辑
│  ├─ runtime/              # 平台运行时资产（含 windows zip）
│  ├─ scripts/              # npm 安装阶段脚本
│  ├─ package.json          # npm 包元数据与版本
│  ├─ PUBLISHING.md         # 发布说明
│  ├─ README.md             # npm 包说明
│  └─ openaihub-1.1.23.tgz  # 当前最新本地打包产物
├─ package/                 # Python 主程序包
│  ├─ app/                  # 核心业务代码
│  │  ├─ bundled_runtime/
│  │  ├─ openai_launcher.py
│  │  ├─ openclaw_oauth_switcher.py
│  │  ├─ openai_hub_api_gateway.py
│  │  └─ ...
│  ├─ bin/                  # 可执行入口包装
│  └─ version.txt           # 当前版本号
├─ scripts/                 # 安装/卸载与辅助脚本
├─ tests/                   # 单元测试与回归测试
├─ openaihub.spec           # PyInstaller 构建配置
└─ README.md                # 主说明文档
```

## 维护边界

- 仅维护 `1.1`，不再维护 `1.0`/`2.0`。
- 构建缓存、临时日志、调试快照、旧版本 tgz 一律不长期保留。
- 若重新构建 exe 或发布，只在需要时临时生成 `build/dist`，发布后可清理。

## 改动前建议

1. 先看 `AGENTS.md`（记忆路由入口）。
2. 再按任务读取 `1.1/docs/memory/` 对应模块。
3. 再看 `1.1/docs/plans/` 确认当前任务背景。
4. 修改版本发布相关内容时，保持以下文件版本一致：
   - `1.1/package/version.txt`
   - `1.1/npm/package.json`
   - `1.1/README.md`
   - `1.1/npm/PUBLISHING.md`
