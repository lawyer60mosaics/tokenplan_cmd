'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const pkg = require(path.join(root, 'package.json'));
const binary = path.join(root, 'dist', 'xcli.exe');

if (process.platform !== 'win32' || process.arch !== 'x64') {
  throw new Error('Build the Windows x64 executable on Windows before packaging.');
}
if (!fs.existsSync(binary)) {
  throw new Error('Missing dist/xcli.exe. Build with PyInstaller before npm pack.');
}
const version = execFileSync(binary, ['--version'], { encoding: 'utf8' }).trim();
if (version !== `TokenPlan CMD ${pkg.version}`) {
  throw new Error(`Executable version does not match npm package ${pkg.version}.`);
}
const target = path.join(__dirname, 'native');
fs.mkdirSync(target, { recursive: true });
fs.copyFileSync(binary, path.join(target, 'xcli.exe'));
console.log(`Bundled ${version} for Windows x64.`);
