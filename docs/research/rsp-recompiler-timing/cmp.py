import sys,collections
def load(f):
    r=[l.rstrip('\n').split('\t') for l in open(f)][1:]
    return r
a=load(sys.argv[1]); b=load(sys.argv[2])
print("tasks",len(a),len(b))
n=min(len(a),len(b))
same=sum(1 for i in range(n) if a[i][1]==b[i][1] and a[i][3]==b[i][3])
print("aligned (type,cpu_start equal):",same,"of",n)
by=collections.defaultdict(lambda:[0,0,0,0,0,0,0])
for i in range(n):
    t=a[i][1]
    d=by[t]; d[0]+=1; d[1]+=int(a[i][4]); d[2]+=int(b[i][4]); d[3]+=int(a[i][7]); d[4]+=int(b[i][7]); d[5]+=int(a[i][6]); d[6]+=int(b[i][6])
for t,d in sorted(by.items()):
    print(f"type {t}: n={d[0]} busy {d[1]} -> {d[2]} ({(d[2]-d[1])/max(d[1],1)*100:+.3f}%) delta {d[2]-d[1]}  dmaLat {d[3]} -> {d[4]} delta {d[4]-d[3]}  rows {d[5]} -> {d[6]}")
ta=sum(int(x[4]) for x in a[:n]); tb=sum(int(x[4]) for x in b[:n])
print("total busy",ta,tb,tb-ta,f"{(tb-ta)/ta*100:+.3f}%")
