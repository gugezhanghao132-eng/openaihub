# Publish OpenAI Hub to npm

## Local verification

```bash
cd npm
npm pack
npm install -g ./openaihub-1.1.16.tgz
openaihub --version
OAH --version
```

## Publish

```bash
cd npm
npm login
npm publish --access public
```

## Trusted publishing alternative

Prepared workflow:

```text
.github/workflows/publish-npm.yml
```

If you configure npm Trusted Publisher for:

- GitHub user/org: `gugezhanghao132-eng`
- Repository: `openaihub`
- Workflow filename: `publish-npm.yml`

then future publishes can run through GitHub Actions without a long-lived publish token.

## Public install command after publish

```bash
npm install -g openaihub
```

## Platform support

- Windows x64
- macOS arm64
- macOS x64

## Uninstall

```bash
npm uninstall -g openaihub
```
