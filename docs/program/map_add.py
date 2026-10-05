import sys
p, g = sys.argv[1], sys.argv[2]
b = open(p, encoding='utf-8').read()
m = '\n## Not yet specified'
assert m in b, 'marker missing'
key = g.split('](')[1].split(')')[0]
if key in b.split(m)[0]:
    sys.exit('already present')
b = b.replace(m, g + '\n' + m, 1)
open(p, 'w', encoding='utf-8', newline='\n').write(b)
