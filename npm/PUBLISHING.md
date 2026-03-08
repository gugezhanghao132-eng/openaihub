# Publish OpenAI Hub to npm

## Local verification

```bash
cd 1.1/npm
npm pack
npm install -g ./openaihub-1.1.2.tgz
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
npm install -g openaihub
```

## Platform support

- Windows x64 only for the current public package

## Uninstall

```bash
npm uninstall -g openaihub
```
