'use strict';

const { spawn } = require('node:child_process');

const { ensureInstalled } = require('./install');

async function main() {
  try {
    const { executablePath } = await ensureInstalled({ quiet: true });
    const child = spawn(executablePath, process.argv.slice(2), {
      stdio: 'inherit',
      windowsHide: false
    });

    child.on('exit', (code, signal) => {
      if (signal) {
        process.kill(process.pid, signal);
        return;
      }
      process.exit(code === null ? 1 : code);
    });

    child.on('error', (error) => {
      process.stderr.write(`[OpenAI Hub] Failed to launch runtime: ${error.message}\n`);
      process.exit(1);
    });
  } catch (error) {
    process.stderr.write(`[OpenAI Hub] ${error.message}\n`);
    process.exit(1);
  }
}

module.exports = {
  main
};
