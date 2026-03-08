# OpenAI Hub 1.1

OpenAI Hub 是一个面向多账号用户的命令行启动器。

它的核心作用不是替代 OpenClAW 或 OpenCode，而是把你的 GPT 账号整理成一个可管理的号池，然后把这些账号轮换给 OpenClAW 和 OpenCode 使用。

你可以把它理解成一层“账号管理与切换桥接层”：

- 负责登录并保存你的账号
- 负责维护账号池
- 负责切换当前正在使用的账号
- 负责把账号配置同步给 OpenClAW 和 OpenCode
- 负责在进入主界面前先做初始化检测

## 下载或更新

现在推荐使用 npm 安装方式。

```bash
npm install -g openaihub
```

第一次下载用这条命令。

后续更新也还是用这条命令，重复执行即可。

安装完成后，重新打开终端，运行：

```bash
openaihub
```

或者使用缩写：

```bash
OAH
```

## 卸载

```bash
npm uninstall -g openaihub
```

## 版本

```bash
openaihub --version
```

## 这个产品是干什么的

OpenAI Hub 主要解决的是“一个人手里有多个 GPT 账号，需要把这些账号稳定轮换给 OpenClAW 和 OpenCode 去使用”的问题。

它的主要用途是：

- 把多个 GPT 账号组成一个号池
- 登录并保存这些账号
- 查看当前账号状态
- 在账号之间切换
- 在需要的时候自动把账号切给 OpenClAW 和 OpenCode

所以它更像是一个账号池调度器，而不是单独的聊天软件。

## 使用前你需要准备什么

### 1. 必须有 OpenClAW

这是必须项。

因为 OpenAI Hub 的登录链路依赖 OpenClAW 的目录结构和登录数据，所以不管你最后选择的是：

- 综合模式
- OpenCode 模式
- OpenClAW 模式

初始化时都会检查 OpenClAW 相关目录。

程序当前会重点检测这些默认位置：

- OpenClAW 根目录：`~/.openclaw`
- OpenClAW 配置文件：`~/.openclaw/openclaw.json`
- OpenClAW agent 目录：`~/.openclaw/agents`
- 账号池文件：`~/.openclaw/openai-codex-accounts.json`
- 程序状态文件：`~/.openclaw/openai-hub-state.json`

如果缺少下面这些关键内容，程序会报错或阻止进入主页面：

- `~/.openclaw/openclaw.json` 不存在
- `~/.openclaw/agents` 不存在
- `~/.openclaw/agents/*/agent` 目录没有建立
- OpenClAW 配置里缺少程序要求的模型项

默认建议：

- 让 OpenClAW 使用默认用户目录 `~/.openclaw`
- 先正常安装并至少初始化一次 OpenClAW
- 确保它已经生成自己的配置和 agent 目录

### 2. 如果你要用 OpenCode 模式或综合模式，就还需要 OpenCode

这两种模式下，程序还会检查 OpenCode 的配置与认证文件。

当前检测的默认位置是：

- OpenCode 配置文件：`~/.config/opencode/opencode.json`
- OpenCode 凭据文件：`~/.local/share/opencode/auth.json`

如果缺少下面这些关键内容，程序会报错或阻止进入主页面：

- `~/.config/opencode/opencode.json` 不存在
- `~/.local/share/opencode/auth.json` 不存在
- OpenCode 配置里缺少程序要求的模型项

默认建议：

- 让 OpenCode 使用默认目录
- 先正常安装一次 OpenCode
- 至少让 OpenCode 生成它自己的配置文件和认证文件

## 启动模式说明

当你运行 `openaihub` 后，程序不会直接进主页面，而是先弹出模式选择菜单。

### 1. 综合模式

- 检查 OpenClAW
- 检查 OpenCode
- 切号时两边一起切

适合想统一管理两边账号的用户。

### 2. OpenCode 模式

- 检查 OpenClAW
- 检查 OpenCode
- 切号时只切 OpenCode

虽然这个模式只控制 OpenCode，但因为登录链路还是依赖 OpenClAW，所以 OpenClAW 相关目录仍然必须存在。

### 3. OpenClAW 模式

- 只检查 OpenClAW
- 切号时只切 OpenClAW

适合只想管理 OpenClAW 这一侧的用户。

## 平台说明

- npm 安装命令的写法在 Windows 和 macOS 上是一致的
- 当前公开 npm 包已经实际验证的是 Windows x64
- macOS 脚本和打包流程已经准备好
- macOS 公开运行时分发还在继续补充验证

所以现在可以说安装命令形式是通用的，但当前已经实测通过的是 Windows 这一侧。

## 程序运行时会做什么

- npm 包会自动下载运行时
- 运行时文件会放到用户目录
- 当前 Windows 路径是：`%USERPROFILE%/.openaihub/npm-runtime`
- 如果运行时文件丢失，程序下次启动会自动尝试恢复

## 当前状态

- npm 包已发布：`openaihub@1.1.0`
- npm 安装命令已可直接使用
- 已验证命令：`openaihub`、`OAH`、`openaihub --version`
- GitHub Release 的 Windows 资产已发布
- macOS 公开运行时分发仍在补充验证
