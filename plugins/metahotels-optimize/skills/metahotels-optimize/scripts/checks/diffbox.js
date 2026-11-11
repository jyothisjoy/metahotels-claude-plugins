// usage: node diffbox.js <normal.png> <variant.png> [out-prefix]
// Where do two screenshots differ? Prints the bounding box of each group of differing rows and, with an
// out-prefix, writes a side-by-side crop (normal | variant, 3x) of each group so the difference can be looked at.
const fs = require('fs');
const { PNG } = require('pngjs');
const [aFile, bFile, prefix] = process.argv.slice(2);
const a = PNG.sync.read(fs.readFileSync(aFile));
const b = PNG.sync.read(fs.readFileSync(bFile));
const w = Math.min(a.width, b.width), h = Math.min(a.height, b.height);
console.log('sizes', a.width + 'x' + a.height, b.width + 'x' + b.height);
const rows = [];
for (let y = 0; y < h; y++) {
  let x0 = -1, x1 = -1, n = 0;
  for (let x = 0; x < w; x++) {
    const i = (a.width * y + x) * 4, j = (b.width * y + x) * 4;
    if (Math.abs(a.data[i] - b.data[j]) + Math.abs(a.data[i + 1] - b.data[j + 1]) + Math.abs(a.data[i + 2] - b.data[j + 2]) > 30) {
      if (x0 < 0) x0 = x;
      x1 = x; n++;
    }
  }
  if (n) rows.push({ y, x0, x1, n });
}
const groups = [];
for (const r of rows) {
  const g = groups[groups.length - 1];
  if (g && r.y - g.y1 <= 12) { g.y1 = r.y; g.x0 = Math.min(g.x0, r.x0); g.x1 = Math.max(g.x1, r.x1); g.n += r.n; } else groups.push({ y0: r.y, y1: r.y, x0: r.x0, x1: r.x1, n: r.n });
}
groups.forEach((g, k) => {
  console.log(`group ${k}: x ${g.x0}-${g.x1}, y ${g.y0}-${g.y1}, ${g.n} px`);
  if (!prefix) return;
  const pad = 24, S = 3;
  const cx = Math.max(0, g.x0 - pad), cy = Math.max(0, g.y0 - pad);
  const cw = Math.min(w - cx, g.x1 - g.x0 + 2 * pad), ch = Math.min(h - cy, g.y1 - g.y0 + 2 * pad);
  const out = new PNG({ width: (cw * 2 + 4) * S, height: ch * S });
  out.data.fill(255);
  [a, b].forEach((img, side) => {
    for (let y = 0; y < ch * S; y++) for (let x = 0; x < cw * S; x++) {
      const si = (img.width * (cy + Math.floor(y / S)) + cx + Math.floor(x / S)) * 4;
      const di = (out.width * y + x + side * (cw + 4) * S) * 4;
      out.data[di] = img.data[si]; out.data[di + 1] = img.data[si + 1]; out.data[di + 2] = img.data[si + 2]; out.data[di + 3] = 255;
    }
  });
  fs.writeFileSync(`${prefix}-${k}.png`, PNG.sync.write(out));
});
