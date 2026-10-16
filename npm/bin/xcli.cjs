#!/usr/bin/env node
'use strict';

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

if (process.platform !== 'win32' || process.arch !== 'x64') {
  console.error('XCLI npm package currently supports Windows x64 only.');
  process.exit(1);
}

const executable = path.join(__dirname, '..', 'native', 'xcli.exe');
if (!fs.existsSync(executable)) {
  console.error('XCLI executable is missing. Install the .tgz package from GitHub Releases.');
  process.exit(1);
}

const child = spawn(executable, process.argv.slice(2), { stdio: 'inherit', shell: false });
// The child shares the console and receives Ctrl+C itself. Keep the wrapper alive
// until it has restored terminal state and flushed its output.
process.on('SIGINT', () => {});
process.on('SIGTERM', () => child.kill('SIGTERM'));
child.on('error', () => {
  console.error('Unable to start XCLI. Reinstall the package or check file permissions.');
  process.exitCode = 1;
});
child.on('exit', (code, signal) => {
  process.exitCode = code === null ? (signal === 'SIGINT' ? 130 : 1) : code;
});
