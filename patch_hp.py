import re, ast
src = open('champion_dna.py').read()

old_hp = src[src.index("R_HP  = re.compile("):src.index("R_MHP = re.compile(")]
new_hp = ("R_HP  = re.compile(r'(?:\\{\\{(?:ap|pplevel)\\|)?(?:key=[^|]*\\|)?([\\d.]+)(?:\\s*to\\s*([\\d.]+))?"
          "[^)]{0,10}?%[^)]{0,45}?(?:maximum|max)[^a-zA-Z]{0,8}health', re.I)\n")
src = src.replace(old_hp, new_hp)

old_mhp = src[src.index("R_MHP = re.compile("):src.index("\ndef ratio_sum")]
new_mhp = ("R_MHP = re.compile(r'(?:\\{\\{(?:ap|pplevel)\\|)?(?:key=[^|]*\\|)?([\\d.]+)(?:\\s*to\\s*([\\d.]+))?"
           "[^)]{0,10}?%[^)]{0,45}?missing[^a-zA-Z]{0,8}health', re.I)\n")
src = src.replace(old_mhp, new_mhp)

old_mh = [l for l in src.split('\n') if 'mh = re.search' in l][0]
new_mh = ("                mh = re.search(r'\\{\\{(?:ap|pplevel)\\|(?:key=[^|]*\\|)?([\\d.]+\\s*to\\s*[\\d.]+)\\}\\}"
          "[^.]{0,80}?(?:maximum|max)[^a-zA-Z]{0,8}health', desc_all, re.I)")
src = src.replace(old_mh, new_mh)

open('champion_dna.py', 'w').write(src)
ast.parse(src)
print('max-health regexes hardened')
