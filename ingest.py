"""LOE v2 — STAGE 0: UNIVERSAL WIKI INGESTION.
One canonical page store from any number of Special:Export XML dumps.
Efficiency principle: parse every export ONCE, dedupe by title keeping the NEWEST revision
timestamp, and persist to SQLite. Every future data drop is just another export -> same code.
"""
import re, os, sys, glob, sqlite3, json, datetime

UP = '/mnt/user-data/uploads'
DB = 'wiki.db'

PAGE = re.compile(r'<page>(.*?)</page>', re.S)
TITLE = re.compile(r'<title>(.*?)</title>', re.S)
TS = re.compile(r'<timestamp>(.*?)</timestamp>')
TEXT = re.compile(r'<text[^>]*>(.*?)</text>', re.S)

def unescape(s):
    return (s.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
             .replace('&#039;', "'").replace('&#39;', "'").replace('&amp;', '&'))

def ingest(paths, db=DB):
    if os.path.exists(db): os.remove(db)
    cx = sqlite3.connect(db); c = cx.cursor()
    c.execute('CREATE TABLE pages(title TEXT PRIMARY KEY, ts TEXT, kind TEXT, source TEXT, text TEXT)')
    c.execute('CREATE INDEX idx_kind ON pages(kind)')
    seen = {}
    for p in paths:
        raw = open(p, encoding='utf-8', errors='replace').read()
        n = 0
        for m in PAGE.finditer(raw):
            blob = m.group(1)
            t = TITLE.search(blob); x = TEXT.search(blob); ts = TS.search(blob)
            if not (t and x): continue
            title = unescape(t.group(1).strip())
            ts_v = ts.group(1) if ts else ''
            body = unescape(x.group(1))
            prev = seen.get(title)
            if prev and prev[0] >= ts_v: continue     # keep newest revision
            kind = ('module' if title.startswith('Module:') else
                    'ability' if title.startswith('Template:Data ') else
                    'template' if title.startswith('Template:') else
                    'category' if title.startswith('Category:') else 'article')
            seen[title] = (ts_v, kind, os.path.basename(p), body)
            n += 1
        print(f'  {os.path.basename(p):58s} {n:5d} new/updated pages')
    for title, (ts_v, kind, src, body) in seen.items():
        c.execute('INSERT INTO pages VALUES(?,?,?,?,?)', (title, ts_v, kind, src, body))
    cx.commit()
    stats = dict(c.execute('SELECT kind, COUNT(*) FROM pages GROUP BY kind').fetchall())
    newest = c.execute('SELECT MAX(ts) FROM pages').fetchone()[0]
    print(f'\ncanonical page store: {sum(stats.values())} pages {stats}')
    print(f'newest revision in corpus: {newest}')
    return cx

if __name__ == '__main__':
    paths = sorted(glob.glob(f'{UP}/League_of_Legends_*.xml'), key=os.path.getsize, reverse=True)
    print('INGESTING', len(paths), 'wiki exports (largest first):')
    cx = ingest(paths)
    c = cx.cursor()
    print('\nkey modules present:')
    for (t,) in c.execute("SELECT title FROM pages WHERE kind='module' ORDER BY title").fetchall():
        print('   ', t)
