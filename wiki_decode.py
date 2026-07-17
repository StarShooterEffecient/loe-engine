"""LOE v2 — WIKI MARKUP DECODER.
Item and ability effects are written in the wiki's own template language. Until now the engine read
them with regular expressions, which is how a CONDITION ("at or below 50% of maximum health") got
read as a PAYLOAD ("deals 50% of maximum health"). Regex cannot see structure.

This is a real decoder:
  1. RECURSIVE PARSE  - {{a|{{b|x}}|c}} becomes a tree, not a string
  2. HANDLER REGISTRY - each template has a semantic handler
  3. TYPED VALUES     - {{as|VALUE|TYPE}} carries its own type: the wiki has been telling us
                        'physical damage' / 'magic damage' / 'shield' all along
  4. UNKNOWN REPORT   - any template with no handler is LOGGED, not ignored.
                        This is the future-proofing: when a patch introduces a new template, the
                        pipeline says so loudly instead of silently mis-parsing. A parser that
                        lies quietly is the single most dangerous thing in this engine.

The whole item-effect vocabulary is 27 templates. Value-bearing: as, rd, pp, ap, fd, g.
Display-only: tip, tt, ii, sti, stil, ui, bi, ai, si, ci, ft, sbc.
"""
import re, json
from collections import Counter

UNKNOWN = Counter()          # template -> times seen with no handler
HANDLED = Counter()


# ---------------------------------------------------------------- 1. recursive parse
def parse_templates(text):
    """Return a list of nodes. Each node is either a str (literal) or dict(name, args)."""
    out, i, n = [], 0, len(text)
    buf = ''
    while i < n:
        if text.startswith('{{', i):
            node, j = _parse_one(text, i)
            if node is None:
                buf += text[i]; i += 1; continue
            if buf: out.append(buf); buf = ''
            out.append(node); i = j
        else:
            buf += text[i]; i += 1
    if buf: out.append(buf)
    return out


def _parse_one(text, i):
    """Parse a single {{...}} starting at i. Returns (node, next_index) or (None, i)."""
    assert text.startswith('{{', i)
    depth, j = 0, i
    while j < len(text):
        if text.startswith('{{', j): depth += 1; j += 2; continue
        if text.startswith('}}', j):
            depth -= 1; j += 2
            if depth == 0: break
            continue
        j += 1
    if depth != 0: return None, i
    body = text[i + 2:j - 2]
    parts, d, cur = [], 0, ''
    for ch in body:
        if ch == '{': d += 1
        elif ch == '}': d -= 1
        if ch == '|' and d == 0:
            parts.append(cur); cur = ''
        else:
            cur += ch
    parts.append(cur)
    name = parts[0].strip().lower()
    args, kwargs = [], {}
    for p in parts[1:]:
        m = re.match(r'\s*([a-zA-Z_]\w*)\s*=(.*)$', p, re.S)
        if m: kwargs[m.group(1).lower()] = m.group(2).strip()
        else: args.append(p.strip())
    return dict(name=name, args=args, kwargs=kwargs, raw=text[i:j]), j


# ---------------------------------------------------------------- 2. handlers
def _num(s):
    m = re.search(r'-?\d+(?:\.\d+)?', str(s))
    return float(m.group(0)) if m else None


def h_fd(node):
    """{{fd|1.5}} -> a formatted decimal."""
    return dict(kind='number', value=_num(node['args'][0] if node['args'] else ''))


def h_g(node):
    """{{g|400}} -> gold."""
    return dict(kind='gold', value=_num(node['args'][0] if node['args'] else ''))


def h_ap(node):
    """{{ap|60 to 100}} or {{ap|60/6}} -> a rank/level span, or a rate (value per period)."""
    a = node['args'][0] if node['args'] else ''
    to = re.match(r'\s*([\d.]+)\s*to\s*([\d.]+)', a)
    if to:
        lo, hi = float(to.group(1)), float(to.group(2))
        return dict(kind='span', lo=lo, hi=hi, value=hi)          # rank 5 / level 18
    rate = re.match(r'\s*([\d.]+)\s*/\s*([\d.]+)\s*$', a)
    if rate:
        total, period = float(rate.group(1)), float(rate.group(2))
        return dict(kind='rate', value=total, period=period)       # e.g. 60 damage over 6s
    v = _num(a)
    return dict(kind='number', value=v, pct=('%' in a)) if v is not None else None


def h_rd(node):
    """{{rd|150 + (200-150)/10*(x-1) for 13|...}} -> a level curve; {{rd|9%|6%}} -> a percentage."""
    a = node['args'][0] if node['args'] else ''
    pct = '%' in a
    curve = re.match(r'\s*([\d.]+)\s*\+\s*\(\s*([\d.]+)\s*-\s*[\d.]+\s*\)', a)
    if curve:
        lo, hi = float(curve.group(1)), float(curve.group(2))
        return dict(kind='span', lo=lo, hi=hi, value=hi, pct=pct)   # value at max level
    v = _num(a)
    return dict(kind='number', value=v, pct=pct) if v is not None else None


def h_pp(node):
    """{{pp|0 to 75 by 5|...}} or {{pp|14;11;8|Outer;Inner;...}} -> a scaling table."""
    a = node['args'][0] if node['args'] else ''
    pct = node['kwargs'].get('key', '') == '%'
    to = re.match(r'\s*([\d.]+)\s*to\s*([\d.]+)', a)
    if to:
        lo, hi = float(to.group(1)), float(to.group(2))
        return dict(kind='span', lo=lo, hi=hi, value=hi, pct=pct)
    if ';' in a:
        vals = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', a)]
        return dict(kind='table', values=vals, value=max(vals) if vals else None, pct=pct)
    v = _num(a)
    return dict(kind='number', value=v, pct=pct) if v is not None else None


def h_as(node):
    """{{as|VALUE_TEXT|TYPE}} — THE key template. Arg 2 is the wiki's own name for what this is:
    'physical damage', 'magic damage', 'shield', 'heal'... We no longer have to infer the type.

    The percent flag must be POSITIONAL. '60 damage (+ 6% AP)' is 60 FLAT — the '%' belongs to the
    AP ratio, not to the payload. Treating any '%' in the sentence as 'this value is a percentage'
    made Blackfire Torch appear to deal 60% of max health per ability."""
    val_text = node['args'][0] if node['args'] else ''
    vtype = node['args'][1].strip().lower() if len(node['args']) > 1 else ''
    inner = decode(val_text)
    num = next((v['value'] for v in inner['values'] if v.get('value') is not None), None)
    if num is None:
        num = _num(val_text)
    plain = strip(val_text)
    # is the FIRST number in the plain rendering immediately followed by a % sign?
    m = re.search(r'(-?\d+(?:\.\d+)?)\s*(%?)', plain)
    pct_positional = bool(m and m.group(2) == '%')
    # a {{pp|key=%}} inside also means percent
    pct_declared = any(v.get('pct') for v in inner['values'] if v['kind'] in ('span', 'table', 'number'))
    return dict(kind='typed', value=num, vtype=vtype, pct=(pct_positional or pct_declared),
                text=plain)


DISPLAY_ONLY = {'tip', 'tt', 'ii', 'iis', 'sti', 'stil', 'ui', 'bi', 'ai', 'ais', 'si', 'ci',
                'ft', 'sbc', 'sbcn', 'anchor', 'clr', 'tocright', 'recurring', 'degree', 'aug',
                'rutngt', 'critical damage', 'seeother', 'outdated if new patch'}

HANDLERS = {'fd': h_fd, 'g': h_g, 'ap': h_ap, 'rd': h_rd, 'pp': h_pp, 'pplevel': h_pp, 'as': h_as}


# ---------------------------------------------------------------- 3. decode
def strip(text):
    """Plain readable text with all markup removed."""
    out = []
    for node in parse_templates(text):
        if isinstance(node, str):
            out.append(node)
        elif node['name'] in DISPLAY_ONLY:
            out.append(node['args'][0] if node['args'] else '')
        elif node['name'] == 'as':
            # {{as|VALUE_TEXT|TYPE}} — render the FULL value text (recursively), not just the number.
            # Rendering only the number silently deleted 'of the target's current health' from
            # Blade of the Ruined King, which is the entire meaning of the item.
            out.append(strip(node['args'][0]) if node['args'] else '')
        elif node['name'] in HANDLERS:
            h = HANDLERS[node['name']](node)
            if h and h.get('value') is not None:
                pctsign = '%' if h.get('pct') else ''
                out.append(f"{h['value']:g}{pctsign}")
            else:
                out.append(' '.join(node['args'][:1]))
        else:
            out.append(' '.join(node['args'][:1]))
    s = ''.join(out)
    return re.sub(r"\[\[|\]\]|'{2,}|<br\s*/?>", ' ', s).strip()


def decode(text):
    """Decode one effect description into typed values + plain text + unknown-template report."""
    values = []

    def walk(nodes):
        for node in nodes:
            if isinstance(node, str): continue
            nm = node['name']
            if nm in HANDLERS:
                HANDLED[nm] += 1
                v = HANDLERS[nm](node)
                if v: values.append(v)
                # {{as|...}} already recursed; others may still nest
                if nm != 'as':
                    walk([x for x in parse_templates('|'.join(node['args'])) if not isinstance(x, str)])
            elif nm in DISPLAY_ONLY or nm.startswith('#'):
                walk([x for x in parse_templates('|'.join(node['args'])) if not isinstance(x, str)])
            else:
                UNKNOWN[nm] += 1                     # <-- future-proofing: never silent
                walk([x for x in parse_templates('|'.join(node['args'])) if not isinstance(x, str)])

    walk(parse_templates(text))
    return dict(values=values, text=strip(text))


def coverage_report():
    return dict(handled=dict(HANDLED), unknown=dict(UNKNOWN),
                unknown_total=sum(UNKNOWN.values()))


if __name__ == '__main__':
    IT = json.load(open('item_dna.json'))
    tested = 0
    for n, d in IT.items():
        for e in d['effects']:
            decode(e.get('raw', ''))
            tested += 1
    rep = coverage_report()
    print(f'decoded {tested} item effect descriptions')
    print(f'\nHANDLED templates: {rep["handled"]}')
    print(f'\nUNKNOWN templates ({rep["unknown_total"]} occurrences) — these would silently corrupt:')
    for t, c in sorted(rep['unknown'].items(), key=lambda x: -x[1]):
        print(f'   {t:28s} {c}')
    if not rep['unknown']:
        print('   none — every template in the corpus has a handler')

    print('\n--- worked examples ---')
    for n in ['Kraken Slayer', "Serylda's Grudge", "Rabadon's Deathcap", 'Blackfire Torch', 'Heartsteel']:
        e = IT[n]['effects'][0] if IT[n]['effects'] else None
        if not e: continue
        r = decode(e['raw'])
        typed = [(v['vtype'], v['value'], v.get('pct')) for v in r['values'] if v['kind'] == 'typed']
        print(f'\n{n}: {e["name"]}')
        print(f'   typed values: {typed}')
        print(f'   text: {r["text"][:110]}')
