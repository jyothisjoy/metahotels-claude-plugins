# Team, IDs and message templates

The people, accounts and routines around the method. Edit this file when the team or a hotel's IDs change; the playbook stays the same.

## People

| Who | Role | Contact for |
|---|---|---|
| **Akshaya** | Runs the external SEO agency (India time, Mon–Fri) | Receives the Priority and Nice-to-Have lists and re-check fixes |
| **Saif** | MetaHotels, runs the daily routine | Sends lists to the agency, forwards the agency's WhatsApp change list, screenshots Claude can't get |
| **Mevi** | MetaHotels | Can do every export in the inputs checklist except hotel facts |
| **Rayyan** | Hotel side | Confirms offers, prices and facts marked [CONFIRM] |
| **Tech guy** | Web team | Web Team list items |

## Accounts

- Google account for Search Console and GA4: **metahotels.m@gmail.com** (84 GA4 properties, 76 Search Console sites as of Oct 2026). Signed in once per machine through `/hotel-seo init`.
- GCP project behind the sign-in: `metahotels-analytics` (OAuth app "MetaHotels SEO", published; branding verified on metahotels.ae, 19 Oct 2026). Google Ads API at **Basic** access (no developer token since Google retired them).
- Google Ads: the **MetaHotels Manager** account (437-179-3247) is owned by metahotelads@gmail.com; metahotels.m@gmail.com has Read only access, which is all Keyword Planner needs.

## Known booking engine (Mirai) IDs

| Hotel | Mirai ID |
|---|---|
| Gevora Hotel | 521138138 |
| Khalidia Hotel | 100380969 |
| Al Bahar Hotel & Resort | 100377331 |
| Atana Hotel Dubai | 100376916 |

- **The booking link to use in lists** (every "Book now" fix, every blog paragraph): `https://<domain>/search/?idtokenprovider=<id>&lang=en&currency=AED`. No dates, no other currency: old links with a 2023 check-in date or `currency=INR` are what break.
- Live check of a stay: `/search/?idtokenprovider=<id>&checkin=dd/mm/yyyy&nights=n&currency=AED&lang=en`.
- Add new hotels here as you find them (the ID is in the site's booking links).

## Daily rhythm (2 hotels a day)

| Time (Dubai) | Who | What |
|---|---|---|
| By 2 pm | MetaHotels team | Drop the exports Claude can't pull (inputs checklist, section "From you") into each hotel's folder for **tomorrow's** 2 hotels |
| 2–5 pm | Claude | `/hotel-seo <domain>` for each: crawl, Search Console, GA4, analysis, live checks, the three PDFs |
| 5–6 pm | Claude + MetaHotels team | `/hotel-seo recheck <domain>` for **today's** agency work; the team pastes the agency's WhatsApp change list |
| 6 pm | MetaHotels team | Send the agency tomorrow's lists plus the re-check fixes (fixes go at the top) |
| Next day | Agency | Priority Lists. Unfinished items roll into the next day, not the next week |

**Order across hotels.** The agency does every hotel's Priority list first, in file-number order, then as many Nice-to-Have items per hotel as they can; the rest stays open. Each list's subtitle says so, naming the day's Priority lists by file number, e.g. "order: all Priority lists first (Khalidia 22 → Al Bahar 25 → Atana 28), then as many Nice-to-Have items as you can per hotel; the rest stays open".

**File numbers** run across all hotels (22, 23, 24...), one per PDF, so the agency can refer to "list 25". `render_lists_pdf` with `file_number: "auto"` takes the next free number in the work folder; set it by hand when several machines produce lists the same day.

## Message templates

Address each message by role, not by name: write `[Name]` where a greeting needs one and let the sender fill it in.

**SEO agency: daily send**
> Hi [Name], here's tomorrow's list. **[NN] [Hotel 1] Priority** (~3.5 h) and **[NN] [Hotel 2] Priority** (~3.5 h), then the Nice-to-Have lists ([NN], [NN]) as time allows. Top of the list: [re-check fixes from today]. Please hold anything marked [CONFIRM] or [waiting for …]. Send the change list for each hotel at end of day and we'll re-check the live sites. Thanks!

**Hotel contact: fact and offer check**
> Good morning [Name], a few [Hotel] checks before the SEO team updates the site:
> **Offers:** [each site offer vs the booking engine: keep / change / remove? end date?]
> **Facts:** [each conflict: A or B?]

**Web team**
> Hi [Name], here's the [Hotel] web team list. [Top item and why it matters in one line]. Then [the rest]. Let me know your ETA.
