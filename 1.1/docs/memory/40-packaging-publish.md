# 40 - 打包与发布流程

## 打包相关路径

- PyInstaller 配置：`1.1/openaihub.spec`
- npm 包目录：`1.1/npm/`
- Windows runtime：`1.1/npm/runtime/openaihub-windows.zip`

## 发版同步文件

- `1.1/package/version.txt`
- `1.1/npm/package.json`
- `1.1/README.md`
- `1.1/npm/PUBLISHING.md`

## 最小发布流程

1. 先检查根目录 `token.txt`
2. 确认以下版本文件已同步：
   - `1.1/package/version.txt`
   - `1.1/npm/package.json`
   - `1.1/README.md`
   - `1.1/npm/PUBLISHING.md`
3. `cd 1.1/npm`
4. `npm pack`
5. 本地验证 tarball 安装
6. `npm publish --access public`（官方源）
7. 创建 GitHub Release 并上传 `openaihub-windows.zip`

## 发布后校验

- `npm view openaihub version dist-tags --registry https://registry.npmjs.org`
- 检查 GitHub Release tag 与 assets
- 如本次发布修正了流程或踩坑结论，回写本文件和 `60-ops-troubleshooting.md`

## 经验规则

- 用户安装建议显式指定官方源，规避镜像延迟：
  - `npm install -g openaihub --registry https://registry.npmjs.org`
- 不要依赖临时记忆；发布任务默认先看 `token.txt`，否则视为流程未执行完整。
- 在 Windows PowerShell 下读取 `token.txt` 时，显式按 UTF-8 读取，避免中文冒号或编码差异导致正则抓不到 token。
- npm 发布时优先使用临时 `userconfig` + `npm config set ... --userconfig <path>` 写入 registry 和 `_authToken`；不要临时手写 `.npmrc` 行内容，否则某些 npm 版本会把 token 行误解析成未知配置。

## token.txt 约定

- 位置：仓库根目录 `token.txt`
- 用途：保存 npm / GitHub 发布凭据，仅本机使用
- 要求：发布前先确认文件存在，再读取并执行发布
