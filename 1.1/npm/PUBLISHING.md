# Publish OpenAI Hub to npm

## Local verification

```bash
cd 1.1/npm
npm pack
npm install -g ./openaihub-1.1.22.tgz
openaihub --version
OAH --version
```

## Publish

```bash
cd 1.1/npm
npm login
npm publish --access public
```

## Trusted publishing alternative

Prepared workflow:

```text
1.1/.github/workflows/publish-npm.yml
```

If you configure npm Trusted Publisher for:

- GitHub user/org: `gugezhanghao132-eng`
- Repository: `openaihub`
- Workflow filename: `publish-npm.yml`

then future publishes can run through GitHub Actions without a long-lived publish token.

## Public install command after publish

```bash
npm install -g openaihub --registry https://registry.npmjs.org
```

## Why the public command must include registry

- Some user machines use a mirror registry such as `npmmirror` by default.
- Mirror versions can lag behind npm official registry, which may install an older `openaihub` version.
- Therefore the public install command must explicitly point to `https://registry.npmjs.org`.

## Platform support

- Windows x64
- macOS arm64
- macOS x64

## Uninstall

```bash
npm uninstall -g openaihub
```
