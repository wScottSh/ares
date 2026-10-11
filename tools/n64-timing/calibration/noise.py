"""The noise-mapping reader (prehw-plan.md U-NOISE-READER, U-NOISE-KIT, U-NOISE-KIT2): which mapping of the RDP's
noise bits a kit-noise or kit-noise2 snap's pixels show, over an offset set fixed before any console data.

The anchor is the noise clock of snap/rect-1016's first pixel in the same log, found from its a bits (Thar0's
all-ones window method, rdp-noise.md:37, 62). A mapping snap's first pixel is at the anchor plus D + k,
|k| <= K, where D and K come from the fork (kit.py --layout) and are written in the question's source. Each
mapping predicts each pixel the snap stores; the reader returns the mapping that alone matches,
`offset-outside-bound` when none does, or `ambiguous`, and the false-match rate (2K+1) x mappings x 2^-b,
with b the fewest pixels the mappings disagree on at any offset in the set.
"""
import itertools
import re
from pathlib import Path

#The three LFSRs as timed.hpp NoiseLfsr models them (rdp-noise.md:33, 37, from Thar0/RDP-Noise's console
#dumps): degree and taps in register order, top bit the current output, all ones at power-on, c one step
#ahead, one step per RDP clock.
LFSRS = {"a": (29, 1 << 1 | 1 << 28), "b": (28, 1 << 2 | 1 << 27), "c": (27, 1 << 0 | 1 << 1 | 1 << 4 | 1 << 26)}
#A mapping takes one pixel's (a3, b3, c3), each LFSR's top three register bits: its outputs at the pixel's
#clock and the next two, as the register shifts left and outputs its top bit (timed.hpp NoiseLfsr).
#G_AD_NOISE's value, per cited source (rdp-noise.md:39): Angrylion (noise >> 6) & 7, the combiner NOISE bits
#with a highest; MiSTer random2 & '1', some odd value 1-7.
AD_MAPPINGS = {"angrylion": lambda a3, b3, c3: ((a3 >> 2) << 2 | (b3 >> 2) << 1 | c3 >> 2,),
               "mister-odd": lambda a3, b3, c3: (1, 3, 5, 7)}
#G_CD_NOISE's packed 9-bit dither (red bits 0-2, green 3-5, blue 6-8: rdp_blend.c rdp_blend_output), whose
#value >> 1 is the G_AC_DITHER threshold. No source maps a, b and c to them (U-NOISE-KIT's alt search), so
#the fork's (rdp_core.c rdp_noise_dither_color) is read against the mutation prehw-plan.md U-NOISE-KIT2
#fixed before any measurement: the same top three bits with the channels in c, b, a order.
CD_MAPPINGS = {"abc-top3": lambda a3, b3, c3: a3 << 6 | b3 << 3 | c3,
               "cba-top3": lambda a3, b3, c3: c3 << 6 | b3 << 3 | a3}
#Each question's mappings and the one the fork implements.
MAPPINGS = {"noise-alpha-dither": AD_MAPPINGS, "noise-dither-bits": CD_MAPPINGS}
FORK = {"noise-alpha-dither": "angrylion", "noise-dither-bits": "abc-top3"}
RATE_MAX = 1e-6
ANCHOR = "rect-1016"
#(kit ROM, mapping snap): the question that reads it, whose source holds the snap's offset set.
READS = {("kit-noise", "ad-noise-7f"): "noise-alpha-dither",
         ("kit-noise2", "cd-noise-84"): "noise-dither-bits",
         ("kit-noise2", "ac-dither"): "noise-dither-bits"}
#"offset set [snap] D = .. +- ..": a question with one mapping snap may leave the snap out.
OFFSET_SET = re.compile(r"offset set (?:([\w-]+) )?D = (\d+) \+- (\d+)")
#A pixel no single noise value set predicts.
EITHER = object()
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


def states(t, n):
    """[(a3, b3, c3)] for the n RDP clocks from t."""
    px = bits(t, n + 2)
    return [tuple(p[j] << 2 | q[j] << 1 | r[j] for j in range(3)) for p, q, r in zip(px, px[1:], px[2:])]


def candidates(question, mapping, state):
    """Every (ad, cd, ac) noise value set the question's mapping allows at one pixel's state."""
    if question == "noise-alpha-dither":
        return [(v, 0, 0) for v in AD_MAPPINGS[mapping](*state)]
    cd = CD_MAPPINGS[mapping](*state)
    #ac-dither also adds G_AD_NOISE, which noise-alpha-dither decides, so it takes every cited AD value.
    return [(v, cd, cd >> 1) for v in sorted({v for f in AD_MAPPINGS.values() for v in f(*state)})]


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


def observed(data, bits16):
    """Each pixel as kit.noise_pixel gives it: its RGB (16 bpp: 5 bits a channel), or None where the draw did
    not write it (the kit clears the surface to 0 and no draw's color is 0)."""
    if bits16:
        px = [int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data), 2)]
        return [(v >> 11 & 31, v >> 6 & 31, v >> 1 & 31) if v else None for v in px]
    return [tuple(data[i:i + 3]) if any(data[i:i + 4]) else None for i in range(0, len(data), 4)]


def predict(states_, draw, question, mapping):
    """The mapping's pixel at each state, or EITHER where its values give different pixels."""
    from kit import noise_pixel
    memo = {}
    for s in set(states_):
        seen = {noise_pixel(draw, *v) for v in candidates(question, mapping, s)}
        memo[s] = seen.pop() if len(seen) == 1 else EITHER
    return [memo[s] for s in states_]


def read(anchor_data, snap_data, draw, question, d, k):
    """{result, rate, b, anchor, matches}: the reader on one log, offset set d +- k."""
    t = anchor(anchor_data)
    if t is None:
        return {"result": "no-anchor", "rate": None, "b": None, "anchor": None, "matches": []}
    seen = observed(snap_data, draw["bits16"])
    w = len(seen)
    at = states(t + d - k, 2 * k + w)
    preds = {m: predict(at, draw, question, m) for m in MAPPINGS[question]}
    letters = {}
    code = lambda px: "?" if px is EITHER else letters.setdefault(px, chr(0x41 + len(letters)))  # noqa: E731
    want = "".join(map(code, seen))
    text = {m: "".join(map(code, p)) for m, p in preds.items()}
    matches = [(m, off - k) for m, p in text.items() for off in range(2 * k + 1)
               if p[off:off + w] == want or ("?" in p[off:off + w] and
                                             all(x in ("?", y) for x, y in zip(p[off:off + w], want)))]
    b = None
    for p, q in itertools.combinations(preds.values(), 2):
        differ = [0]
        for x, y in zip(p, q):
            differ.append(differ[-1] + (x is not EITHER and y is not EITHER and x != y))
        b = min([differ[off + w] - differ[off] for off in range(2 * k + 1)] + ([b] if b is not None else []))
    rate = (2 * k + 1) * len(preds) * 2.0 ** -b
    found = sorted({m for m, _ in matches})
    result = ("ambiguous" if rate >= RATE_MAX or len(found) > 1 else found[0] if found else "offset-outside-bound")
    return {"result": result, "rate": rate, "b": b, "anchor": t, "matches": matches}


def offset_set(question, snap, questions_path=QUESTIONS):
    """(D, K) for the snap from the question's source, or None before kit.py --layout has fixed it."""
    for line in Path(questions_path).read_text(encoding="utf-8").split("\n"):
        cols = line.split("\t")
        if cols[0] == question and len(cols) > 8:
            fixed = {m.group(1): (int(m.group(2)), int(m.group(3))) for m in OFFSET_SET.finditer(cols[8])}
            return fixed.get(snap, fixed.get(None))
    return None


def derive(records, rom):
    """kit.derive: the mapping each READS snap of the log's kit ROM shows, as the metric `mapping`, with `rate`
    and `b`."""
    from kit import noise_draws
    out = {}
    for (kit, snap), question in READS.items():
        ours, base, fixed = records.get(("snap", snap)), records.get(("snap", ANCHOR)), offset_set(question, snap)
        if kit != rom or not (ours and base and fixed and "data" in ours and "data" in base):
            continue
        r = read(base["data"], ours["data"], noise_draws(kit)[snap], question, *fixed)
        out[("snap", snap)] = {**ours, "mapping": r["result"], "rate": f"{r['rate']:.3g}" if r["rate"] is not None else "-",
                               "b": r["b"]}
    return out


SPAN = re.compile(r"^S \d+ noise=(\d+) ", re.M)


def distance(dplog, kit, snap):
    """The fork's noise clocks from the anchor's first pixel to the snap's, from a run's ARES_DPLOG of the kit
    ROM: each one-line draw is one span, in sets.NOISE_KITS order."""
    from romgen.suites.calib import sets
    first, n = {}, 0
    for name, _, _, draws in sets.NOISE_KITS[kit]:
        first[name], n = n, n + len(draws)
    clocks = [int(c) for c in SPAN.findall(dplog)]
    if len(clocks) != n:
        raise ValueError(f"{len(clocks)} spans, not the {n} {kit} draws")
    return clocks[first[snap]] - clocks[first[ANCHOR]]


def offset_table(run_dir):
    """The offset set kit.py --layout fixes for each READS snap: D and K over every fork run of its kit ROM
    (layout pads 0-7, every boot delay), from the .dplog run.sh writes beside each log."""
    run_dir = Path(run_dir)
    out = []
    for (kit, snap), question in READS.items():
        by_pad = {}
        for path in sorted(run_dir.glob(f"**/{kit}.dplog")):
            rel = path.relative_to(run_dir).parts
            pad = int(rel[0][1:]) if re.fullmatch(r"p\d+", rel[0]) else 0
            by_pad.setdefault(pad, []).append(distance(path.read_text(), kit, snap))
        if not by_pad:
            out.append(f"noise offset {snap}: no {kit} .dplog in {run_dir} (calibration/run.sh writes them)")
            continue
        every = [d for ds in by_pad.values() for d in ds]
        lo, hi = min(every), max(every)
        d = (lo + hi) // 2
        out.append(f"noise offset {snap} ({question}): {len(every)} runs, pads " +
                   ", ".join(f"{p}: {min(ds)}..{max(ds)}" for p, ds in sorted(by_pad.items())) +
                   f"; offset set {snap} D = {d} +- {max(hi - d, d - lo)}")
    return "\n".join(out)
