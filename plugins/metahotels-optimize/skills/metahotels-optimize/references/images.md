# Step 2b: site-wide image re-encode

The first change on every site, straight after the audit and baseline, without asking (owner, 2026-10-14). The
other batches are then measured on the compressed images. New attachments only: originals stay in the Media
Library untouched, so deleting the new attachments (and reverting the repoints) is the rollback.
Commands run from the site folder; `$S` is the skill's `scripts/` folder; `<server>` is site.json `mcp_server`.

1. Every Elementor document the site prints (pages, header, footer, popups, loop items):
   `python -I $S/wp/save-trees.py audit/pages` saves each tree to `audit/elementor/elementor-<id>-before.json`.
   These files are also the rollback. Add templates no saved page prints with `--ids=`.
2. `python -I $S/wp/image-list.py images/list.json audit/elementor/*.json --min-kb=80`: every uploaded image the
   trees reference, with its size and every place that uses it.
3. Format per image: **AVIF q50** when every use is a background or slideshow (the full URL is used, so no
   sub-sizes are needed); **WebP q80** when any use is an image widget, a gallery or a featured image (this
   host family cannot build sub-sizes from AVIF, and social previews need WebP). Long side capped at 1920 px for
   backgrounds, 1600 px otherwise. Files that do not shrink by at least 30% are skipped. `image-list.py` sets `fmt`
   and `max` itself.
   `python $S/wp/optimize-images.py images/list.json images/originals images/optimized [results-N.json]`
   (Pillow ≥ 11.3, AVIF built in; runs without `-I`; resumable). About 10 s per image (download + encode): split the
   list into three parts with their own results file and run them in parallel (Gewan: 495 images in about 25 min).
   Test-upload one AVIF and one WebP first and read `media_details.sizes`: that tells whether the host builds
   sub-sizes from each format.
4. `python -I $S/wp_upload.py <server> images/optimized/results.json images/uploaded.json`: new attachments with
   the original's alt text and title. About 8 s per file; two parallel uploads with separate output files are fine.
5. `python -I $S/wp/repoint-all.py images/list.json images/uploaded.json` (dry run), then `--apply`. It reads each
   affected document fresh and runs `repoint-images.py` on it; one document at a time:
   `python -I $S/wp/repoint-images.py <server> <post> <before.json> images/uploaded.json [--apply] [--revert]`.
   Every Elementor save purges that page's cache: no measurement runs meanwhile.
5b. Images the Elementor data does not hold: `python -I $S/wp/html-images.py audit/pages audit/elementor` lists
   `<img>` files of 80 KB or more by attachment id (featured images on cards and blog lists, block-editor images,
   theme output). `featured-find.py <out.json> <id>...` finds the posts (custom post types through the MCP, using
   site.json `post_types`), then re-encode as WebP, upload, `set-featured.py` (switches every post whose featured
   image has a WebP re-encode, rollback file first) and `content-images.py <post>` for block-editor image blocks.
   Both read `images/uploaded*.json`.
6. Purge All, re-warm (`bash $S/warm.sh images`), then `python -I $S/wp/check-images.py audit/pages-images`:
   every image URL in the pages and in their Elementor CSS files must answer 200 with an image type, and it lists
   originals still referenced (structured data and `og:image` are fine). Then `images.js` before and after on the
   homepage and one page per type, and screenshots of the changed sections (`simhtml.js`-style pixel diff is too
   strict after a re-encode: compare 1:1 crops by eye; `checks/el-shot.js` shoots one element). Dead slides it turns
   up (attachment and file gone) go through `remove-dead-slides.py <dead.json>`.
7. Report it in sections 2, 13 and 15 with the bytes before and after per image, and list the new attachment ids so
   the owner can delete them to roll back.

- Gewan, first run (2026-10-14): homepage images without scrolling 4.33 → 1.92 MB, page weight 6.45 → 4.02 MB;
  226 documents, 329 files, 93.9 MB → 29.4 MB. The host wrote some WordPress sub-sizes heavier than their original
  (a 78 KB 2500 px WebP has an 88 KB "large" size): a featured image whose original is already light keeps it.
- Re-encoded AVIF uploads with empty `media_details.sizes`: the host's image library cannot write AVIF. Fine for
  backgrounds and slides (full URL). For image widgets check the one file is lighter than the sizes it replaces,
  compare full-page screenshots, otherwise use WebP (references/patterns.md, "Images").
- Loop items and Theme Builder templates with `image_size: full` make 200 px thumbnails download 0.4–1.5 MB
  originals: set `medium` / `medium_large` / `large` to fit the slot (`elementor-update-element`) in the same batch.
