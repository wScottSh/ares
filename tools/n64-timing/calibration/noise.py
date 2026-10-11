"""The noise-mapping reader (prehw-plan.md U-NOISE-READER, U-NOISE-KIT): which cited mapping of the RDP's noise
bits a kit-noise snap's pixels show, over an offset set fixed before any console data.

The anchor is the noise clock of snap/rect-1016's first pixel, found from its a bits (Thar0's all-ones window
method, rdp-noise.md:37, 62). A mapping snap's first pixel is at the anchor plus D + k, |k| <= K, where D and
K come from the fork (kit.py --layout) and are written in the question's source. Each mapping predicts which
pixels the snap stores; the reader returns the mapping that alone matches, `offset-outside-bound` when none
does, or `ambiguous`, and the false-match rate (2K+1) x mappings x 2^-b, with b the fewest pixels the
mappings disagree on at any offset in the set.
"""
import re
from pathlib import Path

#The three LFSRs as timed.hpp NoiseLfsr models them (rdp-noise.md:33, 37, from Thar0/RDP-Noise's console
#dumps): degree and taps in register order, top bit the current output, all ones at power-on, c one step
#ahead, one step per RDP clock.
LFSRS = {"a": (29, 1 << 1 | 1 << 28), "b": (28, 1 << 2 | 1 << 27), "c": (27, 1 << 0 | 1 << 1 | 1 << 4 | 1 << 26)}
#G_AD_NOISE's value for one pixel's a, b and c outputs, per cited source (rdp-noise.md:39): Angrylion
#(noise >> 6) & 7, the combiner NOISE bits with a highest; MiSTer random2 & '1', some odd value 1-7.
AD_MAPPINGS = {"angrylion": lambda a, b, c: (a << 2 | b << 1 | c,), "mister-odd": lambda a, b, c: (1, 3, 5, 7)}
RATE_MAX = 1e-6
ANCHOR = "rect-1016"
#Mapping snap: the question whose source holds its offset set.
READS = {"ad-noise-7f": "noise-alpha-dither"}
OFFSET_SET = re.compile(r"offset set D = (\d+) \+- (\d+)")
QUESTIONS = Path(__file__).resolve().parent / "questions.tsv"


class Lfsr:
    def __init__(self, degree, taps):
        self.degree, self.taps, self.ones = degree, taps, (1 << degree) - 1
        self.period = self.ones
        self.power = [[self.shift(1 << j) for j in range(degree)]]
        for _ in range(1, 64):
            m = self.power[-1]
            self.power.append([self.apply(m, m[j]) for j in range(degree)])
        self._giants = None

    def shift(self, r):
        return (r << 1 | bin(r & self.taps).count("1") & 1) & self.ones

    @staticmethod
    def apply(m, r):
        out, j = 0, 0
        while r:
            if r & 1:
                out ^= m[j]
            r >>= 1
            j += 1
        return out

    def advance(self, r, steps):
        k = 0
        while steps:
            if steps & 1:
                r = self.apply(self.power[k], r)
            steps >>= 1
            k += 1
        return r

    def outputs(self, r, n):
        out = []
        for _ in range(n):
            out.append(r >> (self.degree - 1) & 1)
            r = self.shift(r)
        return out

    def log(self, r):
        """The clock t (mod the period) at which the register from all ones holds r: baby-step giant-step."""
        m = 1 << ((self.degree + 1) // 2)
        if self._giants is None:
            jump, g, self._giants = self.advance, self.ones, {}
            for i in range(1, self.period // m + 2):
                g = jump(g, m)
                self._giants.setdefault(g, i)
        s = r
        for j in range(m):
            if s == self.ones:
                return (-j) % self.period
            if s in self._giants:
                return (self._giants[s] * m - j) % self.period
            s = self.shift(s)
        return None


LFSR = {name: Lfsr(*spec) for name, spec in LFSRS.items()}


def bits(t, n):
    """[(a, b, c)] for the n RDP clocks from t."""
    seq = {name: LFSR[name].outputs(LFSR[name].advance(LFSR[name].ones, t + (name == "c")), n) for name in "abc"}
    return list(zip(seq["a"], seq["b"], seq["c"]))


def combiner_bits(data):
    """(a, b, c) per pixel of a 32 bpp combiner NOISE dump, c None where the clamp hides it (romgen
    suites/noise/decode.py, Thar0 fb2data.py's inverse)."""
    from romgen.suites.noise.decode import decode
    a, b, c = decode(data)
    return [(int(x), int(y), None if z == "x" else int(z)) for x, y, z in zip(a, b, c)]


def anchor(data):
    """The noise clock of the anchor dump's first pixel, or None when its pixels are not the LFSRs at one clock per
    pixel from a clock below 16 periods of a."""
    try:
        px = combiner_bits(data)
    except SystemExit:
        return None
    a = LFSR["a"]
    if len(px) < a.degree:
        return None
    t = a.log(int("".join(str(p[0]) for p in px[:a.degree]), 2))
    for m in range(16) if t is not None else ():
        if all(p[0] == q[0] and p[1] == q[1] and p[2] in (None, q[2]) for p, q in zip(px, bits(t + m * a.period, len(px)))):
            return t + m * a.period
    return None


def stored(data, bpp):
    """Whether each pixel was written: the kit clears the surface to 0 and the draw's color is not 0."""
    return [any(data[i:i + bpp]) for i in range(0, len(data), bpp)]


def predict(abc, draw, mapping):
    """The mapping's write decision for each pixel at these noise outputs: True, False, or None when the
    mapping's values disagree on it."""
    from kit import noise_pixel
    out = []
    for a, b, c in abc:
        seen = {noise_pixel(draw, ad=v) is not None for v in AD_MAPPINGS[mapping](a, b, c)}
        out.append(seen.pop() if len(seen) == 1 else None)
    return out


def read(anchor_data, snap_data, draw, d, k):
    """{result, rate, b, anchor, matches}: the reader on one log, offset set d +- k."""
    t = anchor(anchor_data)
    if t is None:
        return {"result": "no-anchor", "rate": None, "b": None, "anchor": None, "matches": []}
    seen = stored(snap_data, 2 if draw["bits16"] else 4)
    w = len(seen)
    abc = bits(t + d - k, 2 * k + w)
    preds = {m: predict(abc, draw, m) for m in AD_MAPPINGS}
    code = {True: "1", False: "0", None: "?"}
    want = "".join(code[x] for x in seen)
    text = {m: "".join(code[x] for x in p) for m, p in preds.items()}
    matches = [(m, off - k) for m, p in text.items() for off in range(2 * k + 1)
               if p[off:off + w] == want or ("?" in p[off:off + w] and
                                             all(x in ("?", y) for x, y in zip(p[off:off + w], want)))]
    p, q = preds.values()
    differ = [0]
    for x, y in zip(p, q):
        differ.append(differ[-1] + (x is not None and y is not None and x != y))
    b = min(differ[off + w] - differ[off] for off in range(2 * k + 1))
    rate = (2 * k + 1) * len(AD_MAPPINGS) * 2.0 ** -b
    found = sorted({m for m, _ in matches})
    result = ("ambiguous" if rate >= RATE_MAX or len(found) > 1 else found[0] if found else "offset-outside-bound")
    return {"result": result, "rate": rate, "b": b, "anchor": t, "matches": matches}


def offset_set(question, questions_path=QUESTIONS):
    """(D, K) from the question's source, or None before kit.py --layout has fixed it."""
    for line in Path(questions_path).read_text(encoding="utf-8").split("\n"):
        cols = line.split("\t")
        if cols[0] == question and len(cols) > 8:
            m = OFFSET_SET.search(cols[8])
            return (int(m.group(1)), int(m.group(2))) if m else None
    return None


def derive(records):
    """kit.derive: the mapping each READS snap shows, as the metric `mapping`, with `rate` and `b`."""
    from kit import noise_draws
    out = {}
    for snap, question in READS.items():
        ours, base, fixed = records.get(("snap", snap)), records.get(("snap", ANCHOR)), offset_set(question)
        if not (ours and base and fixed and "data" in ours and "data" in base):
            continue
        r = read(base["data"], ours["data"], noise_draws()[snap], *fixed)
        out[("snap", snap)] = {**ours, "mapping": r["result"], "rate": f"{r['rate']:.3g}" if r["rate"] is not None else "-",
                               "b": r["b"]}
    return out


SPAN = re.compile(r"^S \d+ noise=(\d+) ", re.M)


def distance(dplog, snap):
    """The fork's noise clocks from the anchor's first pixel to the snap's, from a kit-noise run's ARES_DPLOG:
    each one-line draw is one span, in sets.NOISE_CASES order."""
    from romgen.suites.calib import sets
    first, n = {}, 0
    for name, _, _, draws in sets.NOISE_CASES:
        first[name], n = n, n + len(draws)
    clocks = [int(c) for c in SPAN.findall(dplog)]
    if len(clocks) != n:
        raise ValueError(f"{len(clocks)} spans, not the {n} kit-noise draws")
    return clocks[first[snap]] - clocks[first[ANCHOR]]


def offset_table(run_dir):
    """The offset set kit.py --layout fixes for each READS snap: D and K over every fork run of kit-noise
    (layout pads 0-7, every boot delay), from the .dplog run.sh writes beside each log."""
    run_dir = Path(run_dir)
    out = []
    for snap, question in READS.items():
        by_pad = {}
        for path in sorted(run_dir.glob("**/kit-noise.dplog")):
            rel = path.relative_to(run_dir).parts
            pad = int(rel[0][1:]) if re.fullmatch(r"p\d+", rel[0]) else 0
            by_pad.setdefault(pad, []).append(distance(path.read_text(), snap))
        if not by_pad:
            out.append(f"noise offset {snap}: no kit-noise .dplog in {run_dir} (calibration/run.sh writes them)")
            continue
        every = [d for ds in by_pad.values() for d in ds]
        lo, hi = min(every), max(every)
        d = (lo + hi) // 2
        out.append(f"noise offset {snap} ({question}): {len(every)} runs, pads " +
                   ", ".join(f"{p}: {min(ds)}..{max(ds)}" for p, ds in sorted(by_pad.items())) +
                   f"; offset set D = {d} +- {max(hi - d, d - lo)}")
    return "\n".join(out)
