// usage (from the work folder): node <skill>/scripts/md-pdf.js [file.md ...] [--shots=dir]
// Prints each Markdown file as a PDF next to it (A4 portrait). Without a file it builds the two owner documents in
// the current folder, score-vs-experience.md and optimization-results.md. Run it after every change to either one.
// It handles only the Markdown those files use: #, ## and ### headings, paragraphs, "- " and "1. " lists with wrapped lines,
// pipe tables, **bold** and `code`.
// --shots=dir also saves <name>-pageN.png of every PDF page there, to look at the result (the Read tool cannot open
// PDFs on this machine: no pdftoppm).
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const pos = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const shotsArg = process.argv.find((a) => a.startsWith('--shots='));
const shots = shotsArg ? path.resolve(shotsArg.slice(8)) : null;
const files = (pos.length ? pos : ['score-vs-experience.md', 'optimization-results.md'])
  .map((f) => path.resolve(f));

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inline = (s) => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
const cells = (l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());

function toHtml(src) {
  const lines = fs.readFileSync(src, 'utf8').split(/\r?\n/);
  let body = '';
  let title = '';
  for (let i = 0; i < lines.length;) {
    const l = lines[i];
    if (!l.trim()) { i++; continue; }
    const h = l.match(/^(#{1,3})\s+(.*)$/);
    if (h) {
      if (h[1].length === 1 && !title) title = h[2];
      body += `<h${h[1].length}>${inline(h[2])}</h${h[1].length}>\n`;
      i++;
      continue;
    }
    if (l.startsWith('|')) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith('|')) rows.push(cells(lines[i++]));
      const head = rows[0].map((c) => `<th>${inline(c)}</th>`).join('');
      const rest = rows.slice(2).map((r) => '<tr>' + r.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('\n');
      // "Change | number | visitor | decision" tables get the wide third column; other tables share the width
      const kind = (rows[0][0] === 'Change' ? 'cases' : 'cols-' + rows[0].length) + (rows[0][0] === '#' ? ' numbered' : '');
      body += `<table class="${kind}"><thead><tr>${head}</tr></thead><tbody>\n${rest}\n</tbody></table>\n`;
      continue;
    }
    const item = /^(- |\d+\. )/;
    if (item.test(l)) {
      const tag = l.startsWith('- ') ? 'ul' : 'ol';
      const items = [];
      while (i < lines.length && (item.test(lines[i]) || /^\s+\S/.test(lines[i]))) {
        const m = lines[i].match(item);
        if (m) items.push(lines[i].slice(m[0].length)); else items[items.length - 1] += ' ' + lines[i].trim();
        i++;
      }
      body += `<${tag}>` + items.map((t) => `<li>${inline(t)}</li>`).join('\n') + `</${tag}>\n`;
      continue;
    }
    let para = '';
    while (i < lines.length && lines[i].trim() && !/^(#{1,3}\s|\||- |\d+\. )/.test(lines[i])) para += (para ? ' ' : '') + lines[i++].trim();
    body += `<p${/^(Sources?|Last updated):/.test(para) ? ' class="meta"' : ''}>${inline(para)}</p>\n`;
  }
  return { title, body };
}

const css = `
body { font: 10pt/1.45 "Segoe UI", Arial, sans-serif; color: #1c1f23; margin: 0; }
h1 { font-size: 21pt; line-height: 1.2; margin: 0 0 8pt; letter-spacing: -0.01em; }
h2 { font-size: 13pt; line-height: 1.25; margin: 16pt 0 5pt; padding-top: 11pt; border-top: 1px solid #cfd4da; break-after: avoid; }
h3 { font-size: 10.5pt; line-height: 1.3; margin: 11pt 0 4pt; break-after: avoid; }
p { margin: 0 0 7pt; }
p.meta { color: #5b6470; font-size: 9pt; break-after: avoid; }
ul, ol { margin: 0 0 7pt; padding-left: 14pt; }
ol { padding-left: 18pt; }
li { margin-bottom: 3pt; break-inside: avoid; }
code { font: 8.5pt Consolas, "Courier New", monospace; background: #f1f3f5; padding: 0 2pt; border-radius: 2pt; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 9pt; line-height: 1.4; margin: 4pt 0 8pt; break-inside: avoid; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { text-align: left; font-weight: 600; background: #f1f3f5; border-bottom: 1.5px solid #9aa3ad; padding: 5pt 6pt; }
td { vertical-align: top; padding: 5pt 6pt; border-bottom: 1px solid #dfe3e7; overflow-wrap: anywhere; }
table.cases th:nth-child(1) { width: 19%; } table.cases th:nth-child(2) { width: 26%; } table.cases th:nth-child(3) { width: 36%; } table.cases th:nth-child(4) { width: 19%; }
table.cols-3 th:nth-child(1) { width: 40%; } table.cols-3 th:nth-child(2) { width: 27%; }
table.cols-4 th:nth-child(1) { width: 22%; }
table.numbered th:nth-child(1) { width: 4%; }
`;

(async () => {
  const b = await puppeteer.launch({ executablePath: require('./checks/_lib').CHROME, headless: 'new' });
  for (const src of files) {
    const out = src.replace(/\.md$/i, '') + '.pdf';
    const { title, body } = toHtml(src);
    const footer = '<div style="font:7.5pt \'Segoe UI\',Arial,sans-serif;color:#6b7480;width:100%;padding:0 15mm;display:flex;justify-content:space-between">'
      + `<span>${esc(title)}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>`;
    const p = await b.newPage();
    await p.setContent(`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(title)}</title><style>${css}</style></head><body>${body}</body></html>`);
    await p.pdf({
      path: out, format: 'A4', printBackground: true, displayHeaderFooter: true, headerTemplate: '<span></span>', footerTemplate: footer,
      margin: { top: '16mm', bottom: '18mm', left: '15mm', right: '15mm' },
    });
    await p.close();
    // The page tree root holds the total; the first /Count in the file can be a smaller intermediate node.
    const pages = Math.max(0, ...[...fs.readFileSync(out, 'latin1').matchAll(/\/Count\s+(\d+)/g)].map((m) => Number(m[1])));
    if (shots) {
      for (let n = 1; n <= pages; n++) {
        const v = await b.newPage();
        await v.setViewport({ width: 900, height: 1240, deviceScaleFactor: 1.5 });
        await v.goto('file:///' + out.replace(/\\/g, '/') + '#page=' + n + '&toolbar=0&navpanes=0&view=FitH');
        await new Promise((r) => setTimeout(r, 2500));
        await v.screenshot({ path: path.join(shots, path.basename(out, '.pdf') + '-page' + n + '.png') });
        await v.close();
      }
    }
    console.log(out + '  ' + Math.round(fs.statSync(out).size / 1024) + ' KB, ' + pages + ' pages');
  }
  await b.close();
})();
