'use strict';

const { ensureInstalled } = require('../lib/install');

ensureInstalled()
  .catch((error) => {
    process.stderr.write(`[OpenAI Hub] postinstall warning: ${error.message}\n`);
    process.stderr.write('[OpenAI Hub] The runtime will be downloaded automatically on first launch.\n');
  });
