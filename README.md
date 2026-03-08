# OpenAI Hub

OpenAI Hub is a command-line launcher for users who manage multiple OpenClAW and OpenCode accounts.

It helps users log in with their own user accounts, manage account rotation, and switch which account is currently active for OpenClAW and OpenCode.

## Install

```bash
npm install -g openaihub
```

After install, open a new terminal and run:

```bash
openaihub
```

or:

```bash
OAH
```

## Update

```bash
npm install -g openaihub
```

## Uninstall

```bash
npm uninstall -g openaihub
```

## Version

```bash
openaihub --version
```

## What OpenAI Hub does

OpenAI Hub is not a replacement for OpenClAW or OpenCode.

It is a launcher and account-switching helper around them.

It helps you:

- initialize the environment before entering the main page
- detect whether the required host apps are installed
- guide you into the correct mode before initialization
- switch the account or config used by OpenClAW and OpenCode
- keep the workflow simple with one command and one mode-selection menu

If a required host app is missing, OpenAI Hub blocks entry and tells the user what needs to be installed first.

## Startup modes

When you run `openaihub`, the launcher first shows a mode selection menu.

### 1. Combined mode

- checks OpenClAW and OpenCode
- switches both sides together
- best for users who want one unified workflow

### 2. OpenCode mode

- checks OpenCode
- still relies on the OpenClAW login path for authentication flow
- switches only the OpenCode side

### 3. OpenClAW mode

- checks OpenClAW only
- switches only the OpenClAW side

## Platform notes

- the npm install command format is the same on Windows and macOS
- the current public npm package is verified on Windows x64
- macOS packaging scripts are prepared and will use the same `npm install -g openaihub` style after the macOS runtime asset is published

## Runtime behavior

- the npm wrapper downloads the packaged runtime automatically
- npm runtime files are stored under the user directory
- current runtime path on Windows: `%USERPROFILE%/.openaihub/npm-runtime`
- if the runtime is missing, `openaihub` will try to restore it automatically on next launch

## Direct Windows installer

For users who want the direct PowerShell installer, the repo still keeps:

- `scripts/install.ps1`
- `scripts/uninstall.ps1`

## Current status

- npm package published: `openaihub@1.1.0`
- Windows npm install verified
- commands verified: `openaihub`, `OAH`, `openaihub --version`
- GitHub release Windows asset published
- macOS runtime distribution is still being prepared for public verification
