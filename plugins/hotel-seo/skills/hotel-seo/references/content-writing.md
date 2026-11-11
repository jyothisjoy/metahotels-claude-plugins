# Content writing standard — hotel-seo

How we write **every piece of text this plugin produces for a hotel website or profile**: a title, a meta description, an H1, an intro, an FAQ answer, alt text, a button, a booking paragraph, a schema description, a Business Profile description, post or review reply, a section rewrite, a new offer or area page, a full blog post. Most jobs are one small piece, not a whole page. Small or large, it gets the same thinking; only the amount of output changes.

Adapted for hotels from the SEO Content Writer framework (O-CMO, v3.0: JTBD, E-E-A-T, small content units, layered editing) and held to our own rules: the playbook's copy standards and "What we don't recommend", the registry's rule 12, and the [CONFIRM] guard. Where they differ, our rules win (section 9 lists what we left out and why).

---

## 1. The three rules behind every piece

1. **Write for one guest with one job.** Not for a keyword, not for "everyone". The piece exists because someone searched, landed and needs to decide something.
2. **Facts come from the source of truth.** `hotel-facts.json`, the live booking engine, the hotel's own pages, or an official source for the area. Anything else is **[CONFIRM]** (playbook ground rule 6). An invented amenity, distance or price is worse than a vague sentence.
3. **The smallest unit that does the job, written completely.** A title is one line, but a finished one: the guest's words, the hotel's real advantage, the right length. A full page is built one section at a time, never in one go.

---

## 2. The unit brief (before writing anything)

Write it in your head for a title; write it down (run notes or the report JSON's working notes) for anything longer than two sentences.

| Field | What it holds | Where it comes from |
|---|---|---|
| **Guest job** | "When [situation], I want to [motivation], so I can [outcome]." One job only. | the search, the page's purpose, Mirai segments (families, long stays, GCC, same-day) |
| **Searches it answers** | the query cluster for this page, the main phrase in the guest's words, Arabic if the page is Arabic | Search Console query + page (`money_queries_pos_4_20`, `get_search_by_page_query`), `keyword_volumes` / `keyword_ideas` |
| **Intent** | discover · compare · decide · book · on-stay info | the queries and the page type |
| **Facts allowed** | the facts this piece may state, each with its source | `hotel-facts.json`, `booking_engine.md`, the page itself, official area sources |
| **What the guest can't get elsewhere** | the one thing the top results / OTA listings don't say: the view from a specific room, the walk to a named landmark, what's included in the package, the hotel's own photos | the hotel's pages, the engine, the information sheet; if nothing, say so and keep the piece short |
| **Next step** | where the guest goes after reading: a room page, the standard booking link (hotel-addendum.md, "The booking path"), the offer page, contact | the page type and funnel stage |
| **Where it goes** | the field and the page (Rank Math title, Elementor heading, intro text block, FAQ widget, alt field…), and its limits | the finding or Build Plan page |

Example (rooms intro, a Build Plan page spec):
> Guest job: *When I'm booking a family stay in Barsha Heights, I want to see which rooms fit two adults and two children, so I can book without calling the hotel.* · Searches: "family hotel barsha heights", "hotel with connecting rooms dubai" (pos 8–14) · Facts: room occupancy from the engine (3 Feb), connecting rooms [CONFIRM] · Unique: the two-bedroom suite with kitchenette · Next: the suite page, then the booking link · Where: the 60–80 word intro above the room grid on /rooms/.

---

## 3. Sizes and specs per unit

Size comes from the job and the slot, never from a word count target (Google has none). These are the limits of the slot, not quotas.

| Unit | Shape | Must have | Never |
|---|---|---|---|
| **Title** (SEO title) | ≤ 60 characters (hard limit 62–66) and ≤ 580px wide (capitals and W/M are wide; Arabic: characters only); `[What the page is, in the guest's words] \| [Hotel name]`; homepage ends "Official Site" | the main search phrase once, the area or landmark when the search has one | keyword lists, the city twice, "Best", "No. 1", years that will age, the same title on two pages |
| **Meta description** | ≤ 155 characters, one or two sentences | location or landmark, one concrete fact (size, view, kitchenette, what's included), the direct-booking reason or member benefit if confirmed | the title again, "Discover X at Y. Book now." templates, prices, unconfirmed claims |
| **H1** | one per page, states what the page is | the guest's words for the page | slogans ("Experience luxury"), the hotel name alone on an inner page |
| **Intro** (page top, rooms or offers intro) | 40–80 words; first two sentences answer the page's question and still make sense quoted alone | what it is, where, who it suits, one specific fact, a link to the next step | "Welcome to…", "Whether you're travelling for business or leisure…", history before the answer |
| **Section rewrite** (an H2 block) | the size of the section it replaces | an H2 phrased the way guests ask, an answer-first opening sentence, the facts in text (not only in an image) | repeating what another section says |
| **FAQ** | a real guest question (Search Console question queries, hotel contact questions); a 1–3 sentence answer that starts with the answer | the specific fact, or [CONFIRM] | invented questions to hit keywords, answers with prices, "please contact us" as the whole answer |
| **Booking paragraph** (blog → booking) | 2–3 sentences at the end of a post | the hotel by name, why it suits this post's reader, links to a room page and the standard booking link | a hard sell, a discount unless confirmed or read on the engine |
| **Room description** | 60–120 words plus a facts line | what differs from the other rooms (size [CONFIRM unless confirmed], bed, view, occupancy, kitchenette, bathroom), who it suits | adjectives in place of facts, the same paragraph with the room name swapped |
| **Offer page** | what's included, dates, who it's for, the terms in plain words, the button | only what the engine sells today, terms from the engine | prices or percentages not on the engine; a page for an offer the engine no longer sells |
| **Area / landmark page** | only when demand and unique content justify it (registry C03) | how to get there from the hotel (time and mode, [CONFIRM]), what's there, when to go, the rooms that suit that trip | a page per landmark with the name swapped (scaled content) |
| **Full blog post** | as long as the guest's question needs, built section by section (section 6) | a real job, the hotel's first-hand detail, sources for every fact, a booking paragraph | rewriting the top 5 results, invented experiences, AI byline |
| **Alt text** | one sentence (≤ 125 characters), written after viewing the image | what is in the photo + the room or place + the hotel name | "image of", "photo of", keyword lists, the same alt on every image |
| **Button text** | 2–4 words, says where it goes | "View Deluxe King Room", "Check availability" | "Read more", "Click here", "View more", "Learn more", "Submit" |
| **Schema description** | 1–2 sentences that match the visible page | the facts on the page | claims not on the page, reviews written by the hotel |
| **Business Profile description** | ≤ 750 characters, no links, no prices | what the hotel is, where, for whom, 2–3 confirmed facts | the business name stuffed with keywords; offers |
| **Business Profile post** | an update or event (hotel profiles can't post offers) | one piece of news, a photo, a button | deals, discounts, promotions, phone numbers in the text |
| **Review reply** | 2–4 sentences (≤ 600 characters) in the hotel's voice and the review's language (Arabic written natively) | thanks (first name only, when the guest shows one), the guest's specific point answered, what changed if anything did; a complaint: an apology and the confirmed hotel email or phone | surnames, booking or room numbers, stay dates, prices, discounts, codes, promises the hotel hasn't confirmed, links, arguing |

---

## 4. Writing rules (every unit)

**Voice.** Plain, specific, warm without gushing. Short sentences mixed with a few longer ones. Present tense, active voice ("The suite has a kitchenette", not "A kitchenette is provided"). Write to one guest ("you") on room and offer pages; neutral on area guides. Match the English the site already uses (British on most of our sites: "centre", "colour") and Arabic as Arabic, never a translation pasted from English word for word.

**Per-hotel voice.** Before writing more than a few lines for a hotel, look for `<hotel dir>/voice.md` (a single-hotel site: `<domain>/voice.md`; a group: `<domain>/hotels/<slug>/voice.md`). If it doesn't exist and the job is bigger than titles and metas, make it once (section 8) and reuse it every time.

**Openings.** Start with the answer or a concrete fact. Never start with:
- "Welcome to…", "Discover…", "Experience…", "Looking for…?", "Have you ever…?"
- "In today's…", "When it comes to…", "Whether you're … or …"
- a proverb, a famous quote, "everyone knows", "every traveller dreams of…"

**Words and patterns to leave out** (the hotel AI tells; `presend_check` and `render_report` flag them): nestled, in the heart of, boasts (use "has"), vibrant, oasis, haven, unparalleled, seamless, elevate, unforgettable, tapestry, testament, curated, delve, embark, indulge, luxurious retreat, perfect blend, second to none, leverage, enhance, game-changing, innovative, holistic, robust, unlock, "serves as / stands as" (use "is"), "not just X but Y", "X rather than simply Y", "this matters", a reflex list of three adjectives, "Bold term: description" bullet lists, em dashes in paste copy (use a colon, comma or full stop). Also: sentences opening "Moreover / Furthermore / Additionally", filler ("it is worth noting", "let's dive in", "in conclusion", "this article will", "I hope this helps"), inflated verbs (utilise, facilitate) and adjectives (comprehensive, pivotal, bustling). One of these is a warning to read; several kinds in one section (3+ kinds or 6+ hits) is a problem: the section reads machine-made, so rewrite it rather than swapping words.

**Words that date.** "Currently", "this year", "newly opened", "recently", "brand new" and a year in the text go stale without anyone noticing. State the fact ("the spa opened in March 2025 [CONFIRM]" only where the date matters to the guest) or drop the time word.

**One value per fact, in the hotel's unit.** A room's size, guest count or a landmark's distance reads the same in the title, the meta, the body, the schema and on every other page: take it from `hotel-facts.json` (the hotel's answer beats the engine; distances are stored once), never re-measure per page. Sizes in the unit `hotel.json` `preferences.units` names (m² or sq ft), the same unit everywhere. When you change a fact in one place, list every other place it appears (`site_consistency_check`, `custom_search`) and change those too.

**Specific beats impressive.** Replace every adjective you can with a fact: "spacious" → "42 m² [CONFIRM]"; "close to the beach" → "a 3-minute walk to Al Aqah beach [CONFIRM]"; "great views" → "floor-to-ceiling windows facing the Creek". If there is no fact, cut the adjective rather than inventing one.

**Guest's words, once, in the prominent places.** The main search phrase goes in the title, the H1 and the first two sentences, once each, the way a person would say it. Secondary phrases go where they fit naturally, usually an H2 or the intro. Never count keywords, never repeat a phrase to "hit" it, never change a URL slug to add one.

**Answer-first, self-contained passages.** Each section opens with a sentence that answers that section's question and makes sense on its own: it names the hotel or the room instead of starting "It", "This", "They" or "These", and it adds a fact instead of repeating the heading ("Family Suites" → not "Our family suites are…" but "The Family Suite at Atana Hotel sleeps two adults and two children and has a kitchenette [CONFIRM]"). This is what Google's AI features, ChatGPT and Perplexity lift; it is also what a guest skimming on a phone reads.

**Room fit.** On a rooms index or in an FAQ, tell guests which room suits them: "Choose the Family Suite if you're two adults and two children; the Deluxe King suits couples." Build it only from confirmed occupancy (the engine or `hotel-facts.json`), one room per guest type, no superlatives ("the best room for families").

**Proof over promise.** First-hand detail only the hotel has (what the view looks at, which rooms connect, what breakfast includes, how guests get to the airport) beats general claims. Real reviews may be quoted with the platform and month; never write reviews or ratings.

**Next step.** Every page-level piece links onward: a room page, the offer page, or the standard booking link (hotel-addendum.md). Put it after the proof (the facts, a review quote), not in the first line. Use link text that says where it goes.

**The swap test.** Put a competitor's name in place of the hotel's: if the sentence is still true, it says nothing. Build each page-level piece on one item from the hotel's own differentiators (what only it has: the view, the location detail, the room type, the package), taken from its site, the engine and the information sheet.

**The guest's own words.** Reviews on Google, Booking and Tripadvisor, the hotel contact's notes and the questions guests ask the front desk give the phrases guests use ("walk to the metro", "big enough for the kids"). Use them in headings and FAQs; quote a review only word for word, with platform and month.

**One main action.** Each page-level piece asks for one thing (check availability for this room, see this offer); other links support it, they don't compete with it.

**Honesty gates** (from MetaHotels' copywriting method; non-negotiable):
- Superlatives ("best", "only", "first", "largest", "#1", "award-winning") need a source on file; otherwise cut them.
- Urgency and scarcity only when real (a real event date, a real offer end date from the engine); never "only 2 rooms left".
- Prices, discounts and "from" rates only as the live engine shows them on the day, and only where the hotel's rate parity and OTA contracts allow; never an inflated "was" price.
- No invented reviews, ratings, statistics or awards; a rating only with its platform and the date it was checked.

**Facts and sources.** Hotel facts: `hotel-facts.json` or [CONFIRM]. Area facts (opening times, distances, prices of attractions, visa or transport rules): an official or primary source, current within the last 2 years for anything that changes, linked in the run notes; no aggregator lists, no competitor blogs, no AI summaries as sources.

**The claim ledger** (any piece with an area fact). In the run notes, one line per fact that isn't about the hotel (a distance, a travel time, opening hours, visa or entry rules, an event date): the claim as written, its source (link), the date you checked it. A claim with no source is removed or marked [CONFIRM]. A hotel fact is never softened into vague wording to get past the guard ("a short walk" in place of an unconfirmed "3 minutes"): it keeps its number and gets [CONFIRM].

---

## 5. Optimising what already exists (most of our work)

Most items change part of a live page. The page may already rank; don't break what works.

1. **Read the page as it is** (`site_text.json`, `inspect_pages` for the rendered page) and its Search Console queries (query + page, last 3 months).
2. **Protect what ranks.** A page whose clicks and impressions are growing (G06) keeps its title and H1 unless they are wrong; add to it instead.
3. **Use the queries.** Queries with impressions but few clicks → the title and meta. Queries at positions 4–20 → the H1, the intro or a new H2. Questions in the queries → an FAQ or an H2 with an answer-first paragraph. Queries the page gets but doesn't answer → a short section, or a link to the page that does (don't make one page serve two jobs; registry O07 / C02).
4. **Change the smallest thing that fixes it.** A title, an intro, one section. Say exactly which element changes and leave the rest alone.
5. **Give before / after** in the finding (table "Now" → "Change to"), so MetaHotels sees the change and the re-check can test it (`title`, `meta`, `h1`, `text_present` checks with the exact new text).

---

## 6. Writing a full page or blog post

Only when an item really needs a new page (registry C03: demand, intent, and unique content; held **[waiting for hotel details]** when the facts aren't in yet).

1. **Brief** (section 2, written down), plus:
   - the top results for the main search: what they all say, what they miss (web search; read them, don't summarise them);
   - the outline: H1, an answer-first intro, 3–6 H2s phrased as guest questions, the facts each section needs and their source, where the booking paragraph and the internal links go;
   - one angle that only this hotel can give.
2. **Approve the outline before writing** when the user is in the conversation; otherwise check it against the brief yourself.
3. **Write one section at a time** (the intro, then each H2, then the close), each answer-first, each with its facts, none repeating another.
4. **Close** with the next step, not a summary: the booking paragraph and the related pages ("Read more: [Full Page Title]").
5. **Edit** (section 7), then lay it out for the Build Plan page spec (or the agency): a `paste` block per section, the title / meta / H1 in a table, image and alt text suggestions (photos the hotel has, never stock), internal links as source → destination → anchor text, and the checks (`h1`, `title`, `text_present` for each section's first sentence).
6. **Byline.** Blog posts go out under a real person or "<Hotel> team" with a short bio, never a company login (H28) and never "AI".

---

## 7. The edit pass (every piece longer than a sentence)

In this order; a short piece takes a minute, a full post longer:

1. **Repetition.** Anything said twice, in this piece or elsewhere on the page? Cut it.
2. **Facts.** Every number, distance, time, price, amenity and policy: in `hotel-facts.json` or the engine, or marked [CONFIRM]. Area facts linked to their source. The renderer's guard catches hotel facts; area facts are on you.
3. **Job and intent.** Does the first sentence answer what the guest came for? Does the piece end at the next step?
4. **Readability.** Paragraphs of 2–4 sentences, H2s as questions where it fits, facts in text, lists only for real lists.
5. **Voice and tells.** Read it aloud. Any word from the list in section 4, any stock opening, any sentence that could describe any hotel anywhere: rewrite it with a fact or cut it. Then ask once: *what still reads templated here?* (the same sentence shape three times, every section the same length, a closing line that sums up). Write down the concrete answers, revise once, and stop.
6. **Fit the slot.** Title and meta lengths, one H1, alt text per image, button text that says where it goes. Then `copy_check` (write mode) or `presend_check` / `render_report` and fix every problem; read every warning.
7. **Integrity re-check.** The voice edit can undo earlier fixes. Re-verify against the brief and the claim ledger: every fact and number unchanged, [CONFIRM] markers still in place, lengths still within the slot, links and the booking link still right, the main phrase still in the title, H1 and first two sentences.

---

## 8. The hotel voice file (`<hotel dir>/voice.md`, once per hotel)

Make it the first time a hotel needs more than titles and metas. Sources: the hotel's best existing copy (its own About or rooms pages, `site_text.json`), the information sheet, and anything the hotel or MetaHotels says about tone. Existing agency copy full of AI tells is not a voice source.

```
# Voice: <Hotel>
Positioning: <what the hotel is, for whom, in one line: e.g. "4-star business and family hotel in Barsha Heights, 2 minutes from the metro">
Tone: <4–6 words, e.g. direct, warm, practical, local>
English: <British / American, as the site uses it>; Arabic: <yes / no; who checks it>
Always mention when relevant: <confirmed differentiators with source>
Never say: <claims the hotel can't back, competitor names, words the hotel dislikes>
Names: <exact hotel name, room names, outlet names, loyalty programme name, as on the engine>
Booking link: <the standard booking link (hotel-addendum.md) with this hotel's Mirai ID from site.json>
Instead of / write:
- "Nestled in the heart of Dubai…" / "Atana Hotel is in Barsha Heights, a 3-minute walk from Dubai Internet City metro [CONFIRM]."
```

Update it when the hotel corrects something; mention in the run notes that it was used.

---

## 9. What we took from the framework, and what we left out

**Also taken, from MetaHotels' own copywriting method (handoff, Nov 2026):** the honesty gates, the swap test and the differentiator inventory, customer words from reviews, one action per piece. Ads, offers and campaigns are outside this standard.

**Also taken, from Awesome SEO Writing Skill (Flaq AI, MIT):** the claim ledger, the integrity re-check after the style edit, the single "what still reads templated?" pass, and judging AI tells in clusters rather than one word at a time. Left out: rule-of-three and sentence-rhythm scoring, AI-detector scores, word-count minimums.

**Taken:** the guest job before anything else; a brief before writing; small units, one section at a time; Search Console queries to optimise existing pages; facts checked against primary sources; the layered edit (repetition → facts → readability → voice → humanise); per-client voice guardrails; banned openings; CTAs after proof; "Read more" internal links; real bylines.

**Left out, and why:**
- **2,000+ word articles and per-section word counts.** Google has no preferred word count; most of our units are one line to one paragraph.
- **60–100 character titles and the "keyword in H1, first 100 words, H2 twice, 1–2 per 500 words" placement rules.** Our titles stay ≤ 60 (truncation); keyword counts are density by another name (registry rule 12). The guest's words go in the prominent places once.
- **Clickbait headline formulas** ("21 Secrets the Experts Don't Want You to Know", "Who Else Wants…"). Hotel titles say what the page is; the guest is choosing a room, not a curiosity.
- **"American English" as a rule.** We match each site (mostly British English) and write Arabic natively.
- **Statistics as hooks.** Hotel pages open with the answer; statistics only where they serve the guest and come from a primary source.
- **Newsletter repurposing.** Not part of the hotel's reports. Ask if MetaHotels wants it.

---

## 10. Before handing over (checklist)

- [ ] One guest job; the first sentence serves it.
- [ ] The guest's search words in title, H1 and first sentences, once each; nothing counted or stuffed.
- [ ] Every hotel fact confirmed or [CONFIRM]; area facts in the claim ledger with source and date checked.
- [ ] Something only this hotel can say is in it (or the piece is short and honest).
- [ ] No stock opening, no word from the tells list, no em dashes in paste copy, no words that date.
- [ ] Each section's first sentence names the hotel or room and doesn't repeat its heading.
- [ ] Passes the swap test; no superlative, urgency, price or rating without its source; no price in an FAQ answer.
- [ ] Slot limits met: title ≤ 60 and ≤ 580px, meta ≤ 155, alt ≤ 125, one H1, button text says where it goes; each title / meta / alt line shows its count.
- [ ] A next step: room page, offer page or the standard booking link, after the proof.
- [ ] Before / after given for changes to live text, and a check for each.
- [ ] Integrity re-check done after the voice edit.
- [ ] `copy_check` / `presend_check` / `render_report`: no problems; every warning read.
