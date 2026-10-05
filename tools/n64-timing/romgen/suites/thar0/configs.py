"""The 100 timing specs of Thar0/RDP-Timing-Tests src/test_main.c (timing_specs[]), in order.

GROUP and AC_GROUP mirror the C macros of the same names, so each line below matches one line
of the C table. `desc` is the C description string, padding included.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Spec:
    two_cycle: bool
    color_read: bool
    depth_read: bool
    depth_write: bool
    depth_pass: bool
    zb_same_bank: bool
    alpha_compare: bool
    alpha_compare_threshold: int
    rectangle_alpha: int
    vi_on: bool
    vi_same_bank: bool
    desc: str

    @property
    def id(self):
        """A stable name for comparator output, built from the flags."""
        if self.alpha_compare:
            zb = "ac-zcmp" if self.depth_read else "ac"
        elif not (self.depth_read or self.depth_write):
            zb = "nozb"
        else:
            zb = {(True, False): "zbr", (False, True): "zbw", (True, True): "zbrw"}[
                (self.depth_read, self.depth_write)]
            if self.depth_read:
                zb += "-pass" if self.depth_pass else "-fail"
        parts = [zb]
        if self.depth_read or self.depth_write or self.alpha_compare:
            parts.append("zbsame" if self.zb_same_bank else "zbsep")
        parts.append(("visame" if self.vi_same_bank else "visep") if self.vi_on else "vioff")
        parts.append("imrd" if self.color_read else "noimrd")
        parts.append("2cyc" if self.two_cycle else "1cyc")
        return "-".join(parts)


CYC1, CYC2 = False, True
NCRD, CRD = False, True
ZB_DISABLED = (False, False, False, False)
ZB_R = (True, False)
ZB_W = (False, True, True)
ZB_RW = (True, True)
AC_DISABLED = (False, 128, 255)
AC_ENABLED = (True, 128, 96)
ZB_SAME, ZB_DIFF = True, False
Z_FAIL, Z_PASS = False, True
VI_SAME, VI_DIFF = True, False
VI_ON = True
VI_OFF = (False, False)


def GROUP(*settings):
    *flags, desc = [x for s in settings for x in (s if isinstance(s, tuple) else (s,))]
    return [Spec(CYC1, NCRD, *flags, desc + ", image_read off, 1-cycle"),
            Spec(CYC2, NCRD, *flags, desc + ", image_read off, 2-cycle"),
            Spec(CYC1, CRD, *flags, desc + ", image_read on,  1-cycle"),
            Spec(CYC2, CRD, *flags, desc + ", image_read on,  2-cycle")]


def AC_GROUP(im_rd, z_cmp, zb_loc, desc):
    return [Spec(CYC1, im_rd, z_cmp, False, False, zb_loc, *AC_ENABLED, *VI_OFF, desc + ", 1-cycle"),
            Spec(CYC2, im_rd, z_cmp, False, False, zb_loc, *AC_ENABLED, *VI_OFF, desc + ", 2-cycle")]


SPECS = [
    *GROUP(ZB_DISABLED, AC_DISABLED, VI_OFF, "No ZB, No VI"),
    *GROUP(ZB_DISABLED, AC_DISABLED, VI_ON, VI_SAME, "No ZB, VI, FB + VI same    "),
    *GROUP(ZB_DISABLED, AC_DISABLED, VI_ON, VI_DIFF, "No ZB, VI, FB + VI separate"),
    *GROUP(ZB_R, Z_FAIL, ZB_SAME, AC_DISABLED, VI_OFF, "ZB Read-Only, No VI, Z Fail, FB + ZB same    "),
    *GROUP(ZB_R, Z_FAIL, ZB_DIFF, AC_DISABLED, VI_OFF, "ZB Read-Only, No VI, Z Fail, FB + ZB separate"),
    *GROUP(ZB_R, Z_PASS, ZB_SAME, AC_DISABLED, VI_OFF, "ZB Read-Only, No VI, Z Pass, FB + ZB same    "),
    *GROUP(ZB_R, Z_PASS, ZB_DIFF, AC_DISABLED, VI_OFF, "ZB Read-Only, No VI, Z Pass, FB + ZB separate"),
    *GROUP(ZB_W, ZB_SAME, AC_DISABLED, VI_OFF, "ZB Write-Only, No VI, FB + ZB same    "),
    *GROUP(ZB_W, ZB_DIFF, AC_DISABLED, VI_OFF, "ZB Write-Only, No VI, FB + ZB separate"),
    *GROUP(ZB_RW, Z_FAIL, ZB_SAME, AC_DISABLED, VI_OFF, "ZB Read/Write, No VI, Z Fail, FB + ZB same    "),
    *GROUP(ZB_RW, Z_FAIL, ZB_DIFF, AC_DISABLED, VI_OFF, "ZB Read/Write, No VI, Z Fail, FB + ZB separate"),
    *GROUP(ZB_RW, Z_PASS, ZB_SAME, AC_DISABLED, VI_OFF, "ZB Read/Write, No VI, Z Pass, FB + ZB same    "),
    *GROUP(ZB_RW, Z_PASS, ZB_DIFF, AC_DISABLED, VI_OFF, "ZB Read/Write, No VI, Z Pass, FB + ZB separate"),
    *GROUP(ZB_RW, Z_FAIL, ZB_DIFF, AC_DISABLED, VI_ON, VI_DIFF, "ZB Read/Write, VI, Z Fail, FB + ZB + VI separate    "),
    *GROUP(ZB_RW, Z_FAIL, ZB_DIFF, AC_DISABLED, VI_ON, VI_SAME, "ZB Read/Write, VI, Z Fail, FB + VI same, ZB separate"),
    *GROUP(ZB_RW, Z_FAIL, ZB_SAME, AC_DISABLED, VI_ON, VI_DIFF, "ZB Read/Write, VI, Z Fail, FB + ZB same, VI separate"),
    *GROUP(ZB_RW, Z_FAIL, ZB_SAME, AC_DISABLED, VI_ON, VI_SAME, "ZB Read/Write, VI, Z Fail, FB + ZB + VI same        "),
    *GROUP(ZB_RW, Z_PASS, ZB_DIFF, AC_DISABLED, VI_ON, VI_DIFF, "ZB Read/Write, VI, Z Pass, FB + ZB + VI separate    "),
    *GROUP(ZB_RW, Z_PASS, ZB_DIFF, AC_DISABLED, VI_ON, VI_SAME, "ZB Read/Write, VI, Z Pass, FB + VI same, ZB separate"),
    *GROUP(ZB_RW, Z_PASS, ZB_SAME, AC_DISABLED, VI_ON, VI_DIFF, "ZB Read/Write, VI, Z Pass, FB + ZB same, VI separate"),
    *GROUP(ZB_RW, Z_PASS, ZB_SAME, AC_DISABLED, VI_ON, VI_SAME, "ZB Read/Write, VI, Z Pass, FB + ZB + VI same        "),
    *AC_GROUP(False, False, ZB_SAME, "Alpha Compare, image_read off, z_compare off, FB + ZB same    "),
    *AC_GROUP(False, True, ZB_SAME, "Alpha Compare, image_read off, z_compare on,  FB + ZB same    "),
    *AC_GROUP(True, False, ZB_SAME, "Alpha Compare, image_read on,  z_compare off, FB + ZB same    "),
    *AC_GROUP(True, True, ZB_SAME, "Alpha Compare, image_read on,  z_compare on,  FB + ZB same    "),
    *AC_GROUP(False, False, ZB_DIFF, "Alpha Compare, image_read off, z_compare off, FB + ZB separate"),
    *AC_GROUP(False, True, ZB_DIFF, "Alpha Compare, image_read off, z_compare on,  FB + ZB separate"),
    *AC_GROUP(True, False, ZB_DIFF, "Alpha Compare, image_read on,  z_compare off, FB + ZB separate"),
    *AC_GROUP(True, True, ZB_DIFF, "Alpha Compare, image_read on,  z_compare on,  FB + ZB separate"),
]

assert len(SPECS) == 100
assert len({s.id for s in SPECS}) == 100
