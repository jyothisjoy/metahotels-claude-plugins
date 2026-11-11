"""Business Profile photo check (read-only): owner and guest photos by category, how fresh they are, and what's missing.

Calls (Google My Business API v4, GET only):
  owner photos  GET https://mybusiness.googleapis.com/v4/{parent=accounts/*/locations/*}/media   (pageSize: 100 used)
                https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media/list
  guest photos  GET https://mybusiness.googleapis.com/v4/{parent=accounts/*/locations/*}/media/customers  (pageSize up to 200)
                https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media.customers/list
  Both answer {mediaItems[], totalMediaItemCount, nextPageToken}. MediaItem: mediaFormat (PHOTO | VIDEO),
  locationAssociation.category, createTime, insights.viewCount (int64 as a string, when Google returns it), googleUrl.
  https://developers.google.com/my-business/reference/rest/v4/accounts.locations.media#MediaItem
  LOGO is a deprecated alias of PROFILE and is counted as PROFILE.

Uploading photos is gbp_write's "photos" change key (propose -> approved apply); this module never writes.
"""
from datetime import date, datetime, timezone

from .gbp import V4, _find, _get, _safe

STALE_MONTHS = 12              # newest owner photo in a key category older than this: flag
MIN_PHOTOS = 25                # fewer photos than this in total (owner + guest): flag
MIN_OWNER_PHOTOS = 10          # fewer owner photos than this: flag
MAX_ITEMS = 2000               # per list; enough for any hotel, keeps a run bounded
KEY_CATEGORIES = {             # categories a hotel profile should have owner photos in
    'COVER': 'cover photo', 'PROFILE': 'profile (logo) photo', 'EXTERIOR': 'exterior',
    'ROOMS': 'rooms', 'COMMON_AREA': 'pool and common areas', 'FOOD_AND_DRINK': 'food and drink',
}
STALE_CATEGORIES = ('EXTERIOR', 'INTERIOR', 'ROOMS', 'COMMON_AREA', 'FOOD_AND_DRINK')


def _list(url, page_size):
    """(items, totalMediaItemCount) across pages, up to MAX_ITEMS."""
    params, items, total = {'pageSize': page_size}, [], None
    while len(items) < MAX_ITEMS:
        data = _get(url, params)
        if total is None:
            total = data.get('totalMediaItemCount')
        items += data.get('mediaItems', [])
        if not data.get('nextPageToken'):
            break
        params['pageToken'] = data['nextPageToken']
    return items[:MAX_ITEMS], total


def _cat(m):
    c = ((m.get('locationAssociation') or {}).get('category') or 'UNCATEGORISED').upper()
    return 'PROFILE' if c == 'LOGO' else c


def _day(m):
    return (m.get('createTime') or '')[:10]


def _months_ago(day, today):
    d = date.fromisoformat(day)
    return (today.year - d.year) * 12 + today.month - d.month - (today.day < d.day)


def summarise(owner, guests, today=None, owner_total=None, guest_total=None):
    """Counts by category, newest / oldest dates, owner vs guest share, views and flags. Pure (tests call it)."""
    today = today or datetime.now(timezone.utc).date()
    cats = {}
    for who, items in (('owner', owner), ('guest', guests)):
        for m in items:
            c = cats.setdefault(_cat(m), {'owner': 0, 'guest': 0, 'videos': 0, 'owner_newest': '', 'owner_oldest': '',
                                          'newest': '', 'views': 0})
            c[who] += 1
            if m.get('mediaFormat') == 'VIDEO':
                c['videos'] += 1
            d = _day(m)
            if d:
                c['newest'] = max(c['newest'], d)
                if who == 'owner':
                    c['owner_newest'] = max(c['owner_newest'], d)
                    c['owner_oldest'] = min(c['owner_oldest'] or d, d)
            try:
                c['views'] += int((m.get('insights') or {}).get('viewCount') or 0)
            except ValueError:
                pass
    n_owner = owner_total if owner_total is not None else len(owner)
    n_guest = guest_total if guest_total is not None else len(guests)
    total = n_owner + n_guest
    views = sum(c['views'] for c in cats.values())
    has_views = any((m.get('insights') or {}).get('viewCount') is not None for m in owner + guests)
    flags = []
    for c, label in KEY_CATEGORIES.items():
        if not cats.get(c, {}).get('owner'):
            flags.append(f'no owner photo of the {label} ({c})')
    for c in STALE_CATEGORIES:
        newest = cats.get(c, {}).get('owner_newest')
        if newest and _months_ago(newest, today) >= STALE_MONTHS:
            flags.append(f'newest owner photo in {c} is from {newest}, over {STALE_MONTHS} months old')
    if total < MIN_PHOTOS:
        flags.append(f'only {total} photos in total (owner + guests); aim for at least {MIN_PHOTOS}')
    if n_owner < MIN_OWNER_PHOTOS:
        flags.append(f'only {n_owner} owner photos; aim for at least {MIN_OWNER_PHOTOS}')
    if total and n_guest > 2 * n_owner:
        flags.append(f'guests posted {n_guest} photos to the owner\'s {n_owner}: guest photos lead what people see')
    newest_owner = max((_day(m) for m in owner if _day(m)), default='')
    return {
        'owner_photos': n_owner, 'guest_photos': n_guest, 'total': total,
        'owner_share_pct': round(100 * n_owner / total, 1) if total else None,
        'newest_owner_photo': newest_owner,
        'total_views': views if has_views else None,
        'by_category': [{'category': c, **v} for c, v in sorted(cats.items(), key=lambda kv: -(kv[1]['owner'] + kv[1]['guest']))],
        'flags': flags,
    }


@_safe
def photos(location, account=''):
    """Owner and guest photos on one profile: counts by category, dates, share, views, flags."""
    loc = str(location).strip()
    if not (account and loc.startswith('locations/')):
        account, found = _find(loc)
        loc = found['name']
    base = f'{V4}/{account}/{loc}/media'
    owner, owner_total = _list(base, 100)    # the reference gives both 100 and 2500 as the maximum: 100 is safe
    guests, guest_total = _list(f'{base}/customers', 200)
    out = summarise(owner, guests, owner_total=owner_total if owner_total is not None else len(owner),
                    guest_total=guest_total if guest_total is not None else len(guests))
    out['category_counts_from'] = f'the {len(owner)} owner and {len(guests)} guest items read'
    return {'checked': True, 'location': loc, 'generated': date.today().isoformat(), **out,
            'next': ('To add photos: gbp_propose(location, {"photos": [{"url": "<public https image>", "category": '
                     '"ROOMS"}]}, "<hotel dir>/gbp/changes"), then gbp_apply after the user approves.') if out['flags']
            else 'Photos look complete and fresh.'}
