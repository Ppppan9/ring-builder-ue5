# -*- coding: utf-8 -*-
"""RingBuilder 共享内核 III：三环结 / 钻戒几何（逐行移植自 ring_level_builder rp_scene.py，
公式/常量与 Blender 端一致；输出顶点表（cm），供 UE5 / C4D 端直接塞进网格。

三环结 = 傅里叶闭合曲线中心线 + 圆管扫掠（平行移动标架，闭合扭转均匀分摊）。
钻戒   = 整环环带（普通管）+ 简化明亮式圆钻（刻面，flat）+ 六爪镶（贝塞尔中心线扫掠）。
sections 返回格式：[(verts, tris, normals, uvs|None, mat_kind)]，mat_kind ∈ {"metal", "gem"}。
"""
import math

try:
    from mathutils import Vector   # Blender 端真向量（本轮三环结/钻戒逻辑全平台统一）
except ImportError:
    Vector = None                  # UE/C4D 端由 _vec_compat 提供极简向量

PX_CM = 0.1

# ---------------- 三环结（rp_scene KNOT_* 原值） ----------------
KNOT_FIT = {"ax": [2.05579, -1.29824, 1.65069, -6.91506, -1.67315, -0.28795, -0.47453, -1.54293],
            "bx": [-91.8402, 196.81033, -2.47194, 0.81839, 2.36229, 1.19918, -0.0015, -0.64581],
            "ay": [-89.50099, -195.0188, 1.71774, -0.78593, -3.83906, -1.08193, -0.30839, 1.32533],
            "by": [8.35608, -6.34752, -0.64721, -5.53289, -2.53605, -0.08425, -0.93972, -2.03957]}
KNOT_Z = {"c0": 142.36791,
          "cos": [3.70288, -0.71846, 0.78286, -2.24943, 4.39492, 1.44768, -0.01919, -1.08328, 0.8575],
          "sin": [-2.43007, 1.40571, -77.67693, -1.85186, 0.15634, 10.17889, -1.43905, 0.39764, -0.81801]}
KNOT_RT = 61.5                 # 管半径（素材像素）
KNOT_N, KNOT_M = 420, 24       # 采样密度（略低于 Blender 端 960×48）

# ---------------- 钻戒（rp_scene GEM/PRONG 原值） ----------------
GEM = {"Rg": 66.0, "y_girdle": 255.0, "girdle_h": 2.0, "y_table": 289.0,
       "table_r": 0.56, "y_bezel": 271.0, "bezel_r": 0.80, "y_pav": 222.0,
       "pav_r": 0.45, "y_culet": 190.0, "z_axis": 40.0, "z_scale": 0.58, "n": 16}
PHI_MID, PHI_LOW = 80, 120
PRONG = {"phis": (30, PHI_MID, PHI_LOW, 360 - PHI_LOW, 360 - PHI_MID, 330),
         "base": {30: (16.0, 7.0), PHI_MID: (62.0, 0.0), PHI_LOW: (40.0, -7.0)},
         "g_off": 14.0, "tip_off": 15.0, "tip_y": 282.0,
         "r_base": 11.0, "r_mid": 9.0, "r_tip": 7.0}
MID_RADIUS, TUBE_PX = 151.06, 24.715


def _vec_compat():
    """无 mathutils 环境（UE/C4D）时退化为极简向量类。"""
    global Vector
    if Vector is not None:
        return True

    class _V:
        def __init__(self, t):
            self.x, self.y, self.z = t[0], t[1], t[2]

        def __sub__(self, o):
            return _V((self.x - o.x, self.y - o.y, self.z - o.z))

        def __add__(self, o):
            return _V((self.x + o.x, self.y + o.y, self.z + o.z))

        def __mul__(self, k):
            return _V((self.x * k, self.y * k, self.z * k))

        def __rmul__(self, k):
            return self.__mul__(k)

        def length(self):
            return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

        def normalized(self):
            L = max(1e-12, self.length())
            return _V((self.x / L, self.y / L, self.z / L))

        def cross(self, o):
            return _V((self.y * o.z - self.z * o.y,
                       self.z * o.x - self.x * o.z,
                       self.x * o.y - self.y * o.x))

        def dot(self, o):
            return self.x * o.x + self.y * o.y + self.z * o.z

        def copy(self):
            return _V((self.x, self.y, self.z))

        def lerp(self, o, f):
            return _V((self.x + (o.x - self.x) * f,
                       self.y + (o.y - self.y) * f,
                       self.z + (o.z - self.z) * f))

    Vector = _V
    return False


def _knot_xyz(t):
    """三环结中心线（素材像素，Blender 局部：x 右、y 已翻转、z 上）。"""
    F, Z = KNOT_FIT, KNOT_Z
    x = y = 0.0
    for k in range(1, len(F["ax"]) + 1):
        c, s = math.cos(k * t), math.sin(k * t)
        x += F["ax"][k - 1] * c + F["bx"][k - 1] * s
        y += F["ay"][k - 1] * c + F["by"][k - 1] * s
    z = Z["c0"]
    for k in range(1, len(Z["cos"]) + 1):
        z += Z["cos"][k - 1] * math.cos(k * t) + Z["sin"][k - 1] * math.sin(k * t)
    return Vector((x, -y, z))


def knot_centerline(n=KNOT_N):
    """弧长×(1+曲率·管半径) 加权等分采样（弯得紧处段更密）。"""
    _vec_compat()
    M = 8 * n
    P = [_knot_xyz(2 * math.pi * i / M) for i in range(M)]
    L = [0.0]
    for i in range(M):
        a, b, c = P[i - 1], P[i], P[(i + 1) % M]
        d1 = (c - a) * 0.5
        d2 = c - b * 2 + a
        k = d1.cross(d2).length() / max(d1.length() ** 3, 1e-12)
        L.append(L[-1] + (P[(i + 1) % M] - P[i]).length() * (1.0 + k * KNOT_RT))
    tot = L[-1]
    out, j = [], 0
    for i in range(n):
        s = tot * i / n
        while L[j + 1] < s and j + 2 < len(L):
            j += 1
        f = (s - L[j]) / max(L[j + 1] - L[j], 1e-12)
        out.append(P[j].lerp(P[(j + 1) % M], f))
    return out


def _rot_about(v, axis, ang):
    """Rodrigues 旋转（绕单位轴 axis 转 ang），替代 mathutils.rotation_difference。"""
    c, s = math.cos(ang), math.sin(ang)
    return v * c + axis.cross(v) * s + axis * (axis.dot(v)) * (1 - c)


def knot_sections():
    """三环结：中心线扫掠圆管（平行移动标架 + 闭合扭转均匀分摊）。
    返回 [(verts_cm, tris, normals, None, "metal")]。原点 = 瓣尖外接圆圆心正下方地面。"""
    _vec_compat()
    P = knot_centerline(KNOT_N)
    n = len(P)
    T = [(P[(i + 1) % n] - P[i - 1]).normalized() for i in range(n)]
    N0 = T[0].cross(Vector((0.0, 0.0, 1.0)))
    if N0.length() < 1e-6:
        N0 = T[0].cross(Vector((1.0, 0.0, 0.0)))
    N0 = N0.normalized()
    Ns = [N0]
    for i in range(1, n + 1):
        q = _rot_about(Ns[-1], T[i - 1],
                       math.acos(max(-1.0, min(1.0, T[i - 1].dot(T[i % n])))))
        Ns.append(q.normalized())
    # 闭合扭转误差绕 T0 均匀分摊
    nn = Ns[n] - T[0] * Ns[n].dot(T[0])
    nn = nn.normalized()
    ang = math.atan2(T[0].dot(Ns[0].cross(nn)), Ns[0].dot(nn))
    rt = KNOT_RT * PX_CM
    verts, normals, tris = [], [], []

    def add(p, nrm):
        verts.append((p.x * PX_CM, p.y * PX_CM, p.z * PX_CM))
        normals.append((nrm.x, nrm.y, nrm.z))
        return len(verts) - 1

    rings = []
    for i in range(n):
        t = T[i]
        nv = _rot_about(Ns[i], t, -ang * i / n)
        nv = nv - t * nv.dot(t)
        nv = nv.normalized()
        bv = t.cross(nv)
        loop = []
        for j in range(KNOT_M):
            v = 2 * math.pi * j / KNOT_M
            loop.append(add(P[i] + (nv * math.cos(v) + bv * math.sin(v)) * rt,
                            nv * math.cos(v) + bv * math.sin(v)))
        rings.append(loop)
    for i in range(n):
        a, b = rings[i], rings[(i + 1) % n]
        for j in range(KNOT_M):
            k1 = (j + 1) % KNOT_M
            tris.extend((a[j], a[k1], b[k1], a[j], b[k1], b[j]))
    return [(verts, tris, normals, None, "metal")]


# ---------------- 钻戒 ----------------


def _gem_frame(gem_angle):
    th = math.radians(-gem_angle)
    ax = Vector((math.cos(th), math.sin(th), 0.0))
    sx = Vector((math.sin(th), -math.cos(th), 0.0))
    return ax, sx


def _gem_tri_verts(gem_angle):
    """简化明亮式圆钻（照 rp_scene.gem_vertices）：返回 (vs_px, fs) 三角索引表。"""
    G = GEM
    ax, sx = _gem_frame(gem_angle)
    up = Vector((0.0, 0.0, 1.0))
    zc = G["z_axis"]
    Rg, n = G["Rg"], G["n"]

    def P(y, r, ang):
        return (ax * y + (sx * math.cos(ang) + up * (math.sin(ang) * G["z_scale"])) * r
                + up * zc)

    vs, fs = [], []

    def ring(y, r, k, off=0.0):
        i0 = len(vs)
        for i in range(k):
            vs.append(P(y, r, 2 * math.pi * (i + off) / k))
        return list(range(i0, i0 + k))

    table = ring(G["y_table"], Rg * G["table_r"], 8, 0.5)
    bezel = ring(G["y_bezel"], Rg * G["bezel_r"], 8, 0.0)
    g_top = ring(G["y_girdle"] + G["girdle_h"] / 2, Rg, n)
    g_bot = ring(G["y_girdle"] - G["girdle_h"] / 2, Rg, n)
    pav = ring(G["y_pav"], Rg * G["pav_r"], 8, 0.0)
    vs.append(P(G["y_culet"], 0.0, 0.0))
    culet = len(vs) - 1
    fs.append(list(reversed(table)))
    for i in range(8):
        j = (i + 1) % 8
        fs.append([table[i], table[j], bezel[j]])
        fs.append([bezel[i], table[i], bezel[j]][::-1])
        fs.append([bezel[j], g_top[2 * j], g_top[2 * i + 1]])
        fs.append([bezel[i], g_top[2 * i + 1], g_top[2 * i]])
        fs.append([bezel[i], bezel[j], g_top[2 * i + 1]])
    for i in range(n):
        j = (i + 1) % n
        fs.append([g_top[i], g_top[j], g_bot[j], g_bot[i]])
    for i in range(8):
        j = (i + 1) % 8
        fs.append([g_bot[2 * i], g_bot[2 * i + 1], pav[i]])
        fs.append([g_bot[2 * i + 1], g_bot[(2 * j) % n], pav[j]])
        fs.append([g_bot[2 * i + 1], pav[j], pav[i]])
        fs.append([pav[i], pav[j], culet])
    return vs, fs


def _prong_paths(gem_angle, tube_px):
    """六爪中心线（素材像素）：管内起点 → 亭部外侧 → 腰外 → 扣冠部。返回 [(点列, 半径列)]。"""
    G, Pg = GEM, PRONG
    ax, sx = _gem_frame(gem_angle)
    up = Vector((0.0, 0.0, 1.0))
    out = []
    for phi in Pg["phis"]:
        ph = math.radians(phi)
        side = sx * math.sin(ph) + up * math.cos(ph)
        bx, bdz = Pg["base"][phi if phi <= 180 else 360 - phi]
        bx = math.copysign(bx, math.sin(ph))
        B = ax * math.sqrt(MID_RADIUS ** 2 - bx * bx) + sx * bx \
            + up * (tube_px + bdz)

        def on_gem(y, r, off):
            kz = G["z_scale"]
            e = sx * (r * math.sin(ph)) + up * (r * kz * math.cos(ph))
            nv = sx * (math.sin(ph) / r) + up * (math.cos(ph) / (r * kz))
            return ax * y + e + nv.normalized() * off + up * G["z_axis"]

        Gp = on_gem(G["y_girdle"], G["Rg"], Pg["g_off"])
        rt = G["Rg"] * (G["table_r"]
                        + (G["bezel_r"] - G["table_r"])
                        * (G["y_table"] - Pg["tip_y"])
                        / (G["y_table"] - G["y_bezel"]))
        Tp = on_gem(Pg["tip_y"], rt, Pg["tip_off"])
        c1 = B + ax * 40.0 + Vector((side.x, side.y, max(side.z, 0.0))) * 16.0
        c2 = Gp - ax * 30.0
        pts, rad = [], []
        N1, N2 = 26, 10

        def bez(p0, p1, p2, p3, t):
            u = 1 - t
            return p0 * u ** 3 + p1 * 3 * u * u * t + p2 * 3 * u * t * t + p3 * t ** 3

        for i in range(N1 + 1):
            t = i / N1
            pts.append(bez(B, c1, c2, Gp, t))
            rad.append(Pg["r_base"] + (Pg["r_mid"] - Pg["r_base"]) * t)
        cq = Gp + ax * 14.0 + side * 3.0
        for i in range(1, N2 + 1):
            t = i / N2
            pts.append(Gp * (1 - t) ** 2 + cq * 2 * (1 - t) * t + Tp * t * t)
            rad.append(Pg["r_mid"] + (Pg["r_tip"] - Pg["r_mid"]) * t)
        out.append((pts, rad))
    return out


def _sweep_sect(pts_px, rad_px, segs=16):
    """圆截面扫掠（平行移动标架；起点平封扇形、终点半球圆头）。返回 (verts, tris, normals)。"""
    _vec_compat()
    pts = [p * PX_CM for p in pts_px]
    rad = [r * PX_CM for r in rad_px]
    tans = []
    for i in range(len(pts)):
        a, b = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
        tans.append((b - a).normalized())
    nrm = tans[0].cross(Vector((0.0, 0.0, 1.0)))
    if nrm.length() < 1e-6:
        nrm = tans[0].cross(Vector((1.0, 0.0, 0.0)))
    nrm = nrm.normalized()
    verts, normals, tris = [], [], []

    def add(p, nv):
        verts.append((p.x, p.y, p.z))
        normals.append((nv.x, nv.y, nv.z))
        return len(verts) - 1

    loops = []
    for i, p in enumerate(pts):
        if i:
            q = _rot_about(nrm, tans[i - 1],
                           math.acos(max(-1.0, min(1.0, tans[i - 1].dot(tans[i])))))
            nrm = q.normalized()
        bnv = tans[i].cross(nrm).normalized()
        lp = []
        for j in range(segs):
            v = 2 * math.pi * j / segs
            lp.append(add(p + (nrm * math.cos(v) + bnv * math.sin(v)) * rad[i],
                          nrm * math.cos(v) + bnv * math.sin(v)))
        loops.append((lp, nrm.copy(), bnv.copy()))
    for i in range(len(loops) - 1):
        A, B = loops[i][0], loops[i + 1][0]
        for j in range(segs):
            k1 = (j + 1) % segs
            tris.extend((A[j], A[k1], B[k1], A[j], B[k1], B[j]))
    base = loops[0][0]
    for j in range(1, segs - 1):          # 起点平封（扇形，法线朝 -tans[0]）
        tris.extend((base[0], base[j + 1], base[j]))
    lp, n0, b0 = loops[-1]
    t = tans[-1]
    c = pts[-1]
    r = rad[-1]
    prev = lp
    K = 5
    for kk in range(1, K):
        w = math.pi / 2 * kk / K
        cur = []
        for j in range(segs):
            v = 2 * math.pi * j / segs
            d = (n0 * math.cos(v) + b0 * math.sin(v)) * math.cos(w) \
                + t * math.sin(w)
            cur.append(add(c + d * r, d))
        for j in range(segs):
            k1 = (j + 1) % segs
            tris.extend((prev[j], prev[k1], cur[k1], prev[j], cur[k1], cur[j]))
        prev = cur
    pole = add(c + t * r, t)
    for j in range(segs):
        k1 = (j + 1) % segs
        tris.extend((prev[j], prev[k1], pole))
    return verts, tris, normals


def _band_sect():
    """钻戒环带 = 整环管（plain，无色带 → uvs None）。"""
    verts, tris, normals = [], [], []
    R, tube = MID_RADIUS * PX_CM, TUBE_PX * PX_CM
    n, m = 64, 16
    rings = []
    for i in range(n + 1):
        u = math.radians(i / n * 360.0)
        cu, su = math.cos(u), math.sin(u)
        loop = []
        for j in range(m):
            v = j / m * 2 * math.pi
            rad = R + tube * math.cos(v)
            loop.append((rad * cu, -rad * su, tube * math.sin(v),
                         cu * math.cos(v), -su * math.cos(v), math.sin(v)))
        rings.append(loop)
    for p in rings:
        for x in p:
            verts.append(x[:3])
            normals.append(x[3:])
    for i in range(n):
        a, b = rings[i], rings[i + 1]
        for j in range(m):
            k1 = (j + 1) % m
            tris.extend((i * m + j, (i + 1) * m + j, (i + 1) * m + k1,
                         i * m + j, (i + 1) * m + k1, i * m + k1))
    return verts, tris, normals


def gem_sections(gem_angle=-90.0):
    """钻戒（局部坐标，原点 = 环心正下方地面）。返回 sections：
    [(verts, tris, normals, uvs, mat_kind)]，环带+六爪 = "metal"（粉银），
    钻石 = "gem"（flat 刻面，浅蓝白）。"""
    _vec_compat()
    sections = []
    sections.append((*_band_sect(), None, "metal"))
    # 钻石：flat 展开（每面独立顶点 + 面法线；三角/四边形皆支持）
    vs, fs = _gem_tri_verts(gem_angle)
    verts, normals, tris = [], [], []

    def _flat_face(idxs):
        idx = []
        for vi in idxs:
            p = vs[vi]
            verts.append((p.x * PX_CM, p.y * PX_CM, p.z * PX_CM))
            idx.append(len(verts) - 1)
        e1 = tuple(verts[idx[1]][k] - verts[idx[0]][k] for k in range(3))
        e2 = tuple(verts[idx[2]][k] - verts[idx[0]][k] for k in range(3))
        nvec = (e1[1] * e2[2] - e1[2] * e2[1],
                e1[2] * e2[0] - e1[0] * e2[2],
                e1[0] * e2[1] - e1[1] * e2[0])
        L = max(1e-12, math.sqrt(sum(v * v for v in nvec)))
        nv = tuple(v / L for v in nvec)
        for _k in idx:                       # 法线数必须与顶点数等长
            normals.append(nv)
        tris.extend((idx[0], idx[1], idx[2]))
        for k in range(2, len(idxs) - 1):    # n≥3 通用 fan 三角化（复用顶点）
            tris.extend((idx[0], idx[k], idx[k + 1]))

    for f in fs:
        _flat_face(f)
    sections.append((verts, tris, normals, None, "gem"))
    # 六爪：粉银平滑扫掠
    for pts, rad in _prong_paths(gem_angle, TUBE_PX):
        v2, t2, n2 = _sweep_sect(pts, rad)
        sections.append((v2, t2, n2, None, "metal"))
    return sections


def knot_scale_clamp(scale=1.0):
    return max(0.01, scale / 100.0)


def shard_mesh(radius_cm, tube_cm, a_from, a_to, m=14):
    """破碎碎片：环管弧段（平端面，无圆头）。
    a_from/a_to = 环局部素材角（度，含方向 a_to > a_from）。返回 (verts, tris, normals)。"""
    _vec_compat()
    a0, arc = a_from, a_to - a_from
    n = max(3, int(round(abs(arc) / 6.0)))
    verts, normals, tris = [], [], []

    def add(p, nrm):
        verts.append(p)
        normals.append(nrm)
        return len(verts) - 1

    rings = []
    for i in range(n + 1):
        u = math.radians(a0 + arc * i / n)
        cu, su = math.cos(u), math.sin(u)
        loop = []
        for j in range(m):
            v = j / m * 2 * math.pi
            rad = radius_cm + tube_cm * math.cos(v)
            loop.append(add((rad * cu, -rad * su, tube_cm * math.sin(v)),
                            (cu * math.cos(v), -su * math.cos(v), math.sin(v))))
        rings.append(loop)
    for i in range(n):
        a, b = rings[i], rings[i + 1]
        for j in range(m):
            k1 = (j + 1) % m
            tris.extend((a[j], b[j], b[k1], a[j], b[k1], a[k1]))
    for loop, sign in ((rings[0], -1), (rings[-1], 1)):   # 平端面 fan
        tang = (math.sin(math.radians(a0)) * -sign,
                math.cos(math.radians(a0)) * -sign * 0.0, 0.0)
        u_mid = math.radians(a0 + (arc * (0 if sign < 0 else 1)))
        tn = (-math.sin(u_mid) * sign, math.cos(u_mid) * sign, 0.0)
        for j in range(1, m - 1):
            tris.extend((loop[0], loop[j + 1], loop[j])
                        if sign < 0 else (loop[0], loop[j], loop[j + 1]))
        for j in range(m):
            pass
        del tang
    return verts, tris, normals
