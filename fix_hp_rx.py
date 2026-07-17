import ast
s = open('item_effects.py').read()
bad_start = s.index("HEALTH_PCT = re.compile(")
bad_end = s.index("\n", s.index("health', re.I)", bad_start)) + 1
good = (
    'HEALTH_PCT = re.compile(\n'
    '    r"([\\d.]+)\\s*%\\s*of\\s+(?:the\\s+)?(?:target\'?s?|their|its|your|enemy\'?s?)?\\s*"\n'
    '    r"(maximum|max|current|bonus)?\\s*health", re.I)\n'
)
s = s[:bad_start] + good + s[bad_end:]
open('item_effects.py', 'w').write(s)
ast.parse(s)
print('regex quoting fixed')
