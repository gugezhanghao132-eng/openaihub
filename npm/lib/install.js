'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const https = require('node:https');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const {
  bundledRuntimeRoot,
  legacyRuntimeRoot,
  packageRoot,
  packageVersion,
  runtimeRoot,
  getPlatformConfig,
} = require('./config');

function log(message) {
  process.stdout.write(`[OpenAI Hub] ${message}\n`);
}

function downloadFile(url, targetPath, redirectsRemaining = 5) {
  return new Promise((resolve, reject) => {
    const requestUrl = (currentUrl, redirectsLeft) => {
      const req = https.get(currentUrl, {
        headers: {
          'User-Agent': 'OpenAIHub-npm-installer'
        }
      }, (res) => {
        if (res.statusCode && res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          if (redirectsLeft <= 0) {
            reject(new Error(`Too many redirects while downloading ${url}`));
            res.resume();
            return;
          }
          res.resume();
          requestUrl(res.headers.location, redirectsLeft - 1);
          return;
        }

        if (res.statusCode !== 200) {
          reject(new Error(`Download failed: ${res.statusCode} ${currentUrl}`));
          res.resume();
          return;
        }

        const file = fs.createWriteStream(targetPath);
        res.pipe(file);
        file.on('finish', () => {
          file.close(resolve);
        });
        file.on('error', (error) => {
          file.close(() => fs.rmSync(targetPath, { force: true }));
          reject(error);
        });
      });

      req.setTimeout(30000, () => {
        req.destroy(new Error(`Download timed out: ${currentUrl}`));
      });
      req.on('error', reject);
    };

    requestUrl(url, redirectsRemaining);
  });
}

function runCommand(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: 'inherit',
      windowsHide: true
    });

    child.on('error', reject);
    child.on('exit', (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${command} exited with code ${code}`));
    });
  });
}

async function withRetry(action, attempts, label) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await action();
    } catch (error) {
      lastError = error;
      if (attempt < attempts) {
        log(`${label} failed, retrying (${attempt}/${attempts - 1})...`);
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    }
  }
  throw lastError;
}

async function acquireLock(lockPath, timeoutMs = 60000) {
  const startedAt = Date.now();
  while (true) {
    try {
      return await fsp.open(lockPath, 'wx');
    } catch (error) {
      if (error && error.code === 'EEXIST') {
        if (Date.now() - startedAt >= timeoutMs) {
          throw new Error(`Timed out waiting for install lock: ${lockPath}`);
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
        continue;
      }
      throw error;
    }
  }
}

async function removePathWithRetry(targetPath, attempts = 5, delayMs = 400) {
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      await fsp.rm(targetPath, { recursive: true, force: true });
      return;
    } catch (error) {
      if (!error || !['EBUSY', 'EPERM', 'ENOTEMPTY'].includes(error.code) || attempt === attempts) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, delayMs * attempt));
    }
  }
}

async function extractArchive(archivePath, extractRoot, extractKind) {
  if (extractKind === 'zip' && process.platform === 'win32') {
    await runCommand('powershell.exe', [
      '-NoProfile',
      '-ExecutionPolicy',
      'Bypass',
      '-Command',
      `Expand-Archive -Path '${archivePath.replace(/'/g, "''")}' -DestinationPath '${extractRoot.replace(/'/g, "''")}' -Force`
    ]);
    return;
  }

  if (extractKind === 'tar.gz') {
    await runCommand('tar', ['-xzf', archivePath, '-C', extractRoot]);
    return;
  }

  throw new Error(`Unsupported archive extraction for ${process.platform}: ${extractKind}`);
}

async function ensureLauncherEntrypointsExecutable() {
  if (process.platform === 'win32') {
    return;
  }

  await Promise.all([
    fsp.chmod(path.join(packageRoot, 'bin', 'openaihub.js'), 0o755),
    fsp.chmod(path.join(packageRoot, 'bin', 'OAH.js'), 0o755),
  ]);
}

async function removeLegacyRuntimeRoot() {
  if (legacyRuntimeRoot === runtimeRoot) {
    return;
  }

  await removePathWithRetry(legacyRuntimeRoot);
}

async function copyRuntimePreservingLayout(sourceRoot, targetRoot, extractKind) {
  if (extractKind === 'tar.gz' && process.platform !== 'win32') {
    await runCommand('cp', ['-RP', `${sourceRoot}${path.sep}.`, targetRoot]);
    return;
  }

  await fsp.cp(sourceRoot, targetRoot, { recursive: true, force: true });
}

async function validateRuntimeLayout(runtimeDir, platformConfig) {
  const runtimeExecutablePath = path.join(runtimeDir, platformConfig.executableRelativePath);
  await fsp.access(runtimeExecutablePath, fs.constants.F_OK);

  if (process.platform !== 'win32') {
    await fsp.chmod(runtimeExecutablePath, 0o755);
  }

  if (platformConfig.extractKind !== 'tar.gz') {
    return;
  }

  const pythonShimPath = path.join(runtimeDir, '_internal', 'Python');
  await fsp.lstat(pythonShimPath);
  await fsp.realpath(pythonShimPath);
}

function findExecutable(extractRoot, executableName) {
  const stack = [extractRoot];
  while (stack.length > 0) {
    const current = stack.pop();
    const entries = fs.readdirSync(current, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(fullPath);
        continue;
      }
      if (entry.isFile() && entry.name.toLowerCase() === executableName.toLowerCase()) {
        return path.dirname(fullPath);
      }
    }
  }
  return null;
}

async function ensureInstalled(options = {}) {
  const { quiet = false, force = false } = options;
  const platformConfig = getPlatformConfig();
  const runtimeBaseDir = runtimeRoot;
  const runtimeDir = path.join(runtimeBaseDir, platformConfig.runtimeKey);
  const executablePath = path.join(runtimeDir, platformConfig.executableRelativePath);
  const bundledArchivePath = path.join(bundledRuntimeRoot, platformConfig.assetName);
  const versionMarkerPath = path.join(runtimeDir, 'version.txt');

  if (!force && fs.existsSync(executablePath) && fs.existsSync(versionMarkerPath)) {
    const installedVersion = fs.readFileSync(versionMarkerPath, 'utf8').trim();
    if (installedVersion === packageVersion) {
      return { executablePath, runtimeDir, downloaded: false };
    }
  }

  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), 'openaihub-npm-'));
  const archivePath = path.join(tempRoot, platformConfig.assetName);
  const extractRoot = path.join(tempRoot, 'extract');
  const stageRoot = path.join(tempRoot, 'stage');
  const lockPath = path.join(runtimeRoot, `${platformConfig.runtimeKey}.lock`);
  let lockHandle = null;

  try {
    await ensureLauncherEntrypointsExecutable();
    await fsp.mkdir(runtimeRoot, { recursive: true });
    lockHandle = await acquireLock(lockPath);
    await removeLegacyRuntimeRoot();

    if (!quiet) {
      log(`Preparing OpenAI Hub ${packageVersion} for ${platformConfig.runtimeKey}...`);
    }

    await fsp.mkdir(extractRoot, { recursive: true });
    await fsp.mkdir(stageRoot, { recursive: true });

    if (fs.existsSync(bundledArchivePath)) {
      if (!quiet) {
        log(`Using bundled runtime archive ${platformConfig.assetName}...`);
      }
      await fsp.copyFile(bundledArchivePath, archivePath);
    } else {
      if (!quiet) {
        log(`Downloading ${platformConfig.assetName}...`);
      }
      await withRetry(() => downloadFile(platformConfig.assetDownloadUrl, archivePath), 3, 'Runtime download');
    }

    if (!quiet) {
      log('Extracting runtime...');
    }
    await extractArchive(archivePath, extractRoot, platformConfig.extractKind);

    const extractedRuntimeRoot = findExecutable(extractRoot, path.basename(platformConfig.executableRelativePath));
    if (!extractedRuntimeRoot) {
      throw new Error(`Executable ${platformConfig.executableRelativePath} was not found in downloaded asset.`);
    }

    await copyRuntimePreservingLayout(extractedRuntimeRoot, stageRoot, platformConfig.extractKind);
    await fsp.writeFile(path.join(stageRoot, 'version.txt'), `${packageVersion}\n`, 'utf8');
    await validateRuntimeLayout(stageRoot, platformConfig);
    await removePathWithRetry(runtimeDir);
    await fsp.mkdir(runtimeBaseDir, { recursive: true });
    await fsp.rename(stageRoot, runtimeDir);
    await validateRuntimeLayout(runtimeDir, platformConfig);

    if (!quiet) {
      log('Runtime ready.');
    }

    return { executablePath, runtimeDir, downloaded: true };
  } finally {
    if (lockHandle) {
      await lockHandle.close();
    }
    await fsp.rm(lockPath, { force: true });
    await fsp.rm(tempRoot, { recursive: true, force: true });
  }
}

module.exports = {
  ensureInstalled
};
