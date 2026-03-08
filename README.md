# OpenAI Hub

OpenAI Hub is a Windows-first command-line product page for installing and running the 1.1 launcher with mode selection.

## Install / Update (Windows)

```powershell
irm https://raw.githubusercontent.com/gugezhanghao132-eng/openaihub/main/scripts/install.ps1 | iex
```

After install, reopen terminal and run:

```powershell
openaihub
```

or:

```powershell
OAH
```

## Uninstall (Windows)

```powershell
irm https://raw.githubusercontent.com/gugezhanghao132-eng/openaihub/main/scripts/uninstall.ps1 | iex
```

## Version

```powershell
openaihub --version
```

## Startup Modes

- `综合模式`: check OpenClAW + OpenCode, switch both
- `OpenCode 模式`: check OpenClAW + OpenCode, switch OpenCode only
- `OpenClAW 模式`: check OpenClAW only, switch OpenClAW only

## Notes

- Windows installer bundles the runtime and launcher.
- The product still expects host tools like OpenClAW / OpenCode to be installed based on the selected mode.
- If required host software is missing, the app blocks entry and tells the user what to install.

## Files

- `scripts/install.ps1` - Windows install / update
- `scripts/uninstall.ps1` - Windows uninstall
- `scripts/install.sh` - macOS install scaffold
- `scripts/uninstall.sh` - macOS uninstall scaffold
- `scripts/build-macos.sh` - macOS packaging scaffold
