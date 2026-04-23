# OpenAI Hub npm package

Install globally:

```bash
npm install -g openaihub --registry https://registry.npmjs.org
```

If your machine uses a mirror registry, installing without `--registry` may pull an older mirrored version instead of the latest npm official release.

Current support: Windows x64, macOS arm64, macOS x64.

Runtime location after install:

```text
~/.openaihub/npm-runtime
```

Then run:

```bash
openaihub
```

Or:

```bash
OAH
```

What happens after startup:

- first choose a mode
- then enter the main menu
- the local API gateway starts automatically after the main menu is ready

Local API notes:

- default listen address: `127.0.0.1`
- API config lives in `~/.openaihub/local-api.json`
- API key can be viewed or changed from the `API 配置` menu
- current endpoints:
  - `GET /v1/models`
  - `POST /v1/chat/completions`
  - `POST /v1/messages`
- `/v1/messages` supports Claude Code / Claude Haha screenshots via Anthropic `image` content blocks.

The local API follows the current account selected in OpenAI Hub, and can reuse the existing refresh / auto-switch logic.

Uninstalling the npm package removes the launcher/runtime entrypoints, but keeps user data in `~/.openaihub` so saved accounts and config are not lost by mistake.
