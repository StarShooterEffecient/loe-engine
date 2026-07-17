import re, ast
src = open('champion_dna.py').read()

# Two wiki encodings exist for percent-health scalings:
#   A) {{pplevel|key=%|4 to 10}} of the target's '''maximum''' health   <- NO literal % sign
#   B) (+ 8% of target's maximum health)                                <- literal % sign
old_hp = src[src.index("R_HP  = re.compile("):src.index("\ndef ratio_sum")]
new_hp = '''R_HP_A  = re.compile(r'\\{\\{(?:pplevel|ap)\\|(?:key=%\\|)?([\\d.]+)(?:\\s*to\\s*([\\d.]+))?\\}\\}[^.]{0,70}?(?:maximum|max)[^a-zA-Z]{0,10}health', re.I)
R_HP_B  = re.compile(r'([\\d.]+)(?:\\s*to\\s*([\\d.]+))?\\s*%[^.)]{0,50}?(?:maximum|max)[^a-zA-Z]{0,10}health', re.I)
R_MHP_A = re.compile(r'\\{\\{(?:pplevel|ap)\\|(?:key=%\\|)?([\\d.]+)(?:\\s*to\\s*([\\d.]+))?\\}\\}[^.]{0,70}?missing[^a-zA-Z]{0,10}health', re.I)
R_MHP_B = re.compile(r'([\\d.]+)(?:\\s*to\\s*([\\d.]+))?\\s*%[^.)]{0,50}?missing[^a-zA-Z]{0,10}health', re.I)

def pct_health(s, missing=False):
    """Average percent-health ratio found in a blob, under either wiki encoding."""
    tot = 0.0
    for rx in ((R_MHP_A, R_MHP_B) if missing else (R_HP_A, R_HP_B)):
        for m in rx.finditer(s):
            a = float(m.group(1)); b = float(m.group(2)) if m.group(2) else a
            tot += (a + b) / 2 / 100.0
        if tot: break          # encoding A wins if present; never double-count
    return round(tot, 4)
'''
src = src.replace(old_hp, new_hp)

# rewire the record fields to the new helper (leveling first, then description for innates)
src = src.replace("""                       max_hp=ratio_sum(R_HP, lev) or ratio_sum(R_HP, desc_all if slot=='I' else ''),
                       missing_hp=ratio_sum(R_MHP, lev) or ratio_sum(R_MHP, desc_all if slot=='I' else ''),""",
"""                       max_hp=pct_health(lev) or pct_health(desc_all),
                       missing_hp=pct_health(lev, True) or pct_health(desc_all, True),""")

# innate damage-effect line uses the same helper
old_mh = src[src.index("                mh = re.search("):src.index("                    if ratio_ranks:")]
new_mh = """                mh = R_HP_A.search(desc_all) or R_HP_B.search(desc_all)
                if mh:
                    a = float(mh.group(1)); b = float(mh.group(2)) if mh.group(2) else a
                    ratio_ranks = [round(a + (b - a) * i / 4, 2) for i in range(5)]
"""
src = src.replace(old_mh, new_mh)
src = src.replace("""                    if ratio_ranks:
                        effects.append(dict(kind='DAMAGE', label='% max health (innate on-hit)', values=ratio_ranks))""",
"""                    effects.append(dict(kind='DAMAGE', label='% max health (innate on-hit)', values=ratio_ranks))""")

open('champion_dna.py', 'w').write(src)
ast.parse(src)
print('health-ratio parsing rewritten for both wiki encodings')
