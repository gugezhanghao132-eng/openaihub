# OpenAI Hub 1.1

OpenAI Hub 是一个面向多账号用户的命令行启动器。

它的核心作用不是替代 OpenClAW 或 OpenCode，而是把你的 GPT 账号整理成一个可管理的号池，然后把这些账号轮换给 OpenClAW 和 OpenCode 使用。

你可以把它理解成一层“账号管理与切换桥接层”：

- 负责登录并保存你的账号
- 负责维护账号池
- 负责切换当前正在使用的账号
- 负责把账号配置同步给 OpenClAW 和 OpenCode
- 负责在进入主界面前先做初始化检测

## 适合什么人使用

这个工具主要适合下面这类用户：

- 你有多个 GPT 账号，需要轮流给 OpenClAW 或 OpenCode 使用
- 你不想每次都手动改配置、手动替换账号
- 你希望把账号池集中管理，而不是散落在不同目录里
- 你希望进入程序前先自动检查环境，避免进了主界面才发现缺文件

如果你只有一个账号、也不需要切号，那这个工具对你的价值就不会那么大。

## 下载或更新

当前提供三种安装入口：

### 方式一：npm 安装（推荐，最像正式产品）

```bash
npm install -g openaihub
```

第一次下载用这条命令。

后续更新也还是用这条命令，重复执行即可。

适用前提：

- 电脑里已经有 `npm`
- 适合想用最简洁命令的用户

### 方式二：Windows 直装（不想装 npm 时可用）

```powershell
irm https://raw.githubusercontent.com/gugezhanghao132-eng/openaihub/main/scripts/install.ps1 | iex
```

适用前提：

- Windows
- 本机可用 PowerShell
- 能联网访问 GitHub

### 方式三：macOS 直装入口（curl）

```bash
curl -fsSL https://raw.githubusercontent.com/gugezhanghao132-eng/openaihub/main/scripts/install.sh | sh
```

适用前提：

- macOS
- 本机可用 `curl` 和 `sh`

说明：

- 这是 macOS 的直装入口形式
- 当前仓库已经提供这条安装入口对应的脚本
- macOS 运行时公开分发仍在继续补充验证，所以当前最稳的公开方式仍然是先看 npm 方案和 Windows 方案

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

## 快速开始

如果你是第一次使用，推荐按这个顺序来：

### 第一步：确认电脑里已经有 npm

请先在终端里执行：

```bash
npm -v
```

如果这条命令能正常输出版本号，说明你已经有 npm，可以直接安装 OpenAI Hub。

如果这条命令报错，说明你的电脑里还没有 npm。你需要先安装 Node.js（安装 Node.js 时通常会一起带上 npm），然后才能使用：

```bash
npm install -g openaihub
```

### 第二步：安装 OpenAI Hub

推荐优先使用：

```bash
npm install -g openaihub
```

如果你不想装 npm，也可以：

- Windows 用 `irm ... | iex`
- macOS 用 `curl ... | sh`

### 第三步：确认 OpenClAW / OpenCode 已经生成默认目录

在你第一次正式使用前，建议至少先让对应的软件自己运行过一次。

原因很简单：OpenAI Hub 不是凭空生成你所有宿主软件环境，它会去检查这些软件已经存在的默认目录和配置文件。

### 第四步：启动 OpenAI Hub

```bash
openaihub
```

或：

```bash
OAH
```

### 第五步：选择模式

启动后，先选模式，再初始化，再进入主页面。

## 模式对照表

| 模式 | 会检测什么 | 会切换什么 | 适合谁 |
| --- | --- | --- | --- |
| 综合模式 | OpenClAW + OpenCode | 两边一起切 | 两边都在用，想统一管理 |
| OpenCode 模式 | OpenClAW + OpenCode | 只切 OpenCode | 主要用 OpenCode，但仍依赖 OpenClAW 登录链路 |
| OpenClAW 模式 | OpenClAW | 只切 OpenClAW | 只想管理 OpenClAW |

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

## 依赖说明

这个问题你刚才问得很关键，答案是：

### 1. 要用 npm 安装，电脑里必须先有 npm

不是“任何电脑都可以直接运行 npm 安装命令”。

必须满足：

- 这台电脑里已经安装了 Node.js / npm
- 终端里 `npm -v` 能正常执行

只要满足这一点，就可以直接执行：

```bash
npm install -g openaihub
```

### 2. 除了 npm，本工具当前不再要求你额外安装 Python

至少在当前公开验证通过的 Windows npm 包里，运行时会自动下载，用户不需要额外再自己装 Python 才能启动 OpenAI Hub。

### 3. 但宿主软件依然要有

OpenAI Hub 只是账号池启动器和切号工具，不会替你安装 OpenClAW 和 OpenCode 本体。

也就是说：

- npm 负责把 OpenAI Hub 装到你的电脑里
- OpenAI Hub 负责初始化检查、账号池管理、切号和同步
- OpenClAW / OpenCode 仍然需要你自己本地已经有，或者至少已经运行过并生成默认目录

## 程序运行时会做什么

- npm 包会自动下载运行时
- 运行时文件会放到用户目录
- 当前 Windows 路径是：`%USERPROFILE%/.openaihub/npm-runtime`
- 如果运行时文件丢失，程序下次启动会自动尝试恢复

## 常见报错与原因

### 1. `npm` 命令不存在

原因：电脑里还没有安装 npm。

处理方法：先安装 Node.js，然后重新打开终端，再执行：

```bash
npm install -g openaihub
```

### 2. 找不到 OpenClAW 配置文件

常见表现：程序提示找不到 `~/.openclaw/openclaw.json`。

原因：

- OpenClAW 还没有安装
- 或者安装了但还没正常初始化过
- 或者你把目录放到了非默认位置，导致当前版本检测不到

处理方法：

- 先确认 OpenClAW 已安装
- 先至少运行一次 OpenClAW，让它生成默认目录
- 确保 `~/.openclaw/openclaw.json` 存在

### 3. 找不到 OpenClAW agent 目录

常见表现：程序提示找不到 `~/.openclaw/agents` 或 `~/.openclaw/agents/*/agent`。

原因：OpenClAW 目录还没有完整初始化。

处理方法：先运行 OpenClAW，让它把 agent 相关目录生成出来。

### 4. 找不到 OpenCode 配置文件

常见表现：程序提示找不到 `~/.config/opencode/opencode.json`。

原因：

- 你当前选择的是综合模式或 OpenCode 模式
- 但 OpenCode 还没有安装，或者还没有生成配置文件

处理方法：先安装并运行一次 OpenCode，确认配置文件已生成。

### 5. 找不到 OpenCode 凭据文件

常见表现：程序提示找不到 `~/.local/share/opencode/auth.json`。

原因：OpenCode 状态目录还没有生成，或者你还没有完成它的登录/初始化流程。

处理方法：先让 OpenCode 生成自己的状态目录和认证文件。

### 6. 明明只想用 OpenCode，为什么还要求 OpenClAW

原因：当前版本里，OpenCode 模式虽然只切 OpenCode，但登录链路仍然依赖 OpenClAW 那一侧的数据结构和环境，所以初始化时还是会检查 OpenClAW。

这不是文档写错，而是当前实现就是这样。

## 当前状态

- npm 包已发布：`openaihub@1.1.0`
- npm 安装命令已可直接使用
- 已验证命令：`openaihub`、`OAH`、`openaihub --version`
- GitHub Release 的 Windows 资产已发布
- macOS 公开运行时分发仍在补充验证
