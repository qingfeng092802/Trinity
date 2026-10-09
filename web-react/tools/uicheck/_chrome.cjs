/* 共享：uicheck 系列脚本的 Chrome 可执行文件路径解析（单一入口）。

   为什么抽出来：之前每个脚本各写一份，脱敏时漏改就会出现
   「写死本机用户名」的路径泄漏；统一入口后只需改这一处。

   解析顺序：
     1. 环境变量 CHROME / CHROME_PATH —— 推荐方式，本机路径不该写进仓库
     2. 各平台常见安装位置 —— 只探系统级公共路径，不含任何本机用户名
     3. 都没有就抛出明确错误，避免 Playwright 报出含本机路径的堆栈
*/
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

function resolveChrome() {
  const env = process.env.CHROME || process.env.CHROME_PATH;
  const local = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
  const candidates = [
    env,
    path.join(local, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  ].filter(Boolean);
  const hit = candidates.find((c) => fs.existsSync(c));
  if (!hit) {
    throw new Error(
      '找不到 Chrome：设 CHROME=<可执行文件路径>（本机路径不该写进仓库，这里只探常见位置）'
    );
  }
  return hit;
}

module.exports = { resolveChrome };
