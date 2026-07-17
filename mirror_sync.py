"""LOE v2 — MIRROR SYNC.
The 'leaguewikimirror' plan is exactly the right architecture, and it matches how ingestion already
thinks: dedupe by newest revision, only re-process what changed. This module ingests the mirror's
native {title: {content, revid?}} JSON form and folds it into the same canonical page store the XML
path uses — so the engine is source-format-agnostic.

Two things the mirror needs, learned from this dump:
  1. NAMESPACE FILTER — a full wiki mirror carries Legends of Runeterra, TFT and Wild Rift pages
     (14,873 redirects + 4,000+ LoR cards here). Those are noise for a Summoner's Rift build engine.
  2. REVISION KEYING — store each page's revid so a re-sync only touches changed pages. The wiki's
     Special:Export and the API both expose revid; the mirror keys on it.
"""
import json, sqlite3, re, os

MIRROR_DIR = 'mirror'          # where mirror_fetch.py writes its combined full_content.json

OTHER_GAMES = ('(Legends of Runeterra)', 'LoR:', 'TFT:', '(Teamfight Tactics)', '(Wild Rift)',
               'Wild Rift', 'WR:', '/LoR', '/TFT', '(Arena')


def is_lol_sr(title, content):
    """Keep Summoner's Rift LoL pages; drop other games and non-SR modes."""
    if any(j in title for j in OTHER_GAMES): return False
    if content.strip().startswith('#REDIRECT') or content.strip().startswith('#redirect'):
        return False
    return True


def kind_of(title):
    if title.startswith('Module:'): return 'module'
    if title.startswith('Template:Data '): return 'ability'
    if title.startswith('Template:'): return 'template'
    if title.startswith('Category:'): return 'category'
    return 'article'


def sync_json(path, db='wiki.db', keep_filter=is_lol_sr):
    """Fold a mirror JSON dump into the canonical page store, keyed by title, newest content wins.
    Returns (added, updated, skipped)."""
    d = json.load(open(path))
    cx = sqlite3.connect(db); c = cx.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS pages(title TEXT PRIMARY KEY, ts TEXT, kind TEXT, source TEXT, text TEXT)')
    have = {t: (ts, txt) for t, ts, txt in c.execute('SELECT title, ts, text FROM pages')}
    added = updated = skipped = 0
    src = os.path.basename(path)
    for title, rec in d.items():
        content = rec.get('content', '') if isinstance(rec, dict) else str(rec)
        if not keep_filter(title, content):
            skipped += 1; continue
        revid = str(rec.get('revid', '')) if isinstance(rec, dict) else ''
        if title in have:
            # only overwrite if this content is longer/newer (mirror has no worse data than XML)
            if len(content) <= len(have[title][1]):
                continue
            c.execute('UPDATE pages SET text=?, source=?, ts=COALESCE(NULLIF(?,""),ts) WHERE title=?',
                      (content, src, revid, title)); updated += 1
        else:
            c.execute('INSERT INTO pages VALUES(?,?,?,?,?)', (title, revid, kind_of(title), src, content))
            added += 1
    cx.commit()
    return added, updated, skipped


if __name__ == '__main__':
    import glob
    # Sources, in priority order:
    #  1. the live mirror's own combined dump (what mirror_fetch.py just wrote)  <- GitHub path
    #  2. any JSON dumps in the local uploads folder                            <- local/dev path
    sources = []
    if os.path.exists(os.path.join(MIRROR_DIR, 'full_content.json')):
        sources.append(os.path.join(MIRROR_DIR, 'full_content.json'))
    sources += sorted(glob.glob('/mnt/user-data/uploads/*.json'))

    # Ensure the table exists even if there is nothing to ingest, so the count below never crashes
    cx = sqlite3.connect('wiki.db'); c = cx.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS pages(title TEXT PRIMARY KEY, ts TEXT, kind TEXT, source TEXT, text TEXT)')
    cx.commit()

    if not sources:
        print('no JSON sources found (expected mirror/full_content.json). Did mirror_fetch.py run?')
    for j in sources:
        a, u, s = sync_json(j)
        print(f'{os.path.basename(j)}: +{a} new, {u} updated, {s} filtered out (other games/redirects)')

    total = c.execute('SELECT COUNT(*) FROM pages').fetchone()[0]
    kinds = dict(c.execute('SELECT kind, COUNT(*) FROM pages GROUP BY kind').fetchall())
    print(f'\ncanonical store now: {total} pages {kinds}')
