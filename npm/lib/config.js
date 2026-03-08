'use strict';

const os = require('node:os');
const path = require('node:path');

const packageRoot = path.resolve(__dirname, '..');
const runtimeRoot = path.join(os.homedir(), '.openaihub', 'npm-runtime');
const bundledRuntimeRoot = path.join(packageRoot, 'runtime');

const packageInfo = require(path.join(packageRoot, 'package.json'));

function getPlatformConfig() {
  const platform = process.platform;
  const arch = process.arch;

  if (platform === 'win32' && arch === 'x64') {
    return {
      assetName: 'openaihub-windows.zip',
      assetDownloadUrl: `https://github.com/gugezhanghao132-eng/openaihub/releases/download/${getTagName()}/openaihub-windows.zip`,
      executableRelativePath: path.join('openaihub.exe'),
      extractKind: 'zip',
      runtimeKey: 'win32-x64'
    };
  }

  throw new Error(`OpenAI Hub npm package does not support ${platform}-${arch} yet.`);
}

function getTagName() {
  return `v${packageInfo.version}`;
}

module.exports = {
  owner: 'gugezhanghao132-eng',
  repo: 'openaihub',
  packageName: packageInfo.name,
  packageVersion: packageInfo.version,
  packageRoot,
  bundledRuntimeRoot,
  runtimeRoot,
  getTagName,
  getPlatformConfig
};
