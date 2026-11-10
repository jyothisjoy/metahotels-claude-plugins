# Design standard: static image ads and social creatives

Built from the Khalidia Palace trial (25 Oct 2026). Saif rejected the first version as "a sad lookin ad": a hotel photo under a dark gradient, generic serif headline, logo on a box, and a perk any hotel could offer. He approved the second: the hotel's own story photo, a brand-colour panel, a premium type pairing and an integrated logo footer. Ogilvy's layout rules (captions, story appeal, people over products) come from `body-proof-close.md`.

## Before designing: the image
- **Use the hotel's own photo** (website gallery, its feature pages), never a generic room if a story shot exists. Prefer people + the differentiator in one frame (a guest holding her cat in the suite, not an empty room).
- **Story appeal:** the viewer should ask "what's going on here?" (Ogilvy). People beat rooms; a moment beats a layout.
- Log the photo's source URL in the brief and flag licensing for paid use (hotel confirms).

## Layout: pick one, don't default to a gradient
1. **Photo + brand panel (default for 4:5 feed):** photo top ~2/3, a solid panel in the hotel's brand colour (cream, sand, navy — sampled from the logo and website) bottom ~1/3, separated by a thin brand-colour rule. All text sits on the panel, so it is always legible.
2. **Full-bleed photo + one short line** only when the photo has a calm, dark area that holds text without a gradient.
3. **Seal / badge** for the single proof point (e.g. "Cats & dogs welcome · up to 10 kg"): a circle in the panel colour with a double brand-colour ring, slightly rotated, soft shadow, placed in a quiet corner of the photo. One seal, never more.

**Banned defaults:** dark-to-transparent gradient over a busy photo; text over faces; the logo on a translucent box or "plate"; more than two typefaces; centred body copy in multiple lines; stock-template looks (Canva-style ribbons, bursts, "SALE" stickers) unless the hotel's brand uses them.

## Type
- **Two families max:** an elegant serif for the headline (italic Palatino `palabi.ttf`, Book Antiqua `BOOKOS*`, Constantia, Cambria) + a clean geometric sans for everything else (Montserrat, Inter, Gill Sans). Match the hotel's own site fonts when they're known.
- **Hierarchy:** kicker (small caps, letter-spaced, brand colour, ~26 px on 1080 wide) → headline (90–110 px, one line if it fits; measure it) → support lines (30–34 px, ink and a softer secondary tone) → footer.
- Measure text width before placing (`ImageDraw.textlength`); nothing touches the safe margin (72 px on 1080).

## Logo and footer
- The logo sits **in the panel**, in its own colours, never on a box over the photo. Default: a footer with a thin brand-colour hairline, the website on the left (sans, brand colour), the logo right-aligned. Leave ≥ 30 px between the last copy line and the hairline, so it doesn't read as an underline.

## Colour
- Sample the brand colours from the logo file and website (e.g. Khalidia gold `#B08A3E`, ink `#2B2118`, cream `#F7F2E9`). One accent colour only.

## Platform fit
- Meta feed 1080×1350 (4:5); Stories/Reels 1080×1920 with text out of the top ~250 px and bottom ~340 px.
- Text in the image: kicker + headline + up to two short lines. The rest goes in the primary text.

## Build and review
- Render with a script saved beside the creative (`6_Campaigns/creatives/<Hotel>/render_<name>.py`) so edits are one command.
- **Look at the render before showing it**, at full size and as a phone-size crop. Check: is any text clipped, crowded or touching a rule? Does the seal text fit inside its circle? Does the logo read as part of the design?
- **Seal text is checked in code, not by eye:** a circle narrows away from its centre, so a line that fits the middle hits the ring near the top or bottom. Reuse `round_seal()` from `6_Campaigns/creatives/KhalidiaPalace/render_kp_ads.py`. It asserts each line against the ring width at that height and an 8 px gap between lines. Three Khalidia seals passed a plain width check and still touched the ring on 25 Oct 2026.
- **Design self-check (Gate 5 #15):** would this pass as the hotel's own in-house brand creative? If it looks like a template, redo it.
