"""Lint and zip a site plugin for upload: python -I <skill>/scripts/zip-plugin.py <plugin-dir> [out.zip]

Runs `php -l` on every .php file (PHP from PHP_BIN, else php on PATH, else XAMPP's C:/xampp/php/php.exe), then writes the
zip with forward-slash paths and the plugin folder as its root. PowerShell 5.1 Compress-Archive writes backslashes,
which break on the Linux hosts these sites run on. Default output: <plugin-dir>.zip next to the folder.
"""
import os
import shutil
import subprocess
import sys
import zipfile

src = os.path.abspath(sys.argv[1].rstrip('/\\'))
out = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else src + '.zip'
php = os.environ.get('PHP_BIN') or shutil.which('php') or ('C:/xampp/php/php.exe' if os.path.exists('C:/xampp/php/php.exe') else None)
name = os.path.basename(src)
files = []
for root, _, fs in os.walk(src):
    for f in sorted(fs):
        if f.startswith('.') or f.endswith(('.zip', '.bak')):
            continue
        files.append(os.path.join(root, f))
bad = 0
for f in files:
    if f.endswith('.php'):
        if not php:
            sys.exit('no php binary found: set PHP_BIN')
        r = subprocess.run([php, '-l', f], capture_output=True, text=True)
        print(r.stdout.strip() or r.stderr.strip())
        bad += r.returncode != 0
if bad:
    sys.exit('php -l failed: not zipped')
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in files:
        arc = name + '/' + os.path.relpath(f, src).replace(os.sep, '/')
        z.write(f, arc)
        print('  ', arc, os.path.getsize(f))
with zipfile.ZipFile(out) as z:
    assert all('\\' not in n for n in z.namelist())
print('wrote', out, os.path.getsize(out), 'bytes')
