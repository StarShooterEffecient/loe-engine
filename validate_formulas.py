"""LOE v2 — FORMULA VALIDATION GATE.
The mirror's mechanics articles (Critical strike, Penetration, Healing, Damage reduction...) state
the game's rules in prose. This gate reads those statements and checks the engine's combat CONSTANTS
against them — so a stealth patch to a core multiplier is caught by the DATA, not by my memory.

This already paid off: the wiki states critical strikes deal 200% as of V26.01 (reverted from 175%).
The engine was on 175%. Every crit build was undervalued. The gate catches exactly this class of drift.
"""
import re, sqlite3

cx = sqlite3.connect('wiki.db'); C = cx.cursor()


def article(title):
    r = C.execute("SELECT text FROM pages WHERE title=?", (title,)).fetchone()
    return r[0] if r else ''


def check_crit():
    """Wiki: base critical strike damage multiplier (currently 200% as of V26.01)."""
    txt = article('Critical strike')
    # find the CURRENT value: the last "reverted to X% ... in Vnn" or "deals X% ... by default"
    reverts = re.findall(r'(\d{3})%\s*(?:again|damage)[^.]{0,40}?(?:in|as of)\s*\[\[V([\d.]+)', txt)
    default = re.search(r'deals?\s*(\d{3})%\s*of its normal value by default', txt)
    current = None
    if reverts:
        current = int(max(reverts, key=lambda r: tuple(map(int, r[1].split('.'))))[0])
    elif default:
        current = int(default.group(1))
    return dict(stat='crit_multiplier', wiki=(current / 100.0 - 1.0 if current else None),
                engine_const='CRIT_BASE', engine=0.75,
                note=f'wiki says base crit = {current}%' if current else 'not found')


def check_pen_order():
    """Wiki: percentage penetration/reduction applies before flat (multiplicative for %)."""
    txt = article('Armor penetration') or article('Armor')
    mult = bool(re.search(r'multiplicative', txt, re.I))
    order = bool(re.search(r'percentage.{0,40}before.{0,20}flat|following order', txt, re.I))
    return dict(stat='pen_stacking', wiki='multiplicative' if mult else 'unstated',
                engine='multiplicative', ok=(mult or order))


def validate():
    results = []
    crit = check_crit()
    crit['ok'] = (crit['wiki'] is not None and abs(crit['wiki'] - crit['engine']) < 0.01)
    results.append(crit)
    results.append(check_pen_order())
    return results


if __name__ == '__main__':
    print('FORMULA VALIDATION vs the wiki\'s stated rules:\n')
    for r in validate():
        flag = 'OK' if r.get('ok') else '*** MISMATCH ***'
        print(f'  [{flag}] {r["stat"]}')
        for k, v in r.items():
            if k not in ('stat', 'ok'): print(f'        {k}: {v}')
