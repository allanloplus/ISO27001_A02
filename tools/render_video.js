// 將 index.html 逐格渲染成 MP4（與旁白精準同步）。
// 用法：
//   node tools/render_video.js                 # 完整影片 → video/HR_Security_A6.mp4
//   node tools/render_video.js --shots 12,57.5  # 指定秒數截圖到 build/shots/
// 環境變數：FPS（預設 24）、WORKERS（預設 3）
const { chromium } = require(process.env.PLAYWRIGHT_PATH || 'playwright');
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const FPS = +(process.env.FPS || 24);
const WORKERS = +(process.env.WORKERS || 3);
const URL = 'file://' + path.join(ROOT, 'index.html') + '?record=1';

async function openPage(browser) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto(URL, { waitUntil: 'load' });
  await page.evaluate(() => window.__ready);
  await page.waitForTimeout(300);
  return page;
}

function launch() {
  const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY } : undefined;
  return chromium.launch({ proxy, args: ['--ignore-certificate-errors', '--force-color-profile=srgb'] });
}

async function shots(times) {
  const browser = await launch();
  const page = await openPage(browser);
  const out = path.join(ROOT, 'build', 'shots');
  fs.mkdirSync(out, { recursive: true });
  for (const t of times) {
    // 從前 3 秒逐步推進，讓轉場動畫狀態正確
    for (let x = Math.max(0, t - 3); x < t; x += 1 / 12) await page.evaluate(x => window.__renderAt(x), x);
    await page.evaluate(t => window.__renderAt(t), t);
    const f = path.join(out, `t${String(t).padStart(6, '0')}.png`);
    await page.screenshot({ path: f });
    console.log(f);
  }
  await browser.close();
}

async function segment(browser, i, f0, f1, file) {
  const page = await openPage(browser);
  // 預熱：從段落前 3 秒開始推進（不輸出），確保動畫連續
  const warm = Math.max(0, f0 - 3 * FPS);
  for (let f = warm; f < f0; f++) await page.evaluate(t => window.__renderAt(t), f / FPS);
  const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-tune', 'animation', '-crf', '26', '-pix_fmt', 'yuv420p', '-r', String(FPS), file], { stdio: ['pipe', 'inherit', 'inherit'] });
  const t0 = Date.now();
  for (let f = f0; f < f1; f++) {
    await page.evaluate(t => window.__renderAt(t), f / FPS);
    const buf = await page.screenshot({ type: 'jpeg', quality: 90 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if ((f - f0) % (FPS * 30) === 0) {
      const pct = ((f - f0) / (f1 - f0) * 100).toFixed(1);
      console.log(`[w${i}] ${pct}%  (${((Date.now() - t0) / 1000).toFixed(0)}s)`);
    }
  }
  ff.stdin.end();
  await new Promise((res, rej) => ff.on('close', c => (c ? rej(new Error('ffmpeg ' + c)) : res())));
  await page.close();
}

async function full() {
  const dur = +execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
    path.join(ROOT, 'audio', 'narration.mp3')]).toString().trim();
  const total = Math.ceil(dur * FPS);
  const tmp = path.join(ROOT, 'build', 'seg');
  fs.mkdirSync(tmp, { recursive: true });
  const browser = await launch();
  const per = Math.ceil(total / WORKERS);
  const files = [];
  await Promise.all(Array.from({ length: WORKERS }, (_, i) => {
    const f0 = i * per, f1 = Math.min(total, f0 + per);
    const file = path.join(tmp, `seg${i}.mp4`);
    files.push(file);
    return segment(browser, i, f0, f1, file);
  }));
  await browser.close();
  const list = path.join(tmp, 'list.txt');
  fs.writeFileSync(list, files.map(f => `file '${f}'`).join('\n'));
  fs.mkdirSync(path.join(ROOT, 'video'), { recursive: true });
  const out = path.join(ROOT, 'video', 'HR_Security_A6.mp4');
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', list,
    '-i', path.join(ROOT, 'audio', 'narration.mp3'), '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k',
    '-shortest', '-movflags', '+faststart', out], { stdio: 'inherit' });
  console.log('done →', out);
}

const i = process.argv.indexOf('--shots');
(i > 0 ? shots(process.argv[i + 1].split(',').map(Number)) : full()).catch(e => { console.error(e); process.exit(1); });
