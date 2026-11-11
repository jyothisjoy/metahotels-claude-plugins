# usage: python build-icon-subset.py --font=<fa-solid|elementskit|jkit|huge|happy> <src-dir> <pages-dir> <output-dir> [--list]
# Builds a subset of an addon's icon font that holds only the icons the site's pages use (pattern "icon font of
# several hundred KB on every page"). The site plugin then prints a second @font-face for the same family, after the
# addon's stylesheet, with this file and a unicode-range: icons outside the subset fall back to the full font, so
# nothing breaks when the owner adds an icon; the saving just shrinks until the subset is rebuilt.
# Needs fonttools + brotli (pip install fonttools brotli; run without -I). --list only prints the icons in use.
#   1. Download the stylesheet and the font of the preset into <src-dir> (paths below, under /wp-content/plugins/).
#   2. Save every sitemap URL with crawl.sh (<pages-dir>/<n>.html).
#   3. Run this, then put the printed unicode-range and the byte size of the downloaded font into the site plugin's
#      constants (the plugin guards on that size so an addon update that changes the font switches the subset off),
#      and re-zip. Check the glyphs with checks/diffbox.js: sub-pixel anti-aliasing can differ in a pixel diff.
# Presets (first runs): jkit = Jeg Elementor Kit (Nassima 2026-10-10, 392 KB woff2 -> 25 icons),
#   elementskit = ElementsKit Lite (Shams 2026-10-13, 464 KB woff -> 14 icons, 2.4 KB),
#   fa-solid = Elementor's Font Awesome 5 solid (Khalidia 2026-10-13, inlined as a data URI: one caret).
#   huge, happy = Happy Elementor Addons "Huge Icons" and "Happy Icons" (Al Bahar 2026-10-15).
# Only icons printed as a font count; Elementor's inline SVG icons (e-font-icon-svg) do not use the font.
import glob
import os
import re
import sys

BS = chr(92)
PRESETS = {
    'jkit': {
        'where': 'jeg-elementor-kit/assets/fonts/jkiticon/{jkiticon.css,jkiticon.woff2}',
        'css': 'jkiticon.css', 'font': 'jkiticon.woff2', 'out': 'jkiticon-subset',
        'rule': r'\.(jki-[a-z0-9-]+)::?before\{content:"(?:' + re.escape(BS) + r'([0-9a-f]+)|([^"' + re.escape(BS) + r']))"\}',
        'used': lambda html: re.findall(r'\b(jki-[a-z0-9-]+)', html),
    },
    'huge': {
        'where': 'happy-elementor-addons/assets/fonts/huge-icons/{huge-icons.min.css,huge-icons.woff2}',
        'css': 'huge-icons.min.css', 'font': 'huge-icons.woff2', 'out': 'huge-icons-subset',
        'rule': r'\.(huge-[a-z0-9-]+)::?before\{content:"(?:' + re.escape(BS) + r'([0-9a-f]+)|([^"' + re.escape(BS) + r']))";?\}',
        'used': lambda html: re.findall(r'\b(huge-[a-z0-9-]+)', html),
    },
    'happy': {
        'where': 'happy-elementor-addons/assets/fonts/{style.min.css,happy-icons.woff2}',
        'css': 'style.min.css', 'font': 'happy-icons.woff2', 'out': 'happy-icons-subset',
        'rule': r'\.(hm-[a-z0-9-]+)::?before\{content:"(?:' + re.escape(BS) + r'([0-9a-f]+)|([^"' + re.escape(BS) + r']))";?\}',
        'used': lambda html: re.findall(r'\b(hm-[a-z0-9-]+)', html),
    },
    'elementskit': {
        'where': 'elementskit-lite/modules/elementskit-icon-pack/assets/{css/ekiticons.css,fonts/elementskit.woff}',
        'css': 'ekiticons.css', 'font': 'elementskit.woff', 'out': 'elementskit-subset',
        'rule': r'\.icon\.(icon-[a-z0-9_-]+)::?before\{content:"(?:' + re.escape(BS) + r'([0-9a-f]+)|([^"' + re.escape(BS) + r']))"\}',
        'used': lambda html: [n for cls in re.findall(r'class="([^"]*)"', html) if 'icon' in cls.split()
                              for n in cls.split() if n.startswith('icon-')],
    },
    'fa-solid': {
        'where': 'elementor/assets/lib/font-awesome/{css/all.min.css,webfonts/fa-solid-900.woff2}',
        'css': 'all.min.css', 'font': 'fa-solid-900.woff2', 'out': 'fa-solid-subset',
        'rule': r'\.(fa-[a-z0-9-]+):before\{content:"' + re.escape(BS) + r'([0-9a-f]+)()"\}',
        # solid only: "far"/"fab" icons live in other font files
        'used': lambda html: [n for cls in re.findall(r'<(?:i|span)\b[^>]*class="([^"]*)"', html)
                              if [s for s in cls.split() if s in ('fas', 'fa')] for n in cls.split() if n.startswith('fa-')],
    },
}

font = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--font=')), None)
pos = [a for a in sys.argv[1:] if not a.startswith('--')]
if font not in PRESETS or len(pos) < 3:
    sys.exit('usage: python build-icon-subset.py --font=<%s> <src-dir> <pages-dir> <output-dir> [--list]' % '|'.join(PRESETS))
P = PRESETS[font]
src, pages, out = pos[:3]
only_list = '--list' in sys.argv
print('preset', font, '| download from /wp-content/plugins/' + P['where'])

css = open(os.path.join(src, P['css']), encoding='utf-8').read()
cp = {}
for m in re.finditer(P['rule'], css):
    cp[m.group(1)] = int(m.group(2), 16) if m.group(2) else ord(m.group(3))
print('icons in css', len(cp))
used = {}
for f in glob.glob(os.path.join(pages, '*.html')):
    for n in P['used'](open(f, encoding='utf-8', errors='replace').read()):
        used[n] = used.get(n, 0) + 1
unknown = sorted(u for u in used if u not in cp)
known = {u: c for u, c in used.items() if u in cp}
print('used', len(known), '| classes not in the stylesheet:', unknown[:20])
for u, c in sorted(known.items(), key=lambda x: -x[1]):
    print('  %-28s U+%X  %d uses' % (u, cp[u], c))
if only_list:
    sys.exit(0)

from fontTools import subset  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402

font_path = os.path.join(src, P['font'])
# keep each glyph's stored bounding box: icon fonts such as Happy Addons' store xMin 0 (= left side bearing) for
# outlines that start further right, and renderers place the outline by lsb - xMin, so recalculating the box on
# save moved every Huge Icons glyph 53/1024 em to the left (Al Bahar 2026-10-16)
f = TTFont(font_path, recalcBBoxes=False)
cmap = f.getBestCmap()
print('source bytes', os.path.getsize(font_path), 'glyphs', len(f.getGlyphOrder()), 'cmap', len(cmap))
codes = sorted(cp[u] for u in known)
print('codes missing from the font:', [hex(c) for c in codes if c not in cmap])
opt = subset.Options()
opt.flavor = 'woff2'
opt.layout_features = ['*']
opt.name_IDs = ['*']
opt.notdef_outline = True
opt.hinting = True
s = subset.Subsetter(opt)
s.populate(unicodes=codes)
s.subset(f)
os.makedirs(out, exist_ok=True)
p = os.path.join(out, P['out'] + '.woff2')
f.flavor = 'woff2'
f.save(p)
print('subset', p, os.path.getsize(p), 'bytes')
# placement check: each glyph's xMin and metrics must equal the source's, or the icon draws shifted
F, T = TTFont(font_path), TTFont(p)
fc, tc = F.getBestCmap(), T.getBestCmap()
moved = [hex(c) for c in codes if 'glyf' in F and (F['glyf'][fc[c]].xMin, F['hmtx'][fc[c]]) != (T['glyf'][tc[c]].xMin, T['hmtx'][tc[c]])]
print('glyphs placed differently from the source:', moved or 'none')
print('unicode-range:', ','.join('U+%X' % c for c in codes))
open(os.path.join(out, P['out'] + '.txt'), 'w', encoding='utf-8', newline='\n').write(
    '\n'.join('%s U+%X' % (u, cp[u]) for u in sorted(known)) + '\n')
