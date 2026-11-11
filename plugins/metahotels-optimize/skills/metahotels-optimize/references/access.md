# Access model, tool notes and wp-admin snippets

Read before the first REST, MCP or Chrome call of a pass, and whenever a Chrome result is blocked, a
session expires or a shell command mangles text.

## Access model (no SSH / file access on these sites)

| Need | How |
|---|---|
| Content, Elementor data, menus, posts | the site's `<site>-content` / `<site>-default` MCP server (`mcp-adapter/*` abilities) |
| Plugin list, Elementor Custom Code (`elementor_snippet` → `meta._elementor_code`, `_elementor_location`), other REST | `python -I scripts/wp.py <mcp-server-name> GET "/wp-json/..."`. It reuses the MCP app password from `~/.claude.json`. In Git Bash prefix with `MSYS_NO_PATHCONV=1` |
| LiteSpeed / Elementor settings, purges | user's Chrome (logged into wp-admin) via claude-in-chrome `javascript_tool`. Use the snippets below; never click through dozens of toggles |
| Logged-out measurement | headless Chrome through the skill's `scripts/` (the user's Chrome is logged in; LiteSpeed serves admins unoptimized and uncached) |
| PageSpeed Insights | `PAGESPEED_API_KEY` in the work folder's `.env` (`--init` creates it; a site's own `.env` wins). The user fills it in; never ask for it in the chat |
| Upload optimized media | `python -I scripts/wp_upload.py <mcp-server-name> results.json uploaded.json` (REST, new attachments, originals untouched). Remove only your own unused uploads: `wp.py <server> DELETE "/wp-json/wp/v2/media/<id>?force=true"` |
| Custom post types that are not in REST (offers, rooms, restaurants) | MCP `list-posts` with `post_type` + `meta_key`/`meta_value` (e.g. `_thumbnail_id`), then `update-post` |
| Elementor popup triggers and timing | not in REST or MCP: Elementor editor page in the Chrome tab (snippet below) |

Chrome-tool notes:
- Results containing query strings or token-like values get blocked by the tool. Return counts, booleans or short values.
- A blocked result does not mean the code did not run: the script executed and only its output was withheld. Re-read the state with a second, short call before repeating a write.
- One `javascript_tool` call times out after 45 s. Never wait or loop inside a call; poll with separate calls.
- If the tab group disappears, call `tabs_context_mcp` with `createIfEmpty`.
- The wp-admin session can expire mid-pass (Abar: All-In-One WP Security logs it out). A `fetch()` of an admin page then
  returns the login form with status 200, and a settings POST built from it submits the login form and changes nothing.
  Before every write check that `response.url` does not contain `wp-login` and that the form has the expected field;
  after every write re-read and diff. The password is the user's to type: ask them to log in again.
- With more than one Chrome connected, the extension can fall back to another browser when the logged-in one drops off
  (Shams: "Couldn't determine which page this action targets", then a new tab group in a browser that is not logged
  in). `list_connected_browsers` shows which one is in use; `switch_browser` opens the confirmation in every Chrome
  so the user picks. Never leave a test setting switched on across such a gap: revert before the next long step.
- A re-post of the metahotels-core settings page (it holds API-key fields, rendered empty) was refused by the
  permission system on Shams. Those switches are the user's to tick; verify from the page output afterwards.
  On Gewan (2026-10-15, 2.9.8.9) the Brevo form re-post was allowed: its secret fields are write-only and a blank
  submission keeps the stored key. Check first that the reCAPTCHA site key field is filled (it is rendered back),
  then read every switch back and check Brevo still shows as connected.
- Close your tab at the end.

Shell notes:
- `python -I` hides user site-packages: scripts that need Pillow or fonttools run without `-I` (your own scripts only).
- Heredocs in the Bash tool lose backslashes (`\\n` becomes a newline, `\\(` becomes `\(`). Any script with a regex or escapes goes in a file written with the Write tool, then run.
- Windows text mode turns `\r\n` into `\n`: Elementor snippets and HTML fetched with `curl` keep CRLF, so match with a regex (`\s*`) or open files with `newline=''`.
- Local `curl` sometimes fails instantly with status `000` (DNS blip). Use `--retry 2` and re-fetch any `000` before concluding a page is down.

## Snippets (run with claude-in-chrome `javascript_tool` on any wp-admin page of the site)

Read LiteSpeed settings into `window.__ls` (then print subsets as `key=value` for short values only):
```js
window.__ls={};for(const pg of ['litespeed-cache','litespeed-page_optm','litespeed-cdn','litespeed-general']){const d=new DOMParser().parseFromString(await (await fetch('/wp-admin/admin.php?page='+pg)).text(),'text/html');const o={};d.querySelectorAll('input,select,textarea').forEach(e=>{const n=e.name;if(!n||/nonce|_wp_http|LSCWP|enroll/i.test(n))return;if(e.type==='radio'||e.type==='checkbox'){if(e.hasAttribute('checked'))o[n]=(o[n]!==undefined?o[n]+',':'')+e.value}else if(e.tagName==='SELECT'){const s=e.querySelector('option[selected]');o[n]=s?s.value:''}else o[n]=(e.tagName==='TEXTAREA'?e.textContent:e.getAttribute('value')||'')});window.__ls[pg]=o}
Object.fromEntries(Object.entries(window.__ls).map(([k,v])=>[k,Object.keys(v).length]))
```
Change LiteSpeed settings. This re-posts the whole form so nothing else changes; then verify by re-reading and diffing against `window.__ls`:
```js
async function setLS(pg,changes){const r=await fetch('/wp-admin/admin.php?page='+pg);if(/wp-login/.test(r.url))return 'LOGGED OUT';const d=new DOMParser().parseFromString(await r.text(),'text/html');const f=d.querySelector('#wpbody-content form');if(!f||!f.querySelector('[name="litespeed-submit"]'))return 'NO LITESPEED FORM';for(const [k,v] of Object.entries(changes)){const els=f.querySelectorAll('[name="'+k+'"]');if(!els.length)return 'MISSING '+k;els.forEach(e=>{if(e.type==='radio'||e.type==='checkbox')e.checked=(e.value===v);else e.value=v})}const fd=new FormData(f);fd.set('litespeed-submit',f.querySelector('[name="litespeed-submit"]').value);const pr=await fetch(f.getAttribute('action'),{method:'POST',body:fd});return pr.status+(/wp-login/.test(pr.url)?' LOGGED OUT':'')}
await setLS('litespeed-page_optm',{'optm-css_min':'1','optm-js_min':'1','optm-emoji_rm':'1','optm-css_exc':'static.mirai.com\ncdn.metahotels.ae'});
await setLS('litespeed-cache',{'cache-browser':'1'});
```
Useful keys:
- `litespeed-page_optm`: `optm-css_min`, `optm-css_comb`, `optm-ucss`, `optm-css_async`, `optm-js_min`, `optm-js_comb`, `optm-js_defer` (0 off / 1 defer / 2 delay), `optm-js_defer_exc`, `optm-css_exc`, `optm-html_min`, `optm-emoji_rm`, `optm-ggfonts_async`, `optm-css_comb_ext_inl`, `media-lazy`, `media-iframe_lazy`, `media-add_missing_sizes`, `media-vpi`, `optm-guest_only`, `optm-js_exc`, `optm-js_delay_inc`, `optm-dns_preconnect`, `media-lazy_exc`, `optm-ccss_per_url`, `optm-ccss_sep_posttype`, `optm-ccss_sep_uri` (supports `^/$` for an exact path)
- `litespeed-cache`: `cache-browser`, `cache-ttl_browser`, `cache-mobile`, `object`, `object-kind`

Purge (link types on `litespeed-toolbox`: `purge_frontpage`, `purge_all_lscache`, `purge_all_cssjs`):
```js
const d=new DOMParser().parseFromString(await (await fetch('/wp-admin/admin.php?page=litespeed-toolbox')).text(),'text/html');const a=[...d.querySelectorAll('a')].map(x=>x.getAttribute('href')||'').find(x=>/litespeed_type=purge_frontpage(&|$)/.test(x));(await fetch(a.replace(/&amp;/g,'&'))).status
```
Popup triggers/timing are not in REST or MCP. Open `post.php?post=<popup id>&action=elementor` in the tab, wait for
`elementor.documents.getCurrent()`, then:
```js
const t=elementorPro.modules.popup.displaySettingsTypes;t.triggers.model.set('page_load_delay',30);const o={};jQuery.each(t,(n,x)=>{o[n]=x.model.toJSON({remove:['default']})});elementorPro.ajax.addRequest('popup_save_display_settings',{data:{settings:o}})
```
Elementor setting (same pattern; the form posts to `options.php`): find the form containing `[name="elementor_local_google_fonts"]` on `admin.php?page=elementor-settings`, set the select to `1`, POST `new FormData(form)`, then re-read to verify. Elementor 4.x has no `elementor-tools` page (it errors). Saving through Elementor/MCP regenerates CSS.

LiteSpeed extras:
- Queues and quota: `litespeed-page_optm` has the links `gen_ccss` ("Run CCSS Queue Manually", hidden while a request is
  pending), `clear_q_ccss` and `purge_all_ccss`; the dashboard (`admin.php?page=litespeed`) has "Force cron" per queue
  and `litespeed_type=sync_usage`, which shows the QUIC.cloud usage and the **daily** limit.
- `?LSCWP_CTRL=before_optm` on a front-end URL shows the unoptimized page, which is good for A/B checks.
- `optm-guest_only=1` means logged-in admins never see optimized output.

