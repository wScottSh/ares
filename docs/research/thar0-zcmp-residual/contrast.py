"""Per-config BUF residual (model avg - hw avg, rclk per 320-px line) for two compare.tsv files, and their difference."""
import sys, csv
def load(p):
    out = {}
    for r in csv.DictReader(open(p), delimiter='\t'):
        m = [float(v) for v in r['model_buf'].split('/')]; h = [float(v) for v in r['hw_buf'].split('/')]
        out[r['index']] = (r['id'], m[1], h)
    return out
a, b = load(sys.argv[1]), load(sys.argv[2])
inband = lambda m, h: h[0] <= m <= h[2]
print('idx\tid\thw/line\tres_a/line\tres_b/line\tdelta/line\tres_a%\tres_b%\tinband_a\tinband_b')
tot = [0, 0, 0, 0]
for k in a:
    i, ma, h = a[k]; _, mb, _ = b[k]
    print(f'{k}\t{i}\t{h[1]/240:.2f}\t{(ma-h[1])/240:+.2f}\t{(mb-h[1])/240:+.2f}\t{(mb-ma)/240:+.2f}\t{(ma-h[1])/h[1]*100:+.2f}\t{(mb-h[1])/h[1]*100:+.2f}\t{inband(ma,h)}\t{inband(mb,h)}')
    tot[0] += abs(ma-h[1])/h[1]*100; tot[1] += abs(mb-h[1])/h[1]*100; tot[2] += inband(ma,h); tot[3] += inband(mb,h)
n = len(a)
print(f'# mean abs residual a {tot[0]/n:.2f}% b {tot[1]/n:.2f}%; in band a {tot[2]} b {tot[3]}')
