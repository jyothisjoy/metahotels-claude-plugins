// Shared settings for the browser tools (scripts/*.js and scripts/checks/*.js). Every tool runs from the site folder.
//   CHROME     Chrome or Chromium to drive: CHROME_PATH, else the usual install path for this OS
//   shots()    folder for screenshots: ./shots (PERF_SHOTS overrides), created on first use
//   site()     site.json of the current folder ({} when absent)
//   sel(name, fallback)   a selector from site.json "selectors", else the fallback (references/site-setup.md)
const fs = require('fs');
const path = require('path');

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const c = {
    win32: [
      'C:/Program Files/Google/Chrome/Application/chrome.exe',
      'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
      path.join(process.env.LOCALAPPDATA || '', 'Google/Chrome/Application/chrome.exe'),
    ],
    darwin: [
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
    ],
    linux: ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium'],
  }[process.platform] || [];
  const hit = c.find((p) => { try { return fs.existsSync(p); } catch (e) { return false; } });
  if (!hit) {
    console.error('Chrome not found: set CHROME_PATH to a Chrome or Chromium executable');
    process.exit(1);
  }
  return hit;
}

exports.CHROME = findChrome();
exports.shots = () => {
  const d = path.resolve(process.env.PERF_SHOTS || 'shots');
  fs.mkdirSync(d, { recursive: true });
  return d;
};
let cache = null;
exports.site = () => {
  if (cache) return cache;
  try { cache = JSON.parse(fs.readFileSync(process.env.SITE_JSON || 'site.json', 'utf8')); } catch (e) { cache = {}; }
  return cache;
};
exports.sel = (name, fallback) => ((exports.site().selectors || {})[name]) || fallback;
