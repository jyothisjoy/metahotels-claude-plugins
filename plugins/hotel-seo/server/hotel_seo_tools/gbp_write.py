"""Google Business Profile changes, in two steps the user controls.

1. propose(location, changes)  reads the live profile, validates every change (Google's validate-only
   call for listing fields), and writes a change file with each field before -> after. Sends nothing.
2. apply(change_file, confirm) sends exactly that file, only with confirm = the change id the user
   was shown. A field that changed on the live profile since the proposal is skipped, not overwritten.
   Every applied change goes to ~/.metahotels-seo/gbp-changes.jsonl, and listing fields are read back.

Locked unless propose(..., allow_risky=True): business name, address and primary category. Changing
them can send the profile back to verification or get it suspended.

`changes` keys (all optional):
  website, phone, description                                       strings
  regular_hours    [{"day": "MONDAY", "open": "00:00", "close": "24:00"}]   (replaces all)
  special_hours    [{"date": "2026-12-31", "closed": true} | {"date", "open", "close"}]   (replaces all)
  additional_categories   ["Spa", "categories/gcid:..."]            (replaces the list)
  attributes       {"has_wifi": true, "has_pool": true, "url_reservations": "https://...", "x": null to unset}
  review_replies   [{"review_id": "...", "reply": "..."}]           (new or replacing an existing reply)
  delete_review_replies   ["review_id"]
  posts            (hotel profiles: STANDARD or EVENT only, no deals, discounts or offer links; Google policy)
                   [{"type": "STANDARD|OFFER|EVENT", "summary", "button": "BOOK|LEARN_MORE|CALL|...",
                     "url", "photo_url", "title", "start": "yyyy-mm-dd", "end": "yyyy-mm-dd",
                     "coupon", "terms", "language": "en"}]
  delete_posts     ["<post id or full name>"]
  photos           [{"url": "<public image URL>", "category": "ROOMS|EXTERIOR|INTERIOR|COMMON_AREA|FOOD_AND_DRINK|..."}]
  lodging          hotel amenities and policies (Lodging API updateLodging), flat or nested:
                   {"policies.checkinTime": "15:00", "parking": {"freeParking": true}, "pools.pool": "DEPENDENT_ON_SEASON",
                    "x.y": null to unset}; fields in gbp_lodging.WRITABLE. gbp_amenities builds this from confirmed facts.
  title, address ({addressLines: [...], locality, administrativeArea, postalCode, regionCode}),
  primary_category                                                  (allow_risky only)
"""
import hashlib
import hmac
import json
import secrets
import re
from datetime import datetime, timedelta, timezone

from . import paths
from .gbp import INFO, READ_MASK, V4, GbpError, _call, _find, _get, _safe

LOG = paths.HOME / 'gbp-changes.jsonl'
KEY_FILE = paths.HOME / 'gbp-change-key'
ALLOWED_HOSTS = {'mybusinessbusinessinformation.googleapis.com', 'mybusiness.googleapis.com',
                 'mybusinesslodging.googleapis.com'}
ALLOWED_METHODS = {'PATCH', 'PUT', 'POST', 'DELETE'}


def _key():
    """Local secret that signs change files, so apply() only sends what propose() wrote on this machine."""
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(secrets.token_hex(32))
        try:
            KEY_FILE.chmod(0o600)
        except OSError:
            pass
    return bytes.fromhex(KEY_FILE.read_text().strip())


def _sign(c):
    signed = {k: c[k] for k in ('id', 'location', 'account', 'created', 'expires', 'ops')}
    return hmac.new(_key(), json.dumps(signed, sort_keys=True, ensure_ascii=False, default=str).encode(),
                    hashlib.sha256).hexdigest()


def _op_target_ok(op, c):
    """Every request must go to a Business Profile API host, for this change's own location."""
    from urllib.parse import urlparse
    u = urlparse(op.get('url', ''))
    if op.get('method') not in ALLOWED_METHODS or u.scheme != 'https' or u.hostname not in ALLOWED_HOSTS:
        return False
    path = u.path.lstrip('/')
    own = (f"v1/{c['location']}", f"v4/{c['account']}/{c['location']}/")
    return path == own[0] or path.startswith(own[0] + '/') or path.startswith(own[1])
EXPIRES_H = 24
RISKY = {'title', 'address', 'primary_category'}
DAYS = {'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'}
PHOTO_CATS = {'COVER', 'PROFILE', 'LOGO', 'EXTERIOR', 'INTERIOR', 'PRODUCT', 'AT_WORK', 'FOOD_AND_DRINK', 'MENU',
              'COMMON_AREA', 'ROOMS', 'TEAMS', 'ADDITIONAL'}
BUTTONS = {'BOOK', 'ORDER', 'SHOP', 'LEARN_MORE', 'SIGN_UP', 'CALL'}
KNOWN = {'website', 'phone', 'description', 'regular_hours', 'special_hours', 'additional_categories', 'attributes',
         'review_replies', 'delete_review_replies', 'posts', 'delete_posts', 'photos', 'lodging'} | RISKY


def _time(s):
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', str(s).strip())
    if not m or int(m.group(1)) > 24 or int(m.group(2)) > 59:
        raise GbpError(f'time "{s}" is not hh:mm')
    return {'hours': int(m.group(1)), 'minutes': int(m.group(2))}


def _date(s):
    y, m, d = (int(x) for x in str(s).split('-'))
    return {'year': y, 'month': m, 'day': d}


def _hours(rows):
    periods = []
    for r in rows:
        day = str(r.get('day', '')).upper()
        if day not in DAYS:
            raise GbpError(f'regular_hours day "{r.get("day")}" is not MONDAY..SUNDAY')
        periods.append({'openDay': day, 'openTime': _time(r['open']),
                        'closeDay': str(r.get('close_day', day)).upper(), 'closeTime': _time(r['close'])})
    return {'periods': periods}


def _special(rows):
    out = []
    for r in rows:
        p = {'startDate': _date(r['date'])}
        if r.get('end_date'):
            p['endDate'] = _date(r['end_date'])
        if r.get('closed'):
            p['closed'] = True
        else:
            p['openTime'], p['closeTime'] = _time(r['open']), _time(r['close'])
        out.append(p)
    return {'specialHourPeriods': out}


def _category(name, region):
    if str(name).startswith(('categories/', 'gcid:')):
        return {'name': name if name.startswith('categories/') else f'categories/{name}'}
    data = _get(f'{INFO}/categories', {'regionCode': region or 'AE', 'languageCode': 'en', 'view': 'BASIC',
                                       'filter': f'displayName={name}', 'pageSize': 20})
    cats = data.get('categories', [])
    exact = [c for c in cats if c.get('displayName', '').lower() == str(name).lower()]
    if len(exact) == 1 or len(cats) == 1:
        c = (exact or cats)[0]
        return {'name': c['name'], 'displayName': c.get('displayName', '')}
    raise GbpError(f'category "{name}": ' + (f"pick one of {[c.get('displayName') for c in cats[:10]]}" if cats
                                             else 'no Google category with that name'))


def _attr_value(meta, key, value):
    name = f'attributes/{key}'
    vt = meta.get('valueType')
    if value is None:
        return None                                   # in the mask, not in the body = unset
    if vt == 'BOOL':
        if not isinstance(value, bool):
            raise GbpError(f'{key} takes true or false')
        return {'name': name, 'values': [value]}
    if vt == 'URL':
        if not re.match(r'https?://', str(value)):
            raise GbpError(f'{key} takes a URL')
        return {'name': name, 'uriValues': [{'uri': value}]}
    allowed = [v.get('value') for v in meta.get('valueMetadata', [])]
    if vt == 'ENUM':
        if allowed and value not in allowed:
            raise GbpError(f'{key} takes one of {allowed}')
        return {'name': name, 'values': [value]}
    if vt == 'REPEATED_ENUM':
        vals = value if isinstance(value, list) else [value]
        bad = [v for v in vals if allowed and v not in allowed]
        if bad:
            raise GbpError(f'{key}: {bad} not in {allowed}')
        return {'name': name, 'repeatedEnumValue': {'setValues': vals,
                                                    'unsetValues': [v for v in allowed if v not in vals]}}
    raise GbpError(f'{key}: value type {vt} is not supported here')


def _show_attr(a):
    if not a:
        return None
    return a.get('values') or [u.get('uri') for u in a.get('uriValues', [])] or (a.get('repeatedEnumValue') or {}).get('setValues')


DEAL = re.compile(r'(?:special|exclusive|limited|seasonal|summer|winter|weekend|holiday|eid|ramadan|our|latest|'
                  r'new|stay) offers?\b|\boffers?\s*(?:ends|valid|code|:)|/offers?/|/packages?/|\bdeals?\b|discount|%\s*off|\boff\b\s*\d|\bsave\s+\d|\bpromo|promotion|coupon|'
                  r'voucher|special (?:rate|price)|best (?:rate|price)|\bfree night|early bird|last minute|'
                  r'عرض|عروض|خصم|تخفيض', re.I)


def _hotel_post_policy(p):
    """Google's posts policy for hotels: no Offer posts, and no post that mentions or links to deals,
    promotions, special offers or discounts (support.google.com/business/answer/7213077, "Hotel posts").
    Updates and events are fine."""
    if str(p.get('type', 'STANDARD')).upper() == 'OFFER':
        raise GbpError('hotel profiles can\'t have Offer posts (Google posts policy). Use a STANDARD update '
                       'about the hotel instead, with no deal or discount in it')
    text = ' '.join(str(p.get(k) or '') for k in ('summary', 'title', 'url', 'terms', 'coupon'))
    m = DEAL.search(text)
    if m:
        raise GbpError(f'hotel posts can\'t mention or link to deals, promotions or discounts (Google posts '
                       f'policy); found "{m.group(0)}". Rewrite it as a hotel update or event')


def _post_body(p):
    t = str(p.get('type', 'STANDARD')).upper()
    if t not in ('STANDARD', 'OFFER', 'EVENT'):
        raise GbpError(f'post type "{t}" is not STANDARD, OFFER or EVENT')
    summary = (p.get('summary') or '').strip()
    if not summary or len(summary) > 1500:
        raise GbpError('post summary must be 1-1500 characters')
    if re.search(r'\+?\d[\d\s-]{7,}\d', summary):
        raise GbpError('post summary has a phone number in it; Google rejects those. Use button "CALL" instead')
    body = {'languageCode': p.get('language', 'en'), 'summary': summary, 'topicType': t}
    if p.get('button'):
        b = str(p['button']).upper()
        if b not in BUTTONS:
            raise GbpError(f'post button "{b}" is not one of {sorted(BUTTONS)}')
        body['callToAction'] = {'actionType': b} | ({} if b == 'CALL' else {'url': p.get('url', '')})
        if b != 'CALL' and not p.get('url'):
            raise GbpError('a post button needs a url')
    if p.get('photo_url'):
        body['media'] = [{'mediaFormat': 'PHOTO', 'sourceUrl': p['photo_url']}]
    if t in ('OFFER', 'EVENT'):
        if not (p.get('title') and p.get('start') and p.get('end')):
            raise GbpError(f'{t} posts need title, start and end dates')
        body['event'] = {'title': p['title'], 'schedule': {'startDate': _date(p['start']), 'endDate': _date(p['end'])}}
    if t == 'OFFER':
        body['offer'] = {k: v for k, v in (('couponCode', p.get('coupon')), ('redeemOnlineUrl', p.get('url')),
                                           ('termsConditions', p.get('terms'))) if v}
    return body


def _location_fields(loc):
    """The parts of the live listing proposals compare against (stale check)."""
    return {'websiteUri': loc.get('websiteUri', ''), 'phoneNumbers': loc.get('phoneNumbers', {}),
            'profile': loc.get('profile', {}), 'regularHours': loc.get('regularHours', {}),
            'specialHours': loc.get('specialHours', {}), 'categories': loc.get('categories', {}),
            'title': loc.get('title', ''), 'storefrontAddress': loc.get('storefrontAddress', {})}


@_safe
def propose(location, changes, out_dir='', allow_risky=False):
    """Validate a change to one profile and write the change file. Sends nothing."""
    unknown = set(changes) - KNOWN
    if unknown:
        return {'checked': False, 'reason': f'unknown change keys {sorted(unknown)}; known: {sorted(KNOWN)}'}
    risky = RISKY & set(changes)
    if risky and not allow_risky:
        return {'checked': False, 'reason': f'{sorted(risky)} are locked: changing the name, address or primary '
                'category can send the profile back to verification or get it suspended. Only with the user '
                'asking for exactly this change: propose again with allow_risky=true.'}
    account, loc = _find(location)
    name = loc['name']
    live = _location_fields(loc)
    region = (loc.get('storefrontAddress') or {}).get('regionCode', '')
    ops, warnings = [], []

    # ---- listing fields: one PATCH
    patch, mask, rows = {}, [], []
    if 'website' in changes:
        w = changes['website'].strip()
        if not re.match(r'https?://', w):
            raise GbpError('website must start with https://')
        from .gbp import _host
        if _host(w) != _host(live['websiteUri']) and live['websiteUri']:
            warnings.append(f"the website link moves from {_host(live['websiteUri'])} to {_host(w)}")
        if 'utm_' not in w:
            warnings.append('the new website link has no UTM tags (GA4 will count profile visits as organic)')
        patch['websiteUri'] = w
        mask.append('websiteUri')
        rows.append(('Website link', live['websiteUri'], w))
    if 'phone' in changes:
        ph = changes['phone'].strip()
        if not re.fullmatch(r'\+?[\d\s()-]{7,20}', ph):
            raise GbpError(f'phone "{ph}" does not look like a phone number')
        patch['phoneNumbers'] = dict(live['phoneNumbers'], primaryPhone=ph)
        mask.append('phoneNumbers')
        rows.append(('Phone', live['phoneNumbers'].get('primaryPhone', ''), ph))
    if 'description' in changes:
        d = changes['description'].strip()
        if len(d) > 750:
            raise GbpError(f'description is {len(d)} characters; Google allows 750')
        if re.search(r'https?://|www\.', d):
            raise GbpError('description has a link in it; Google rejects descriptions with URLs')
        patch['profile'] = {'description': d}
        mask.append('profile.description')
        rows.append(('Description', live['profile'].get('description', ''), d))
    if 'regular_hours' in changes:
        patch['regularHours'] = _hours(changes['regular_hours'])
        mask.append('regularHours')
        rows.append(('Opening hours', live['regularHours'], patch['regularHours']))
    if 'special_hours' in changes:
        patch['specialHours'] = _special(changes['special_hours'])
        mask.append('specialHours')
        rows.append(('Special hours', live['specialHours'], patch['specialHours']))
    if 'additional_categories' in changes or 'primary_category' in changes:
        cats = dict(live['categories'])
        if 'additional_categories' in changes:
            cats['additionalCategories'] = [_category(c, region) for c in changes['additional_categories']]
            rows.append(('Additional categories',
                         [c.get('displayName') for c in live['categories'].get('additionalCategories', [])],
                         [c.get('displayName') or c['name'] for c in cats['additionalCategories']]))
        if 'primary_category' in changes:
            cats['primaryCategory'] = _category(changes['primary_category'], region)
            rows.append(('PRIMARY CATEGORY (risky)', (live['categories'].get('primaryCategory') or {}).get('displayName'),
                         cats['primaryCategory'].get('displayName') or cats['primaryCategory']['name']))
        patch['categories'] = cats
        mask.append('categories')
    if 'title' in changes:
        patch['title'] = changes['title'].strip()
        mask.append('title')
        rows.append(('BUSINESS NAME (risky)', live['title'], patch['title']))
        warnings.append('changing the business name can trigger re-verification; Google suspends keyword-stuffed names')
    if 'address' in changes:
        patch['storefrontAddress'] = dict(live['storefrontAddress'], **changes['address'])
        mask.append('storefrontAddress')
        rows.append(('ADDRESS (risky)', live['storefrontAddress'], patch['storefrontAddress']))
        warnings.append('changing the address usually sends the profile back to verification')
    if mask:
        # Google's own check, without saving anything
        _call('PATCH', f'{INFO}/{name}', {'updateMask': ','.join(mask), 'validateOnly': 'true'}, patch)
        top = sorted({m.split('.')[0] for m in mask})
        ops.append({'kind': 'listing', 'rows': rows, 'method': 'PATCH', 'url': f'{INFO}/{name}',
                    'params': {'updateMask': ','.join(mask)}, 'body': patch,
                    'before': {k: live[k] for k in top if k in live}, 'google_validated': True})

    # ---- attributes: one PATCH
    if changes.get('attributes'):
        meta = {m['parent'].split('/')[-1]: m for m in
                _get(f'{INFO}/attributes', {'parent': name, 'languageCode': 'en', 'pageSize': 200}).get('attributeMetadata', [])}
        current = {a['name'].split('/')[-1]: a for a in _get(f'{INFO}/{name}/attributes').get('attributes', [])}
        body, amask, arows = [], [], []
        for k, v in changes['attributes'].items():
            k = k.split('/')[-1]
            if k not in meta:
                raise GbpError(f'attribute "{k}" is not available for this profile; available: {sorted(meta)[:60]}')
            if meta[k].get('deprecated'):
                raise GbpError(f'attribute "{k}" is deprecated')
            a = _attr_value(meta[k], k, v)
            amask.append(f'attributes/{k}')
            if a:
                body.append(a)
            arows.append((meta[k].get('displayName', k), _show_attr(current.get(k)), _show_attr(a)))
        ops.append({'kind': 'attributes', 'rows': arows, 'method': 'PATCH', 'url': f'{INFO}/{name}/attributes',
                    'params': {'attributeMask': ','.join(amask)}, 'body': {'name': f'{name}/attributes', 'attributes': body},
                    'before': {m.split('/')[-1]: current.get(m.split('/')[-1]) for m in amask}})

    # ---- hotel amenities and policies (Lodging API): one PATCH
    if 'lodging' in changes:
        from . import gbp_lodging
        ops.append(gbp_lodging.lodging_op(name, changes['lodging']))

    # ---- reviews
    base = f'{V4}/{account}/{name}'
    for r in changes.get('review_replies', []):
        text = (r.get('reply') or '').strip()
        if not text or len(text) > 4096:
            raise GbpError('a review reply must be 1-4096 characters')
        rv = _get(f"{base}/reviews/{r['review_id']}")
        old = (rv.get('reviewReply') or {}).get('comment', '')
        ops.append({'kind': 'review_reply', 'review': {'stars': rv.get('starRating'), 'date': rv.get('createTime', '')[:10],
                                                       'comment': (rv.get('comment') or '')[:600]},
                    'rows': [('Reply', old, text)], 'method': 'PUT', 'url': f"{base}/reviews/{r['review_id']}/reply",
                    'body': {'comment': text}, 'before': old})
    for rid in changes.get('delete_review_replies', []):
        rv = _get(f'{base}/reviews/{rid}')
        old = (rv.get('reviewReply') or {}).get('comment', '')
        if not old:
            raise GbpError(f'review {rid} has no reply to delete')
        ops.append({'kind': 'delete_review_reply', 'review': {'stars': rv.get('starRating'), 'comment': (rv.get('comment') or '')[:600]},
                    'rows': [('Reply', old, '(deleted)')], 'method': 'DELETE', 'url': f'{base}/reviews/{rid}/reply',
                    'before': old})

    # ---- posts and photos
    prim = ((live['categories'] or {}).get('primaryCategory') or {}).get('displayName', '')
    lodging = bool(re.search(r'hotel|resort|inn|lodging|motel|hostel|apartment|guest ?house|chalet|villa', prim, re.I))
    for p in changes.get('posts', []):
        if lodging:
            _hotel_post_policy(p)
        body = _post_body(p)
        ops.append({'kind': 'post', 'rows': [(f"New {body['topicType'].lower()} post", '', body['summary'])],
                    'method': 'POST', 'url': f'{base}/localPosts', 'body': body, 'before': None})
    for pid in changes.get('delete_posts', []):
        full = pid if '/localPosts/' in pid else f'{account}/{name}/localPosts/{pid.split("/")[-1]}'
        post = _get(f'{V4}/{full}')
        ops.append({'kind': 'delete_post', 'rows': [('Post', post.get('summary', '')[:300], '(deleted)')],
                    'method': 'DELETE', 'url': f'{V4}/{full}', 'before': post.get('summary', '')})
    for ph in changes.get('photos', []):
        cat = str(ph.get('category', 'ADDITIONAL')).upper()
        if cat not in PHOTO_CATS:
            raise GbpError(f'photo category "{cat}" is not one of {sorted(PHOTO_CATS)}')
        if not re.match(r'https://', ph.get('url', '')):
            raise GbpError('photos need a public https:// image URL Google can download')
        ops.append({'kind': 'photo', 'rows': [(f'New photo ({cat})', '', ph['url'])], 'method': 'POST',
                    'url': f'{base}/media', 'body': {'mediaFormat': 'PHOTO', 'sourceUrl': ph['url'],
                                                     'locationAssociation': {'category': cat}}, 'before': None})
    if not ops:
        return {'checked': False, 'reason': 'no changes given'}

    now = datetime.now(timezone.utc)
    cid = hashlib.sha256(json.dumps([name, ops], sort_keys=True, default=str).encode()).hexdigest()[:8]
    change = {'id': cid, 'status': 'proposed', 'location': name, 'account': account, 'title': loc.get('title', ''),
              'created': now.isoformat(timespec='seconds'),
              'expires': (now + timedelta(hours=EXPIRES_H)).isoformat(timespec='seconds'),
              'allow_risky': bool(risky), 'warnings': warnings, 'ops': ops}
    change = json.loads(json.dumps(change, ensure_ascii=False, default=str))   # same shape as when read back
    change['mac'] = _sign(change)
    out = paths.resolve(out_dir or 'gbp-changes')
    out.mkdir(parents=True, exist_ok=True)
    f = out / f'gbp-change-{now:%Y%m%d}-{cid}.json'
    f.write_text(json.dumps(change, indent=1, ensure_ascii=False), encoding='utf-8')
    preview = _preview(change)
    f.with_suffix('.md').write_text(preview, encoding='utf-8')
    return {'checked': True, 'change_id': cid, 'change_file': str(f), 'preview': preview,
            'next': f'Show the preview to the user word for word. Only after they approve it in a later message, '
                    f'call gbp_apply("{f}", confirm="{cid}"). Expires in {EXPIRES_H} hours.'}


def _fmt(v):
    if v in (None, '', [], {}):
        return '(empty)'
    if isinstance(v, list) and len(v) == 1 and isinstance(v[0], bool):
        return 'yes' if v[0] else 'no'
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def _preview(c):
    L = [f"## Business Profile change {c['id']}: {c['title']} ({c['location']})", '']
    for w in c['warnings']:
        L.append(f'⚠ {w}')
    if c['warnings']:
        L.append('')
    for op in c['ops']:
        if op.get('review'):
            L.append(f"Review ({op['review'].get('stars')}, {op['review'].get('date', '')}): \"{op['review']['comment']}\"")
        for label, before, after in op['rows']:
            L += [f'**{label}**', f'- now: {_fmt(before)}', f'- after: {_fmt(after)}', '']
    L.append(f"Nothing has been sent. Approve to apply change {c['id']} (expires {c['expires'][:16]} UTC).")
    return '\n'.join(L)


def _live_before(op, account, name):
    """What the live profile holds now for this op, in the same shape as op['before']."""
    if op['kind'] == 'listing':
        loc = _get(f'{INFO}/{name}', {'readMask': READ_MASK})
        live = _location_fields(loc)
        return {k: live[k] for k in op['before']}
    if op['kind'] == 'attributes':
        cur = {a['name'].split('/')[-1]: a for a in _get(f'{INFO}/{name}/attributes').get('attributes', [])}
        return {k: cur.get(k) for k in op['before']}
    if op['kind'] in ('review_reply', 'delete_review_reply'):
        return (_get(op['url'].rsplit('/reply', 1)[0]).get('reviewReply') or {}).get('comment', '')
    if op['kind'] == 'lodging':
        from . import gbp_lodging
        return gbp_lodging.live_values(gbp_lodging.fetch(name), op['before'])
    if op['kind'] == 'delete_post':
        return _get(op['url']).get('summary', '')
    return None


@_safe
def apply(change_file, confirm):
    """Send an approved change file. confirm must be the change id the user approved."""
    f = paths.resolve(change_file)
    if not re.fullmatch(r'gbp-change-\d{8}-[0-9a-f]{8}\.json', f.name):
        return {'checked': False, 'reason': 'not a gbp_propose change file; nothing sent'}
    c = json.loads(f.read_text(encoding='utf-8'))
    if not hmac.compare_digest(str(c.get('mac', '')), _sign(c)):
        return {'checked': False, 'reason': 'the change file was edited after gbp_propose wrote it, or was made on '
                'another machine; nothing sent. Propose the change again.'}
    if str(confirm).strip() != c['id']:
        return {'checked': False, 'reason': f"confirm must be the change id {c['id']} the user approved; nothing sent"}
    bad = [op.get('url') for op in c['ops'] if not _op_target_ok(op, c)]
    if bad:
        return {'checked': False, 'reason': f"requests outside this profile's Business Profile API: {bad[:3]}; nothing sent"}
    if c['status'] != 'proposed':
        return {'checked': False, 'reason': f"change {c['id']} is already {c['status']}; propose a new one"}
    if datetime.now(timezone.utc) > datetime.fromisoformat(c['expires']):
        return {'checked': False, 'reason': f"change {c['id']} expired; propose it again so the before values are fresh"}
    results = []
    for op in c['ops']:
        label = op['rows'][0][0] if op['rows'] else op['kind']
        try:
            if op['before'] is not None and _live_before(op, c['account'], c['location']) != op['before']:
                results.append({'op': op['kind'], 'what': label, 'result': 'skipped',
                                'why': 'the live profile changed since the proposal; propose again'})
                continue
            resp = _call(op['method'], op['url'], op.get('params'), op.get('body'))
            r = {'op': op['kind'], 'what': label, 'result': 'sent'}
            if op['kind'] == 'listing':
                loc = _get(f"{INFO}/{c['location']}", {'readMask': READ_MASK})
                pick = {'websiteUri': lambda x: x.get('websiteUri', ''),
                        'title': lambda x: x.get('title', ''),
                        'profile': lambda x: (x.get('profile') or {}).get('description', ''),
                        'phoneNumbers': lambda x: (x.get('phoneNumbers') or {}).get('primaryPhone', '')}
                checked = [k for k in op['body'] if k in pick]
                if checked:
                    same = all(pick[k](loc) == pick[k](op['body']) for k in checked)
                    r['read_back'] = 'live now' if same else ('not live yet: Google is reviewing the edit '
                                                              '(the profile shows it as a pending edit)')
            if op['kind'] == 'lodging':
                from . import gbp_lodging
                now = gbp_lodging.live_values(gbp_lodging.fetch(c['location']), op['after'])
                r['read_back'] = 'live now' if now == op['after'] else (
                    'not live yet: ' + ', '.join(f'{p} shows {now[p]}' for p in op['after'] if now[p] != op['after'][p]))
            if op['kind'] in ('post', 'photo'):
                r['created'] = resp.get('name', '')
                if resp.get('state'):
                    r['state'] = resp['state']
            results.append(r)
        except GbpError as e:
            results.append({'op': op['kind'], 'what': label, 'result': 'failed', 'why': str(e)[:400]})
    sent = sum(r['result'] == 'sent' for r in results)
    c['status'] = 'applied' if sent == len(results) else ('partly applied' if sent else 'failed')
    c['applied'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    c['results'] = results
    c['mac'] = _sign(c)           # status is outside the signature; the 'applied' status blocks a second apply
    f.write_text(json.dumps(c, indent=1, ensure_ascii=False), encoding='utf-8')
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as log:
        log.write(json.dumps({'when': c['applied'], 'id': c['id'], 'location': c['location'], 'title': c['title'],
                              'status': c['status'], 'file': str(f),
                              'changes': [{'what': lbl, 'before': b, 'after': a} for op in c['ops'] for lbl, b, a in op['rows']],
                              'results': results}, ensure_ascii=False, default=str) + '\n')
    return {'checked': True, 'change_id': c['id'], 'status': c['status'], 'results': results, 'log': str(LOG)}


def history(location='', limit=20):
    """Applied changes from the log, newest first."""
    if not LOG.exists():
        return {'changes': []}
    rows = [json.loads(line) for line in LOG.read_text(encoding='utf-8').splitlines() if line.strip()]
    if location:
        rows = [r for r in rows if location.lower() in (r['location'] + ' ' + r['title']).lower()]
    return {'changes': rows[::-1][:limit]}
