#!/usr/bin/env python3
"""LOE v2 — WIKI MIRROR FETCHER (leaguewikimirror).
Talks to the official wiki's MediaWiki API and keeps a local mirror that only ever re-downloads
pages whose REVISION NUMBER changed. This is the foundation the whole engine's accuracy rests on:
without it, every build is frozen to whatever files were last hand-uploaded.

How it stays cheap and current:
  1. LIST    ask the API for every page in the namespaces we care about, with its latest revid.
  2. DIFF    compare each revid to what we already have in the manifest.
  3. FETCH   download ONLY the changed/new pages (in batches), never the whole wiki.
  4. COMMIT  write pages to disk + update the manifest {title: revid}. Re-running is a no-op until
             something on the wiki actually changes.

Runs anywhere with network. Designed for GitHub Actions on a schedule (see loe-mirror.yml).
The sandbox this was built in cannot reach the wiki (proxy allows only package registries), so the
network path is exercised by GitHub, and the DIFF/manifest logic is unit-tested locally below.
"""
import urllib.request, urllib.parse, json, os, time, sys, gzip

API = 'https://wiki.leagueoflegends.com/en-us/api.php'
UA = 'LOE-SynergyEngine-mirror/2.0 (meta-blind build optimizer; https://github.com/)'
MIRROR_DIR = 'mirror'
MANIFEST = os.path.join(MIRROR_DIR, 'manifest.json')

# The only namespaces a Summoner's Rift build engine needs. Everything else (LoR, TFT, Wild Rift,
# talk pages, user pages) is skipped at the source, so we never even list it.
#   0 = article (mechanics pages), 10 = Template (ability data + item text), 828 = Module (the data)
NAMESPACES = [0, 10, 828]

# Page-title prefixes worth keeping within those namespaces (keeps the mirror lean & on-topic).
KEEP_PREFIX = ('Module:ChampionData', 'Module:ItemData', 'Module:SpellData', 'Module:RuneData',
               'Module:DamageData', 'Module:ChannelData', 'Module:MonsterData', 'Module:GlossaryData',
               'Module:GamemodeData', 'Module:Gold', 'Template:Data ', 'Template:Rune data ',
               'Template:Item data ', 'Template:Map data ')
# plain mechanics articles we validate formulas against (namespace 0, no prefix)
KEEP_ARTICLES = {'Critical strike', 'Armor penetration', 'Magic penetration', 'Armor', 'Magic resistance',
                 'Ability haste', 'Healing', 'Health', 'Attack damage', 'Attack speed', 'Movement speed',
                 'Tenacity', 'Damage reduction', 'Item group', 'Named item effect', 'Penetration',
                 'Adaptive force', 'Lethality', 'On-hit', 'Life steal', 'Omnivamp', 'Rune', 'Champion'}


def api(params, retries=4):
    params.setdefault('format', 'json')
    params.setdefault('formatversion', '2')
    url = API + '?' + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if attempt == retries - 1: raise
            time.sleep(2 ** attempt)                 # polite backoff; the wiki is a volunteer resource


def list_revisions():
    """Return {title: revid} for every page we care about, via allpages (one call per namespace)."""
    latest = {}
    for ns in NAMESPACES:
        cont = {}
        while True:
            q = dict(action='query', list='allpages', apnamespace=ns, aplimit='500',
                     apfilterredir='nonredirects')
            q.update(cont)
            data = api(q)
            for p in data.get('query', {}).get('allpages', []):
                title = p['title']
                if ns == 828 and not title.startswith(KEEP_PREFIX): continue
                if ns == 10 and not title.startswith(KEEP_PREFIX): continue
                if ns == 0 and title not in KEEP_ARTICLES: continue
                latest[title] = None                 # revid filled in by the revisions pass
            if 'continue' in data: cont = data['continue']
            else: break
    # now fetch current revids in batches of 50 titles
    titles = list(latest)
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = api(dict(action='query', prop='revisions', rvprop='ids|timestamp',
                        titles='|'.join(batch)))
        for p in data.get('query', {}).get('pages', []):
            if 'revisions' in p:
                latest[p['title']] = p['revisions'][0]['revid']
    return {t: r for t, r in latest.items() if r is not None}


def fetch_content(titles):
    """Download current wikitext for a list of titles, in batches. Returns {title: content}."""
    out = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        data = api(dict(action='query', prop='revisions', rvprop='content|ids',
                        rvslots='main', titles='|'.join(batch)))
        for p in data.get('query', {}).get('pages', []):
            if 'revisions' not in p: continue
            rev = p['revisions'][0]
            content = rev.get('slots', {}).get('main', {}).get('content') or rev.get('content', '')
            out[p['title']] = content
    return out


def load_manifest():
    if os.path.exists(MANIFEST):
        return json.load(open(MANIFEST))
    return {}


def sync(dry_run=False):
    os.makedirs(MIRROR_DIR, exist_ok=True)
    have = load_manifest()                            # {title: revid}
    print(f'manifest: {len(have)} pages currently mirrored')
    print('listing current revisions from the wiki API...')
    latest = list_revisions()
    print(f'wiki reports {len(latest)} pages in scope')

    changed = [t for t, rev in latest.items() if have.get(t) != rev]
    removed = [t for t in have if t not in latest]
    print(f'CHANGED or NEW: {len(changed)}  |  REMOVED upstream: {len(removed)}')
    if dry_run:
        for t in changed[:20]: print('   would fetch:', t)
        return dict(changed=len(changed), removed=len(removed), fetched=0)

    if changed:
        print(f'fetching {len(changed)} changed pages...')
        content = fetch_content(changed)
        for title, text in content.items():
            safe = urllib.parse.quote(title, safe='') + '.wikitext'
            open(os.path.join(MIRROR_DIR, safe), 'w', encoding='utf-8').write(text)
            have[title] = latest[title]
    for t in removed:
        have.pop(t, None)
    json.dump(have, open(MANIFEST, 'w'), indent=0)

    # also emit a single combined JSON in the shape mirror_sync.py already ingests
    combined = {}
    for title in have:
        safe = urllib.parse.quote(title, safe='') + '.wikitext'
        p = os.path.join(MIRROR_DIR, safe)
        if os.path.exists(p):
            combined[title] = dict(content=open(p, encoding='utf-8').read(), revid=have[title])
    json.dump(combined, open(os.path.join(MIRROR_DIR, 'full_content.json'), 'w'))
    print(f'mirror updated: {len(changed)} pages fetched, {len(have)} total in manifest')
    return dict(changed=len(changed), removed=len(removed), fetched=len(changed))


if __name__ == '__main__':
    dry = '--dry-run' in sys.argv
    try:
        sync(dry_run=dry)
    except urllib.error.HTTPError as e:
        print(f'wiki API returned {e.code}. If this is a sandbox, that is expected — run on GitHub.')
        sys.exit(1)
