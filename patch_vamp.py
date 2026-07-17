import re, ast
src = open('champion_dna.py').read()
old = [l for l in src.split('\n') if 'vm = re.search' in l][0]
new = ("            vm = re.search(r'(?i)heal(?:s|ing)?[^0-9%]{0,30}?for\\s+(?:\\{\\{[^}]*\\|)?([\\d.]+)\\s*%"
       "[^.]{0,140}?damage', desc_all)")
src = src.replace(old, new)
old2 = [l for l in src.split('\n') if "sc = re.search" in l][0]
new2 = ("                sc = re.search(r'(?i)\\+\\s*(?:\\{\\{fd\\|)?([\\d.]+)\\}*\\s*%\\s*per\\s*100[^a-zA-Z]{0,12}"
        "(?:bonus)?[^a-zA-Z]{0,12}health', desc_all)")
src = src.replace(old2, new2)
open('champion_dna.py', 'w').write(src)
ast.parse(src)
print('vamp regex hardened for wiki markup')
