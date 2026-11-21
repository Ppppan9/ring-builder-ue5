# -*- coding: utf-8 -*-
"""解环关卡核心逻辑（纯 Python，不依赖 bpy）。
逐行移植自星星 AE 版 src/lib/level.ts / bind.ts / gen/solver.ts / unlock.ts / outro.ts（v1.0.5；v1.4 起按 AE 1.0.9 加入三环结道具：props / 道具扣 fixed link），
保证 Blender 里的解环规划、时间安排、移出方向、破碎碎片与 AE 面板一致（tests/ 里与 JS 输出逐项比对）。"""
import json, math, os

D2R = math.pi / 180.0
_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "assets_manifest.json"), "r", encoding="utf-8") as _f:
    ASSETS = json.load(_f)
ASSET_MAP = {a["id"]: a for a in ASSETS}
COLOR_ZH = {"blue": "蓝", "green": "绿", "orange": "橙", "purple": "紫", "red": "红", "cyan": "浅蓝", "silver": "银"}
SHAPE_ZH = {"full": "整圆环", "gap": "C 形环", "t": "T 形扣", "u": "U 形扣", "sleeve": "套筒扣", "oval": "椭圆扣", "arc": "圆弧角件",
            "bigarc": "大弧", "stick": "直棒", "elbow": "直角弯", "ubend": "U 形弯", "knot": "三环结"}

GAP_SAFE = 22.0           # bind.ts GAP_SAFE_DEFAULT
MAX_UNLOCK_CLASPS = math.inf   # unlock.ts 1.0.14：不再按扣子数量限制（规则见 sequence 部分）
BLOCK_DEG = 8.0
T_LEN_MAX = 160           # level.ts 1.0.14 T 扣最多拉长（素材像素）
PASS_WIDTH = {"t": 42, "u": 42, "oval": 48, "sleeve": 88, "arc": 88}   # rules.ts DEFAULT_RULES

DEFAULT_UNLOCK = dict(mode="duration", secPerStep=0.6, degPerSec=120, easeOut=33, easeIn=33, start="cti", gap=0.1, deps=False, dir="auto",
                      moveOut=True, moveDist=160, moveSec=0.5, fade=True, fadeSec=0.5, fadeDelay=0, shatter=False, shards=12,
                      shatterSec=0.8, spread=60, shatterRev=False, ringGap=0.15)


def fwd(a):
    return a % 360.0


def norm(a):
    return ((a % 360.0) + 540.0) % 360.0 - 180.0


def d_ang(a, b):
    d = fwd(a - b)
    return 360 - d if d > 180 else d


def asset(aid):
    return ASSET_MAP.get(aid) or {}


KNOT_ASSET = "prop_knot_silver"


def owner_of(L, oid):
    """level.ts ownerOf：扣子所属对象 = 圆环或道具（AE 1.0.8 三环结；道具与 Ring 结构兼容）"""
    for r in L["rings"]:
        if r["id"] == oid:
            return r
    for p in L.get("props") or []:
        if p["id"] == oid:
            return p
    return None


def is_prop_id(L, oid):
    return any(p["id"] == oid for p in (L.get("props") or []))


# ---------------- level.ts / bind.ts 几何 ----------------
def clasp_world(ring, c):
    t = (ring["rotation"] + c["angle"]) * D2R
    s = ring["scale"] / 100.0
    return {"x": ring["x"] + s * c["radius"] * math.cos(t), "y": ring["y"] + s * c["radius"] * math.sin(t),
            "rotation": ring["rotation"] + c["angle"] + 90 + c.get("rotation", 0), "scale": c["scale"]}


def hook_offset(aid):
    a = asset(aid)
    if not a or not a.get("attach"):
        return 0.0
    if a.get("shape") == "t" and a.get("capSpan"):
        return a["attach"][1] - (a["capSpan"][0] + a["capSpan"][1]) / 2.0
    return 0.0


def clasp_len(c):
    """level.ts claspLen（1.0.14）：T 扣拉长量，非 T 扣恒 0，夹在 0..T_LEN_MAX"""
    a = asset(c.get("asset", ""))
    if not a or a.get("shape") != "t":
        return 0.0
    try:
        v = float(c.get("len") or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(float(T_LEN_MAX), v)) if math.isfinite(v) else 0.0


def hook_off(c):
    """bind.ts hookOff（1.0.14）= 素材扣长 + 拉长量"""
    return hook_offset(c["asset"]) + clasp_len(c)


# ---- 1.0.10 钻戒（level.ts gemDist / gemClear / rotLocked）----
DIAMOND_ASSET = "ring_full_diamond"


def is_gem_ring(r):
    return bool(r and asset(r.get("asset", "")).get("gem"))


def gem_dist(r, d):
    a = asset(r["asset"])
    if not a.get("gem"):
        return 180.0
    return abs(norm(d - ((a.get("gemAngle", -90)) + r["rotation"])))


def gem_clear(r, d):
    a = asset(r["asset"])
    return (not a.get("gem")) or gem_dist(r, d) > a.get("gemHalf", 18)


def rot_locked(aid):
    return bool(asset(aid).get("gem"))


# ---- 1.0.17 三环结的扣子不能套钻戒（level.ts knotGemPair / knotGemBanned / KNOT_GEM_MSG）----
KNOT_GEM_MSG = "三环结的扣子不能套钻戒（钻戒没有开口，解不开）"
KNOT_GEM_LABEL = "✕ 未扣上：三环结不能套钻戒"


def closed_locked(aid):
    """封闭（没有开口）且不能转的环素材（= 钻戒）"""
    a = asset(aid) if aid else {}
    return bool(a) and a.get("kind") == "ring" and a.get("shape") != "gap" and rot_locked(aid)


def knot_gem_pair(H, B):
    """「挂 H、套 B」：H = 道具（三环结）且 B = 封闭且不能转的环 ⇒ 禁止"""
    return bool(H) and bool(B) and asset(H.get("asset", "")).get("kind") == "prop" and closed_locked(B.get("asset"))


def knot_gem_banned(L, c):
    if not c.get("touchRingId"):
        return False
    return knot_gem_pair(owner_of(L, c.get("ringId")), next((r for r in L.get("rings", []) if r["id"] == c["touchRingId"]), None))


def hook_point(A, c):
    w = clasp_world(A, c)
    off = hook_off(c) * c["scale"] / 100.0
    t = (w["rotation"] - 90) * D2R
    return {"x": w["x"] + off * math.cos(t), "y": w["y"] + off * math.sin(t), "attach": {"x": w["x"], "y": w["y"]}}


SKIN_TUBE = {"jade": (115.5, 173.0), "wood": (115.5, 173.0), "block": (115.5, 173.0), "gold": (115.5, 173.0), "amethyst": (115.5, 173.0)}   # skinClasp.ts SKIN_TUBE（1.0.15 + 亮面金属 gold / 紫水晶 amethyst）
RING_SKINS = ("default", "jade", "wood", "block", "gold", "amethyst")    # skins.ts RING_SKINS（1.0.15）
SKIN_ZH = {"default": "默认", "jade": "玉", "wood": "木", "block": "彩块", "gold": "亮面金属", "amethyst": "紫水晶"}   # 1.0.16 gold 显示为「亮面金属」
CLASP_MATS = ("gold", "silver")   # level.ts 1.0.15 Clasp.mat


def normalize_skin(s):
    """skins.ts normalizeSkin（1.0.16：'metal' 是亮面金属的别名 ⇒ gold；本插件旧名 candy ⇒ block）；未知 ⇒ default"""
    if s == "metal":
        return "gold"
    if s == "candy":
        return "block"
    return s if s in RING_SKINS else "default"


def clasp_metal(L, c):
    """skinClasp.ts claspMetal（1.0.15）：扣子自己选的 mat（gold / silver）优先；没选 ⇒ 钻戒相关 = 'gem'（粉银），否则 None（材质原样）"""
    m = c.get("mat")
    if m in CLASP_MATS:
        return m
    rs = {r["id"]: r for r in L.get("rings", [])}
    return "gem" if any(is_gem_ring(rs.get(i)) for i in (c.get("ringId"), c.get("touchRingId")) if i) else None


def tube_of(R, skin=None):
    """skinClasp.ts tubeOf：环管中线半径与半宽（素材像素）；换皮的环用材质贴图的管，钻戒（fixedSkin）不换皮"""
    a = ASSET_MAP.get(R["asset"], {})
    sk = normalize_skin(skin or "default")
    t = SKIN_TUBE.get(sk) if (a.get("kind") == "ring" and not a.get("fixedSkin")) else None
    inner, outer = (t if t else (a.get("innerRadius", 126), a.get("outerRadius", 176)))
    return {"mid": (inner + outer) / 2.0, "hw": (outer - inner) / 2.0}


def clasp_seat(A, B, c, skin=None):
    """skinClasp.ts claspSeat：扣点落在被扣环 B 的环管上 = on，否则 free（含落在 C 口里）"""
    if knot_gem_pair(A, B):
        return "free"            # 1.0.17 三环结的扣子不能套钻戒 ⇒ 恒「未扣上」
    h = hook_point(A, c)
    sB = B["scale"] / 100.0
    t = tube_of(B, skin)
    d = math.hypot(h["x"] - B["x"], h["y"] - B["y"])
    if abs(d - t["mid"] * sB) > t["hw"] * sB + 0.5:
        return "free"
    ba = ASSET_MAP.get(B["asset"], {})
    if ba.get("shape") == "gap":
        dr = math.degrees(math.atan2(h["y"] - B["y"], h["x"] - B["x"]))
        off = abs((((dr - ((ba.get("gapAngle") or 0) + B.get("rotation", 0))) % 360) + 540) % 360 - 180)
        if off < (ba.get("gapDeg") or 0) / 2.0:
            return "free"
    return "on"


def clasp_state(L, c):
    """AE 1.0.14 标签：已扣上 → None；选了被扣环但扣头不在它的环管上 → 「未扣上」；没有被扣环 → 「无被扣环」"""
    A = owner_of(L, c.get("ringId"))
    if not A:
        return None
    if not c.get("touchRingId"):
        return "无被扣环"
    B = next((r for r in L["rings"] if r["id"] == c["touchRingId"]), None)
    if not B or clasp_seat(A, B, c, L.get("skin")) == "free":
        return "未扣上"
    return None


def band(r):
    a = asset(r["asset"])
    s = r["scale"] / 100.0
    return {"inner": a.get("innerRadius", 126) * s, "outer": a.get("outerRadius", 176) * s, "mid": a.get("midRadius", 151) * s}


def engaged_not_off(L, c):
    """bind.ts engagement() 的 'off' 判定（求解器 requireEngage 只排除 off）"""
    rings = {r["id"]: r for r in L["rings"]}
    A, B = owner_of(L, c["ringId"]), rings.get(c.get("touchRingId"))
    if not A or not B:
        return False
    h = hook_point(A, c)
    bB = band(B)
    ca = asset(c["asset"])
    dB = math.hypot(h["x"] - B["x"], h["y"] - B["y"])
    slack = min(ca.get("width", 40), ca.get("height", 40)) * c["scale"] / 100.0 / 2.0
    return bB["inner"] - slack <= dB <= bB["outer"] + slack


# ---------------- gen/solver.ts ----------------
def level_to_puzzle(L):
    idx = {r["id"]: i for i, r in enumerate(L["rings"])}
    rings = []
    for x in L["rings"]:
        a = asset(x["asset"])
        rings.append({"id": x["id"], "gap0": (a.get("gapAngle") or 0) + x["rotation"] if a.get("shape") == "gap" else None, "gapDeg": a.get("gapDeg") or 0})
    links = []
    for c in L["clasps"]:
        t = c.get("touchRingId")
        if not t or t == c["ringId"] or t not in idx:
            continue
        fixed = c["ringId"] not in idx            # 道具扣（三环结）：道具不转，from = -1
        A = owner_of(L, c["ringId"]) if fixed else L["rings"][idx[c["ringId"]]]
        if not A:
            continue
        B = L["rings"][idx[t]]
        kg = knot_gem_pair(A, B)         # 1.0.17 三环结套钻戒：engagement 恒「脱离」，但仍拴着钻戒 ⇒ 不能当成已解开
        if not kg and not engaged_not_off(L, c):
            continue
        ba, ca = asset(B["asset"]), asset(c["asset"])
        p = hook_point(A, c)
        sB = B["scale"] / 100.0
        w = PASS_WIDTH.get(ca.get("shape"), min(ca.get("width", 40), ca.get("height", 40))) * c["scale"] / 100.0
        chord = (ba.get("gapWidthPx") or 0) * sB
        half = math.asin(min(1.0, w / 2.0 / ((ba.get("midRadius") or 151) * sB))) / D2R
        lk = {"id": c["id"], "from": -1 if fixed else idx[A["id"]], "to": idx[B["id"]], "owner": A["id"], "phi": math.atan2(p["y"] - B["y"], p["x"] - B["x"]) / D2R,
              "tol": max(0.0, (ba.get("gapDeg") or 0) / 2.0 - half), "pass": (not kg) and ba.get("shape") == "gap" and w < chord}
        if fixed:
            lk["fixed"] = True
        if kg:
            lk["knotGem"] = True
        links.append(lk)
    return {"rings": rings, "links": links}


# ---------------- sequence.ts（AE 1.0.14：一个一个移出，按扣子逐枚判断）----------------
from decimal import Decimal, ROUND_HALF_UP
from functools import cmp_to_key


def to_fixed(x, n):
    """JS Number.prototype.toFixed + 一元 +（按二进制精确值四舍五入，平局远离 0）"""
    return float(Decimal(x).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def _cmp_chain(*vals):
    """JS 比较器 a || b || c：NaN / 0 视为假，取第一个真值"""
    for v in vals:
        if v != 0 and not (isinstance(v, float) and math.isnan(v)):
            return v
    return 0


class SeqModel(object):
    """sequence.ts seqModel：状态 s = {th, gone, rel}"""

    def __init__(self, p):
        self.p = p
        self.L = p["links"]

    def engaged(self, s, k):
        l = self.L[k]
        return not s["rel"][k] and not s["gone"][l["to"]] and (l["from"] < 0 or not s["gone"][l["from"]])

    def aligned(self, s, k):
        l = self.L[k]
        g = self.p["rings"][l["to"]]["gap0"]
        return bool(l["pass"]) and g is not None and d_ang(g + s["th"][l["to"]], l["phi"]) <= l["tol"] + 1e-9

    def pins(self, s, i):
        return [k for k in range(len(self.L)) if self.engaged(s, k) and (self.L[k]["from"] == i or self.L[k]["to"] == i)]

    def removable(self, s, i):
        return not s["gone"][i] and all(self.aligned(s, k) for k in self.pins(s, i))

    def rot_opts(self, s, i, dir="auto"):
        g = self.p["rings"][i]["gap0"]
        if s["gone"][i] or g is None:
            return []
        ks = self.pins(s, i)
        if any(self.L[k]["from"] == i and not self.aligned(s, k) for k in ks):
            return []
        inc = [k for k in ks if self.L[k]["to"] == i]
        cur = g + s["th"][i]
        out = []
        far = [k for k in inc if d_ang(cur, self.L[k]["phi"]) > self.L[k]["tol"] + 1e-9]
        fwT = [fwd(self.L[k]["phi"] - cur) for k in far]
        bwT = [fwd(cur - self.L[k]["phi"]) for k in far]
        if dir != "ccw" and fwT:
            out.append(to_fixed(min(fwT), 3))
        if dir != "cw" and bwT:
            out.append(-to_fixed(min(bwT), 3))
        return out

    def rotate(self, s, i, d):
        th, rel, released = list(s["th"]), list(s["rel"]), []
        for k in self.pins(s, i):
            if self.L[k]["from"] == i:
                rel[k] = True
                released.append(k)
        th[i] += d
        return {"th": th, "gone": s["gone"], "rel": rel}, released

    def remove(self, s, i):
        gone = list(s["gone"])
        gone[i] = True
        return {"th": s["th"], "gone": gone, "rel": s["rel"]}


def plan_removal(level, target=None, freed=None, deps=False, dir="auto", names=None):
    """sequence.ts planRemoval：target=None ⇒ 全部移出（烘焙）；否则面板解开 target（deps 决定能否先移走不相邻的环）"""
    p = level_to_puzzle(level)
    n = len(p["rings"])
    M = SeqModel(p)
    names = names or {}
    nm = lambda i: names.get(i, i)
    idx = {r["id"]: i for i, r in enumerate(p["rings"])}
    freed = freed or set()
    st = {"s": {"th": [0.0] * n, "gone": [r["id"] in freed for r in p["rings"]], "rel": [False] * len(p["links"])}}
    ti = idx.get(target) if target is not None else None
    if target is not None and ti is None:
        return {"ok": False, "steps": [], "th": {}, "error": "选中的图层不是环", "blockers": []}
    steps, pend = [], []
    adj = []
    for i in range(n):
        a = []
        for l in p["links"]:
            j = l["to"] if l["from"] == i else (l["from"] if l["to"] == i and l["from"] >= 0 else None)
            if j is not None and j not in a:
                a.append(j)
        adj.append(a)

    def nbrs(s, i):
        out = []
        for k in M.pins(s, i):
            j = p["links"][k]["to"] if p["links"][k]["from"] == i else p["links"][k]["from"]
            if j >= 0 and j not in out:
                out.append(j)
        return out

    def dist(s):
        D = [math.inf] * n
        if ti is None:
            return D
        D[ti] = 0
        q = [ti]
        while q:
            nq = []
            for i in q:
                for j in nbrs(s, i):
                    if D[j] == math.inf:
                        D[j] = D[i] + 1
                        nq.append(j)
            q = nq
        return D

    def allowed_remove(s, i):
        if ti is None or i == ti or deps:
            return True
        return i in nbrs(s, ti)

    def candidates(s):
        return [i for i in range(n) if M.removable(s, i) and allowed_remove(s, i)]

    def pick_removal(s, last_rot):
        c = candidates(s)
        if not c:
            return -1
        if ti is not None and ti in c:
            return ti
        D = dist(s)
        nl = nbrs(s, last_rot) if last_rot >= 0 else []

        def cmp(a, b):
            fa = 1 if (last_rot >= 0 and a != last_rot and a in nl) else 0
            fb = 1 if (last_rot >= 0 and b != last_rot and b in nl) else 0
            return _cmp_chain(fb - fa, D[a] - D[b], len(M.pins(s, a)) - len(M.pins(s, b)), a - b)
        return sorted(c, key=cmp_to_key(lambda a, b: (lambda v: -1 if v < 0 else 1 if v > 0 else 0)(cmp(a, b))))[0]

    def do_remove(i):
        s = st["s"]
        links = [p["links"][k]["id"] for k in M.pins(s, i)]
        steps.append({"ring": p["rings"][i]["id"], "rots": list(pend), "links": links})
        del pend[:]
        st["s"] = M.remove(s, i)

    def do_rot(i, d):
        s = st["s"]
        s2, rel = M.rotate(s, i, d)
        in_gap = [k for k in M.pins(s2, i) if p["links"][k]["to"] == i and M.aligned(s2, k) and not M.aligned(s, k)]
        pend.append({"ring": p["rings"][i]["id"], "from": s["th"][i], "to": s["th"][i] + d, "released": [p["links"][k]["id"] for k in rel + in_gap]})
        st["s"] = s2

    def goal():
        s = st["s"]
        return s["gone"][ti] if ti is not None else all(s["gone"])

    last_rot = -1
    guard = 0
    while guard < 6 * n + 20 and not goal():
        guard += 1
        s = st["s"]
        r = pick_removal(s, last_rot)
        if r >= 0:
            do_remove(r)
            last_rot = -1
            continue

        def touched(sq):
            out = []
            for x in sq:
                for j in [x[0]] + adj[x[0]]:
                    if j not in out:
                        out.append(j)
            return out
        rel_n = lambda s_: sum(1 for v in s_["rel"] if v)
        rel0 = rel_n(s)
        frontier = [(s, [], 0.0)]
        found, found_sc, expanded = None, math.inf, 0
        D0 = dist(s)
        depth = 1
        while depth <= 4 and found is None and frontier:
            nxt = []
            for (nst, seq, deg) in frontier:
                for i in range(n):
                    for d in M.rot_opts(nst, i, dir if (ti is not None and i == ti) else "auto"):
                        expanded += 1
                        if expanded > 40000:
                            break
                        st2 = M.rotate(nst, i, d)[0]
                        sq = seq + [(i, d)]
                        dg = deg + abs(d)
                        c = [j for j in touched(sq) if M.removable(st2, j) and allowed_remove(st2, j)]
                        prog = len(c) > 0 or rel_n(st2) > rel0
                        if prog:
                            sc = (0 if (ti is not None and ti in c) else 1e4 if c else 2e4) + dg + (min(D0[x[0]] for x in sq) * 50 if ti is not None else 0)
                            if sc < found_sc:
                                found, found_sc = (st2, sq, dg), sc
                        else:
                            nxt.append((st2, sq, dg))
            frontier = sorted(nxt, key=lambda x: x[2])[:3000] if len(nxt) > 3000 else nxt
            depth += 1
        if found is not None:
            for (i, d) in found[1]:
                do_rot(i, d)
            last_rot = found[1][-1][0]
            continue
        break
    s = st["s"]
    th_out = {r["id"]: s["th"][i] for i, r in enumerate(p["rings"])}
    if goal():
        return {"ok": True, "steps": steps, "th": th_out, "target": target, "deps": [x["ring"] for x in steps if x["ring"] != target]}
    left = [i for i in range(n) if not s["gone"][i]]
    focus = [ti] if ti is not None else left
    why, blockers = [], []
    for i in focus[:3]:
        bad = [k for k in M.pins(s, i) if not M.aligned(s, k)]
        desc = []
        for k in bad:
            l = p["links"][k]
            A = p["rings"][l["from"]]["id"] if l["from"] >= 0 else (l.get("owner") or "道具")
            B = p["rings"][l["to"]]["id"]
            bl = B if l["from"] == i else A
            if bl not in blockers:
                blockers.append(bl)
            g = p["rings"][l["to"]]["gap0"]
            if l.get("knotGem"):
                desc.append("扣子 %s（%s → %s）：%s" % (nm(l["id"]), nm(A), nm(B), KNOT_GEM_MSG))
            elif not l["pass"] or g is None:
                desc.append("扣子 %s（%s → %s）穿在%s上，永远放不开" % (nm(l["id"]), nm(A), nm(B), "闭口环" if g is None else "比扣子窄的开口"))
            else:
                desc.append("扣子 %s（%s 挂、穿在 %s 上）离 %s 的开口 %d°" % (nm(l["id"]), nm(A), nm(B), nm(B), js_round(d_ang(g + s["th"][l["to"]], l["phi"]))))
        if desc:
            why.append("%s 还被 %d 枚扣子拴着：%s" % (nm(p["rings"][i]["id"]), len(desc), "；".join(desc)))
    # 1.0.17 三环结套钻戒：永远解不开，原因放最前（不论它拴的是不是前三个卡住的环）
    for k, l in enumerate(p["links"]):
        if l.get("knotGem") and not s["rel"][k]:
            t_ = "扣子 %s（%s → %s）：%s" % (nm(l["id"]), nm(l.get("owner") or "道具"), nm(p["rings"][l["to"]]["id"]), KNOT_GEM_MSG)
            if not any(t_ in w for w in why):
                why.insert(0, t_)
            bl = l.get("owner") or p["rings"][l["to"]]["id"]
            if bl not in blockers:
                blockers.append(bl)
    hint = "；可开启“含依赖”先移走挡路的环" if (ti is not None and not deps) else ""
    return {"ok": False, "steps": steps, "th": th_out, "target": target,
            "error": "无法一个一个移出：%s。转动任何一个环都不能让它们的开口对准扣子%s" % ("。".join(why) or "互相卡死", hint),
            "stuck": [p["rings"][i]["id"] for i in left], "blockers": blockers, "deps": [x["ring"] for x in steps]}


def js_round(x):
    """JS Math.round（.5 向 +∞）"""
    return int(math.floor(x + 0.5))


def check_removal(level, steps, freed=None):
    """sequence.ts checkRemoval：重放移出顺序，检查每次转动 / 移出都合法"""
    p = level_to_puzzle(level)
    M = SeqModel(p)
    idx = {r["id"]: i for i, r in enumerate(p["rings"])}
    freed = freed or set()
    s = {"th": [0.0] * len(p["rings"]), "gone": [r["id"] in freed for r in p["rings"]], "rel": [False] * len(p["links"])}
    for st in steps:
        for r in st["rots"]:
            i = idx[r["ring"]]
            if abs(s["th"][i] - r["from"]) > 1e-6:
                return {"ok": False, "error": "%s 转动起点不连续" % r["ring"]}
            own = [k for k in M.pins(s, i) if p["links"][k]["from"] == i and not M.aligned(s, k)]
            if own:
                return {"ok": False, "error": "%s 挂出去的扣子 %s 还穿在邻环上，不能转" % (r["ring"], [p["links"][k]["id"] for k in own])}
            s = M.rotate(s, i, r["to"] - r["from"])[0]
        i = idx[st["ring"]]
        if s["gone"][i]:
            return {"ok": False, "error": "%s 重复移出" % st["ring"]}
        bad = [k for k in M.pins(s, i) if not M.aligned(s, k)]
        if bad:
            return {"ok": False, "error": "%s 移出时还被 %s 拴着（扣子不在开口里）" % (st["ring"], [p["links"][k]["id"] for k in bad])}
        s = M.remove(s, i)
    return {"ok": True}


# ---------------- unlock.ts（1.0.14：planUnlock = planRemoval(target)）----------------
def claspLinks(p, i, freed_idx):
    ks = range(len(p["links"]))
    return ([k for k in ks if p["links"][k]["from"] == i and p["links"][k]["to"] not in freed_idx],
            [k for k in ks if p["links"][k]["to"] == i and p["links"][k]["from"] not in freed_idx])


def plan_unlock(level, target, freed=None, deps=False, names=None, dir="auto"):
    """unlock.ts planUnlock（1.0.14）：一次只动一个环——转环让开口对准扣子、放走相邻环、最后移出目标"""
    freed = set(freed or [])
    p = level_to_puzzle(level)
    ids = [r["id"] for r in p["rings"]]
    if target not in ids:
        return {"ok": False, "target": target, "error": "选中的图层不是环", "blockers": [], "deps": []}
    ti = ids.index(target)
    fr = set(j for j, r in enumerate(p["rings"]) if r["id"] in freed)
    own, inc = claspLinks(p, ti, fr)
    cnt = len(own) + len(inc)
    ex0 = sum(1 for l in p["links"] if (l["from"] == ti and l["to"] in fr) or (l["to"] == ti and l["from"] in fr))
    note = "仍拴着 %d 枚扣子（挂出去 %d、别人穿在它上 %d；已排除 %d 枚：对方环已解开）" % (cnt, len(own), len(inc), ex0)
    if ti in fr or cnt == 0:
        return {"ok": True, "target": target, "already": True, "steps": [], "deps": [], "note": note}
    sp = plan_removal(level, target=target, freed=freed, deps=deps, dir=dir, names=names)
    if not sp["ok"]:
        err = sp.get("error") or ""
        if err.startswith("无法一个一个移出"):
            err = "无法解环" + err[len("无法一个一个移出"):]
        return {"ok": False, "target": target, "error": err, "blockers": sp.get("blockers") or [], "deps": sp.get("deps") or []}
    steps, outs = [], []
    for st in sp["steps"]:
        steps.extend(st["rots"])
        outs.append({"ring": st["ring"], "links": st["links"], "after": len(steps)})
    return {"ok": True, "target": target, "already": False, "steps": steps, "deps": sp.get("deps") or [], "note": note, "outs": outs, "seq": sp["steps"]}


# ---------------- outro.ts ----------------
def _unit(x, y):
    l = math.hypot(x, y)
    return [x / l, y / l] if l > 1e-9 else [0.0, 0.0]


def move_direction(level, ring_id, links):
    R = next(r for r in level["rings"] if r["id"] == ring_id)
    rings = {r["id"]: r for r in level["rings"]}
    clasps = {c["id"]: c for c in level["clasps"]}
    us = []
    for cid in links:
        c = clasps.get(cid)
        if not c:
            continue
        if c["ringId"] == ring_id:
            w = clasp_world(R, c)
            us.append((_unit(R["x"] - w["x"], R["y"] - w["y"]), False))
        elif c.get("touchRingId") == ring_id:
            B = owner_of(level, c["ringId"])       # 所属对象可以是道具（AE 1.0.8 三环结）
            if not B:
                continue
            h = hook_point(B, c)
            us.append((_unit(R["x"] - h["x"], R["y"] - h["y"]), True))
    for st in (us, [u for u in us if u[1]], us[:1]):
        if not st:
            continue
        sx, sy = sum(u[0][0] for u in st), sum(u[0][1] for u in st)
        if math.hypot(sx, sy) > 0.2 * len(st) or len(st) == 1:
            d = _unit(sx, sy)
            if d[0] or d[1]:
                return d, "clasp"
    a = asset(R["asset"])
    if a.get("shape") == "gap":
        g = ((a.get("gapAngle") or 0) + R["rotation"]) * D2R
        return [-math.cos(g), -math.sin(g)], "gap"
    return [0.0, -1.0], "none"


def _hash(s, k):
    M = 0xFFFFFFFF
    h = (2166136261 ^ k) & M
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & M
    h = ((h ^ (h >> 13)) * 1274126177) & M
    return (h % 10007) / 10007.0


def shard_layout(R, n, rev, start_local=None):
    """outro.ts shardGeometry 的角度部分（3D 版用环管弧段切片，不用 2D 遮罩多边形）"""
    a = asset(R["asset"])
    c = a.get("center") or [a.get("width", 352) / 2.0, a.get("height", 352) / 2.0]
    ri = max(0.0, a.get("innerRadius", 126) - 14)
    ro0 = a.get("outerRadius", 176) + 16
    # 1.0.10 钻戒：钻石托伸到外缘以外（reach），遮罩外径放大到盖住钻石托；碎片锚点仍取环带中段
    ro = max(ro0, a.get("reach", ro0) + 6) if a.get("gem") else ro0
    rm = (ri + ro0) / 2.0
    gap = a.get("shape") == "gap"
    gd = (a.get("gapDeg") or 38) if gap else 0
    g = (a.get("gapAngle") or 0) if gap else (start_local or 0)
    lo, hi = g + gd / 2.0, g + 360 - gd / 2.0
    pad = gd / 2.0 - 0.5 if gap else 0
    span = hi - lo
    cuts = [lo + span * k / n + (-pad if k == 0 else pad if k == n else 0) for k in range(n + 1)]
    out = []
    for j in range(n):
        mid = (cuts[j] + cuts[j + 1]) / 2.0
        out.append({"a0": cuts[j], "a1": cuts[j + 1], "mid": mid, "frac": ((n - 1 - j) / (n - 1) if rev else j / (n - 1)) if n > 1 else 0})

    def frac_at(deg):
        x = ((deg - lo) % 360 + 360) % 360
        if x > span:
            x = 0 if x - span > (360 - span) / 2 else span
        f = x / span
        return 1 - f if rev else f
    return {"center": c, "shards": out, "fracAt": frac_at, "ri": ri, "ro": ro, "rm": rm}


def _r4(x):
    return round(x, 4)


def _dedupe(k):
    out = []
    for i, x in enumerate(k):
        if i == 0 or x[0] > k[i - 1][0] + 1e-6:
            out.append([_r4(x[0]), _r4(x[1])])
    return out


def build_outro(level, ring_id, links, ts, P, fps):
    R = next(r for r in level["rings"] if r["id"] == ring_id)
    a = asset(R["asset"])
    fr = 1.0 / (fps or 30)
    s = R["scale"] / 100.0
    d, frm = move_direction(level, ring_id, links)
    dur = max(fr, P["moveSec"])
    O = {"ring": ring_id, "t0": ts, "t1": ts, "dir": d, "dirFrom": frm, "links": links, "clasps": {}}
    if P["moveOut"]:
        O["move"] = {"t0": ts, "t1": ts + dur, "from": [R["x"], R["y"]], "to": [R["x"] + P["moveDist"] * d[0], R["y"] + P["moveDist"] * d[1]]}
        O["t1"] = max(O["t1"], ts + dur)
    fs = ts + max(0, P.get("fadeDelay", 0) or 0)
    fe = fs + max(fr, P.get("fadeSec", P["moveSec"]))

    def fv(t):
        if not P["fade"]:
            return 100.0
        return 100.0 if t <= fs else 0.0 if t >= fe else 100 * (1 - (t - fs) / (fe - fs))
    fade_keys = _dedupe([[ts, 100], [fs, 100], [fe, 0]])
    own = [c for c in level["clasps"] if c["ringId"] == ring_id]
    if P["fade"]:
        O["t1"] = max(O["t1"], fe)
    if not P["shatter"]:
        if P["fade"]:
            O["op"] = fade_keys
            for c in own:
                O["clasps"][c["id"]] = fade_keys
        return O
    n = max(3, min(48, int(round(P.get("shards") or 12))))
    sd = max(fr * 2, P["shatterSec"])
    sweep = sd * .55
    life = sd - sweep
    start_local = None if a.get("shape") == "gap" else math.atan2(-d[1], -d[0]) / D2R - R["rotation"]
    G = shard_layout(R, n, P.get("shatterRev", False), start_local)
    rot = R["rotation"] * D2R

    def to_local(x, y):
        return [(x * math.cos(-rot) - y * math.sin(-rot)) / s, (x * math.sin(-rot) + y * math.cos(-rot)) / s]

    def keys(tb0):
        tb = _r4(tb0)
        te = tb + life

        def own2(t):
            return 100.0 if t <= tb else 0.0 if t >= te else 100 * (1 - (t - tb) / (te - tb))
        v = lambda t: min(fv(t), own2(t))
        bp = sorted(set(_r4(t) for t in [ts, tb, te] + ([fs, fe] if P["fade"] else []) if ts - 1e-9 <= t <= te + 1e-9))
        pts = []
        for i in range(len(bp)):
            pts.append(bp[i])
            if i + 1 < len(bp):
                t0, t1 = bp[i], bp[i + 1]
                d0, d1 = fv(t0) - own2(t0), fv(t1) - own2(t1)
                if d0 * d1 < 0:
                    pts.append(_r4(t0 + (t1 - t0) * d0 / (d0 - d1)))
        k = []
        for t in pts:
            if k and t <= k[-1][0] + 1e-6:
                continue
            val = v(t)
            if len(k) >= 2 and abs(k[-1][1] - val) < 1e-6 and abs(k[-2][1] - val) < 1e-6:
                k[-1] = [t, val]
            else:
                k.append([t, val])
            if val <= 0:
                break
        return _dedupe(k)
    O["hideAt"] = ts
    O["shards"] = []
    for i, q in enumerate(G["shards"]):
        tb = _r4(ts + sweep * q["frac"])
        m = q["mid"] * D2R
        h = _hash(R["id"], 100 + i)
        cx = G["center"][0] + G["rm"] * math.cos(m)
        cy = G["center"][1] + G["rm"] * math.sin(m)
        rad = [math.cos(m) * P["spread"] * (0.7 + h * 0.6) / s, math.sin(m) * P["spread"] * (0.7 + h * 0.6) / s]
        grav = to_local(0, P["spread"] * 1.1)
        O["shards"].append({"i": i, "a0": q["a0"], "a1": q["a1"], "anchor": [round(cx, 2), round(cy, 2)], "drift": [round(rad[0] + grav[0], 2), round(rad[1] + grav[1], 2)],
                            "spin": round((1 if h > .5 else -1) * (25 + h * 60), 1), "tb": tb, "t1": _r4(tb + life), "op": keys(tb)})
    for c in own:
        O["clasps"][c["id"]] = keys(ts + sweep * G["fracAt"](c["angle"]))
    O["t1"] = max(O["t1"], ts + sd)
    return O


def schedule(plan, cti, last_key, fps, P, level):
    """unlock.ts schedule（1.0.14 严格串行）：按移出顺序逐环——这一环的转动（一个接一个）→ 这一环的移出 / 破碎 / 淡出全部完成 → 环间隔 ringGap → 下一环"""
    base = cti if P.get("start", "cti") == "cti" else P["start"]
    t = max(base, last_key + P["gap"]) if last_key > 0 else base
    fr = 1.0 / (fps or 30)
    snap = lambda x: js_round(x / fr) * fr
    t = snap(t)
    keys, moves, outros = [], [], []
    fx = P["moveOut"] or P["fade"] or P["shatter"]
    rg = snap(max(0, P.get("ringGap", DEFAULT_UNLOCK["ringGap"]) if P.get("ringGap") is not None else DEFAULT_UNLOCK["ringGap"]))
    OP = dict(P)
    OP.update(moveSec=snap(max(fr, P["moveSec"])), shatterSec=snap(max(2 * fr, P["shatterSec"])), fadeSec=snap(max(fr, P.get("fadeSec", P["moveSec"]) if P.get("fadeSec") is not None else P["moveSec"])),
              fadeDelay=snap(max(0, P.get("fadeDelay") or 0)))
    outs = plan.get("outs") or [{"ring": plan["target"], "links": [c["id"] for c in level["clasps"] if c["ringId"] == plan["target"] or c.get("touchRingId") == plan["target"]], "after": len(plan["steps"])}]

    def dur_of(s):
        d = s["to"] - s["from"]
        return max(fr, snap(abs(d) / max(1, P["degPerSec"]) if P["mode"] == "speed" else P["secPerStep"]))
    si = 0
    for oi, o in enumerate(outs):
        while si < o["after"]:
            s = plan["steps"][si]
            dur = dur_of(s)
            keys.append({"ring": s["ring"], "t0": t, "t1": t + dur, "v0": s["from"], "v1": s["to"]})
            t = snap(t + dur + P["gap"])
            si += 1
        if not fx:
            if oi < len(outs) - 1:
                t = snap(t + rg)
            continue
        rot = {}
        for s in plan["steps"][:o["after"]]:
            rot[s["ring"]] = s["to"]
        L2 = dict(level)
        L2["rings"] = [dict(r, rotation=r["rotation"] + rot.get(r["id"], 0)) for r in level["rings"]]
        O = build_outro(L2, o["ring"], o["links"], t, OP, fps)
        outros.append(O)
        if O.get("move"):
            mv = dict(O["move"])
            mv["ring"] = O["ring"]
            moves.append(mv)
        t = snap(O["t1"] + rg)
    while si < len(plan["steps"]):
        s = plan["steps"][si]
        dur = dur_of(s)
        keys.append({"ring": s["ring"], "t0": t, "t1": t + dur, "v0": s["from"], "v1": s["to"]})
        t = snap(t + dur + P["gap"])
        si += 1
    end = max([keys[-1]["t1"] if keys else t] + [m["t1"] for m in moves] + [o["t1"] for o in outros])
    start = min(keys[0]["t0"] if keys else math.inf, outros[0]["t0"] if outros else math.inf, t)
    return {"keys": keys, "moves": moves, "outros": outros, "start": start, "end": end}


def bake_timeline(level, P=None, start=0.0):
    """unlock.ts bakeTimeline（1.0.14 烘焙解谜动画）：全部环按 plan_removal 一个一个移出，返回同一份时间轴"""
    Q = dict(DEFAULT_UNLOCK)
    Q.update(P or {})
    Q.update(start=start, deps=True)
    sp = plan_removal(level)
    if not sp["ok"]:
        return {"ok": False, "error": sp.get("error") or "无法一个一个移出", "seq": sp["steps"]}
    steps, outs = [], []
    for st in sp["steps"]:
        steps.extend(st["rots"])
        outs.append({"ring": st["ring"], "links": st["links"], "after": len(steps)})
    plan = {"ok": True, "target": outs[-1]["ring"] if outs else "", "already": not outs, "steps": steps, "deps": [o["ring"] for o in outs[:-1]], "outs": outs, "seq": sp["steps"]}
    fps = level.get("fps") or 30
    S = schedule(plan, start, 0, fps, Q, level)
    out = {"ok": True, "seq": sp["steps"], "plan": plan, "fps": fps, "easeIn": Q["easeIn"], "easeOut": Q["easeOut"]}
    out.update(S)
    return out


def motion_spans(S):
    """unlock.ts motionSpans：每个环的运动区间（检查任何时刻最多一个环在动）"""
    sp = [{"ring": k["ring"], "kind": "rot", "t0": k["t0"], "t1": k["t1"]} for k in S["keys"]] + [{"ring": o["ring"], "kind": "out", "t0": o["t0"], "t1": o["t1"]} for o in S["outros"]]
    return sorted(sp, key=lambda x: x["t0"])


def ease_ae(u, ease_out, ease_in):
    x1, x2 = min(1, ease_out / 100.0), 1 - min(1, ease_in / 100.0)
    if u <= 0:
        return 0.0
    if u >= 1:
        return 1.0
    bx = lambda t: 3 * (1 - t) * (1 - t) * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3
    by = lambda t: 3 * (1 - t) * t * t + t ** 3
    lo, hi = 0.0, 1.0
    for _ in range(40):
        m = (lo + hi) / 2
        if bx(m) < u:
            lo = m
        else:
            hi = m
    return by((lo + hi) / 2)


# ---------------- 关卡校验 / 名称 ----------------
def ring_label(r):
    a = asset(r.get("asset", ""))
    if a.get("gem"):
        return "%s(%s)" % (r.get("name") or r["id"], a.get("label") or "钻戒")
    return "%s(%s%s)" % (r.get("name") or r["id"], COLOR_ZH.get(a.get("color"), ""), SHAPE_ZH.get(a.get("shape"), ""))


def validate_level(L):
    if not isinstance(L, dict):
        raise ValueError("关卡数据不是 JSON 对象")
    if L.get("version") != 1:
        raise ValueError("关卡 version 必须为 1（当前 %r）" % L.get("version"))
    for k in ("width", "height"):
        if not isinstance(L.get(k), (int, float)) or not (16 <= L[k] <= 16384):
            raise ValueError("关卡 %s 不合法" % k)
    if not isinstance(L.get("rings"), list) or not isinstance(L.get("clasps"), list):
        raise ValueError("关卡缺少 rings / clasps 数组")
    if len(L["rings"]) > 500 or len(L["clasps"]) > 2000:
        raise ValueError("环或扣子数量过多")
    ids = set()
    for r in L["rings"]:
        for k in ("x", "y", "scale", "rotation"):
            if not isinstance(r.get(k), (int, float)) or not math.isfinite(r[k]):
                raise ValueError("环 %s 的 %s 不合法" % (r.get("id"), k))
        if not isinstance(r.get("id"), str) or r["id"] in ids:
            raise ValueError("环 id 缺失或重复：%r" % r.get("id"))
        ids.add(r["id"])
    props = L.get("props")
    if props is not None and not isinstance(props, list):
        raise ValueError("props 须为数组")
    for q in props or []:
        a = asset(q.get("asset", "")) if isinstance(q, dict) else {}
        if not isinstance(q, dict) or not isinstance(q.get("id"), str) or a.get("kind") != "prop":
            raise ValueError("未知道具素材: %r" % (q.get("asset") if isinstance(q, dict) else q))
        for k in ("x", "y", "scale", "rotation"):
            if not isinstance(q.get(k), (int, float)) or not math.isfinite(q[k]):
                raise ValueError("道具 %s 位置/缩放/旋转无效" % q["id"])
        if q["id"] in ids:
            raise ValueError("道具 %s 与圆环 id 重复" % q["id"])
    pids = set(q["id"] for q in props or [])
    if len(props or []) > 20:
        raise ValueError("道具数量过多")
    for c in L["clasps"]:
        if c.get("ringId") not in ids and c.get("ringId") not in pids:
            raise ValueError("扣子 %s 附着的圆环 %s 不存在（也不是道具）" % (c.get("id"), c.get("ringId")))
        if c.get("touchRingId") and c["touchRingId"] not in ids:
            raise ValueError("扣子 %s 套住的 %s 不是圆环（道具不能被扣）" % (c.get("id"), c["touchRingId"]))
        for k in ("angle", "radius", "scale"):
            if not isinstance(c.get(k), (int, float)) or not math.isfinite(c[k]):
                raise ValueError("扣子 %s 的 %s 不合法" % (c.get("id"), k))
        if "mat" in c and c["mat"] not in CLASP_MATS:
            raise ValueError("扣子 %s 的材质 mat 无效（只能是 gold / silver）" % c.get("id"))     # level.ts 1.0.15
        c.setdefault("rotation", 0)
    return True
