# -*- coding: utf-8 -*-
"""RingBuilder：解环关卡 JSON → UE 场景（MVP：默认主题 C 环/整环/T 扣 + 俯拍相机灯光地面）。

与 ring_level_builder 的 Blender 端共享 rp_core 解谜内核（同一份 assets_manifest.json）。
单位约定：1 画布像素 = 0.1 cm（UE 单位 cm）；画布 y（向下）→ UE -Y。

用法（编辑器 Python 控制台或 -run=pythonscript）：
    import rb_build
    rb_build.build("/path/to/level.json")      # 建模 + 相机灯光地面
    rb_build.clear()                            # 清理本插件生成的全部 Actor
"""
import json
import math
import os
import sys

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)

import rp_core as C          # noqa: E402  共享解谜内核
import rb_toon as T          # noqa: E402  共享卡通色带内核
import rb_geom as G          # noqa: E402  三环结/钻戒几何内核

PX_CM = 0.1                  # 1 画布像素 = 0.1 cm
GAP_3D_DEG = 80.0
RING_TAG = "RP_"

RING_HEX = {"red": "dc3247", "orange": "ec8a23", "green": "24b24a",
            "blue": "3a6fde", "cyan": "33a9e0",
            "purple": "8c45dc", "silver": "c8ccd2", "ground": "6b7078",
            "gem_silver": "c8bcc0", "gem": "dfe8fb", "knot": "c4b3a2"}
GEM_MAT = {"metal": "gem_silver", "gem": "gem"}
TUBE_DEFAULT = 24.715
MID_RADIUS = 151.06
N_SEG, M_SEG, K_CAP = 64, 16, 5


def _lin(hexstr):
    def f(x):
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.005) ** 2.4
    return tuple(f(int(hexstr[i:i + 2], 16) / 255.0) for i in (0, 2, 4))


def _tube_mesh(radius_cm, tube_cm, gap_deg):
    """截断圆环管 + 半球圆头（append 式）。原点 = 环心平面，缺口朝局部 +Y。
    返回 (verts, tris, normals, uvs)；u = 管径向（内沿 0 → 外沿 1，卡通色带采样）。"""
    if gap_deg > 0:
        a0, arc = 90.0 + gap_deg / 2.0, 360.0 - gap_deg
    else:
        a0, arc = 0.0, 360.0
    verts, tris, normals, uvs = [], [], [], []

    def add(p, nrm, uv):
        verts.append(p)
        normals.append(nrm)
        uvs.append(uv)
        return len(verts) - 1

    rings = []
    for i in range(N_SEG + 1):
        u = math.radians(a0 + arc * i / N_SEG)
        cu, su = math.cos(u), math.sin(u)
        loop = []
        for j in range(M_SEG):
            v = j / M_SEG * 2 * math.pi
            rad = radius_cm + tube_cm * math.cos(v)
            loop.append(add((rad * cu, -rad * su, tube_cm * math.sin(v)),
                            (cu * math.cos(v), -su * math.cos(v), math.sin(v)),
                            T.tube_to_u(math.cos(v))))
        rings.append(loop)
    for i in range(N_SEG):
        a, b = rings[i], rings[i + 1]
        for j in range(M_SEG):
            k1 = (j + 1) % M_SEG
            tris.extend((a[j], b[j], b[k1],
                         a[j], b[k1], a[k1]))
    if gap_deg > 0:
        for u, sign, prev in ((math.radians(a0), -1, rings[0]),
                              (math.radians(a0 + arc), 1, rings[-1])):
            cx, cy = radius_cm * math.cos(u), -radius_cm * math.sin(u)
            rad_d = (math.cos(u), -math.sin(u), 0.0)
            tan_d = (-math.sin(u) * sign, -math.cos(u) * sign, 0.0)
            for step in range(1, K_CAP):
                w = math.pi / 2 * step / K_CAP
                cur = []
                for j in range(M_SEG):
                    v = j / M_SEG * 2 * math.pi
                    d = (rad_d[0] * math.cos(v) * math.cos(w) + tan_d[0] * math.sin(w),
                         rad_d[1] * math.cos(v) * math.cos(w) + tan_d[1] * math.sin(w),
                         math.sin(v) * math.cos(w) + tan_d[2] * math.sin(w))
                    cur.append(add((cx + d[0] * tube_cm,
                                    cy + d[1] * tube_cm,
                                    d[2] * tube_cm), d,
                                   T.tube_to_u(math.cos(v) * math.cos(w))))
                for j in range(M_SEG):
                    k1 = (j + 1) % M_SEG
                    tris.extend((prev[j], cur[j], cur[k1],
                                 prev[j], cur[k1], prev[k1]))
                prev = cur
            pole = add((cx + tan_d[0] * tube_cm, cy + tan_d[1] * tube_cm,
                        tan_d[2] * tube_cm), tan_d, 1.0)
            for j in range(M_SEG):
                k1 = (j + 1) % M_SEG
                tris.extend((prev[j], prev[k1], pole))
    return verts, tris, normals, uvs


def _hoop(r, depth, seg=16):
    """实心短圆柱（轴向 X）：T 扣 MVP 占位体。"""
    verts, tris, normals = [], [], []
    for side, x in ((0, -depth / 2), (1, depth / 2)):
        for j in range(seg):
            a = j / seg * 2 * math.pi
            verts.append((x, r * math.cos(a), r * math.sin(a)))
            normals.append((0.0, math.cos(a), math.sin(a)))
    for j in range(seg):
        k1 = (j + 1) % seg
        tris.extend((j, seg + j, seg + k1, j, seg + k1, k1))
        tris.extend((0, k1, j))
        tris.extend((seg, seg + j, seg + k1))
    return verts, tris, normals


# ---------------------------------------------------------------------------
# 材质（每色一个材质资产：BaseColor 参数 + 卡通自发光 + 粗糙度）
# ---------------------------------------------------------------------------

_MAT_DIR = "/Game/RingBuilder"


def ensure_material(color_key):
    name = "RB_Mat_" + color_key
    path = _MAT_DIR + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    rgb = _lin(RING_HEX.get(color_key, "888888"))
    mat = unreal.MaterialEditingLibrary.create_material(name, _MAT_DIR)
    p = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionVectorParameter)
    p.set_editor_property("parameter_name", "RingColor")
    p.set_editor_property("default_value",
                          unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
    unreal.MaterialEditingLibrary.connect_material_property(
        p, "Output", unreal.MaterialProperty.MP_BASE_COLOR)
    mul = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionMultiply)
    k = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionConstant)
    k.set_editor_property("r", 0.55)
    unreal.MaterialEditingLibrary.connect_material_expressions(
        p, "Output", mul, "A")
    unreal.MaterialEditingLibrary.connect_material_expressions(
        k, "Output", mul, "B")
    unreal.MaterialEditingLibrary.connect_material_property(
        mul, "Output", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    rough = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionConstant)
    rough.set_editor_property("r", 0.35)
    unreal.MaterialEditingLibrary.connect_material_property(
        rough, "Output", unreal.MaterialProperty.MP_ROUGHNESS)
    unreal.EditorAssetLibrary.save_asset(mat.get_path_name())
    return mat


def ensure_toon_material(color_key):
    """卡通色带材质（环用）：256×1 sRGB 渐变纹理 + UV.u 径向采样。
    BaseColor = 色带×0.45，Emissive = 色带×0.55（俯拍观感对齐 Blender 端）。"""
    name = "RB_Toon_" + color_key
    path = _MAT_DIR + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    hexc = RING_HEX.get(color_key, "888888")
    png = os.path.join(HERE, "_ramp_%s.png" % color_key)
    if not os.path.exists(png):
        raise RuntimeError("色带纹理缺失: %s（仓库预生成文件，勿删除）" % png)
    task = unreal.AssetImportTask()
    task.filename = png
    task.destination_path = _MAT_DIR
    task.destination_name = "RB_Ramp_" + color_key
    task.automated = True
    task.replace_existing = True
    task.save = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    tex = unreal.EditorAssetLibrary.load_asset(_MAT_DIR + "/RB_Ramp_"
                                               + color_key)
    try:
        tex.set_editor_property("srgb", True)
    except Exception:
        pass
    mat = unreal.MaterialEditingLibrary.create_material(name, _MAT_DIR)
    tc = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionTextureCoordinate)
    sample = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionTextureSample)
    sample.set_editor_property("texture", tex)
    unreal.MaterialEditingLibrary.connect_material_expressions(
        tc, "Output", sample, "UVs")
    dim = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionConstant)
    dim.set_editor_property("r", T.TOON_DIFFUSE)
    dim_mul = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionMultiply)
    unreal.MaterialEditingLibrary.connect_material_expressions(
        sample, "RGB", dim_mul, "A")
    unreal.MaterialEditingLibrary.connect_material_expressions(
        dim, "Output", dim_mul, "B")
    unreal.MaterialEditingLibrary.connect_material_property(
        dim_mul, "Output", unreal.MaterialProperty.MP_BASE_COLOR)
    em = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionConstant)
    em.set_editor_property("r", T.TOON_EMISSION)
    em_mul = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionMultiply)
    unreal.MaterialEditingLibrary.connect_material_expressions(
        sample, "RGB", em_mul, "A")
    unreal.MaterialEditingLibrary.connect_material_expressions(
        em, "Output", em_mul, "B")
    unreal.MaterialEditingLibrary.connect_material_property(
        em_mul, "Output", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    rough = unreal.MaterialEditingLibrary.create_material_expression(
        mat, unreal.MaterialExpressionConstant)
    rough.set_editor_property("r", 0.35)
    unreal.MaterialEditingLibrary.connect_material_property(
        rough, "Output", unreal.MaterialProperty.MP_ROUGHNESS)
    unreal.EditorAssetLibrary.save_asset(mat.get_path_name())
    return mat


# ---------------------------------------------------------------------------
# Actor 装配（ProceduralMeshComponent + EmptyActor）
# ---------------------------------------------------------------------------


def _spawn_pmc(label, verts, tris, normals, mat,
               loc_xy, yaw_deg=0.0, scale=1.0, attach_to=None, uvs=None):
    x, y = loc_xy
    pos = unreal.Vector(x * PX_CM, -y * PX_CM, 0.0)
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.EmptyActor, pos)
    if actor is None:
        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.Actor, pos)
    pmc = unreal.ProceduralMeshComponent(unreal.Name(label), actor)
    actor.set_actor_root_component(pmc)
    actor.add_instance_component(pmc)
    pmc.register_component()
    uv0 = ([unreal.Vector2D(u, 0.0) for u in uvs] if uvs
           else [unreal.Vector2D(0.0, 0.0)] * len(verts))
    tang = [unreal.ProcMeshTangent(n[0], n[1], n[2], False) for n in normals]
    pmc.create_mesh_section(0,
                            [unreal.Vector(*p) for p in verts],
                            list(tris),
                            [unreal.Vector(*n) for n in normals],
                            uv0, tang, [], [], [], [])
    pmc.set_material(0, mat)
    actor.set_actor_rotation(unreal.Rotator(0.0, -yaw_deg, 0.0), False, False)
    actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
    actor.set_actor_label(label)
    if attach_to is not None:
        actor.attach_to_actor(attach_to, unreal.Name(""),
                              unreal.AttachmentRule.KEEP_WORLD,
                              unreal.AttachmentRule.KEEP_WORLD,
                              unreal.AttachmentRule.KEEP_WORLD)
    return actor


def _spawn_multi_pmc(label, sections, loc_xy, yaw_deg=0.0, scale=1.0):
    """多 section Actor（钻戒 metal/gem 双材质、三环结单材质）。"""
    x, y = loc_xy
    pos = unreal.Vector(x * PX_CM, -y * PX_CM, 0.0)
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.EmptyActor, pos)
    if actor is None:
        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
            unreal.Actor, pos)
    pmc = unreal.ProceduralMeshComponent(unreal.Name(label), actor)
    actor.set_actor_root_component(pmc)
    actor.add_instance_component(pmc)
    pmc.register_component()
    for i, (verts, tris, normals, uvs, kind) in enumerate(sections):
        uv0 = ([unreal.Vector2D(u, 0.0) for u in uvs] if uvs
               else [unreal.Vector2D(0.0, 0.0)] * len(verts))
        tang = [unreal.ProcMeshTangent(n[0], n[1], n[2], False)
                for n in normals]
        pmc.create_mesh_section(i,
                                [unreal.Vector(*p) for p in verts],
                                list(tris),
                                [unreal.Vector(*n) for n in normals],
                                uv0, tang, [], [], [], [])
        pmc.set_material(i, ensure_material(GEM_MAT.get(kind, kind)))
    actor.set_actor_rotation(unreal.Rotator(0.0, -yaw_deg, 0.0), False, False)
    actor.set_actor_scale3d(unreal.Vector(scale, scale, scale))
    actor.set_actor_label(label)
    return actor


def _find_by_label(label):
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if actor.get_actor_label() == label:
            return actor
    return None


def _spawn_stage(w, h):
    """地面 + 主光 + 天光 + 俯拍正交相机。"""
    verts = [(-w * PX_CM * 1.6, h * PX_CM * 1.6, 0),
             (w * PX_CM * 1.6, h * PX_CM * 1.6, 0),
             (w * PX_CM * 1.6, -h * PX_CM * 1.6, 0),
             (-w * PX_CM * 1.6, -h * PX_CM * 1.6, 0)]
    tris = [0, 1, 2, 0, 2, 3]
    normals = [(0, 0, 1)] * 4
    _spawn_pmc("RP_Ground", verts, tris, normals,
               ensure_material("ground"), (0, 0))
    sun = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.DirectionalLight, unreal.Vector(0, 0, 400))
    sun.set_actor_rotation(unreal.Rotator(-55.0, 30.0, 0.0), False, False)
    lc = sun.get_component_by_class(unreal.DirectionalLightComponent)
    lc.set_editor_property("intensity", 4.0)
    sun.set_actor_label("RP_Sun")
    sky = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.SkyLight, unreal.Vector(0, 0, 500))
    sky.set_actor_label("RP_Sky")
    cam = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CameraActor, unreal.Vector(0, 0, 600))
    cc = cam.get_component_by_class(unreal.CameraComponent)
    cc.set_editor_property("projection_mode",
                           unreal.CameraProjectionMode.ORTHOGRAPHIC)
    cc.set_editor_property("ortho_width", max(w, h) * PX_CM * 1.1)
    cam.set_actor_rotation(unreal.Rotator(-90.0, 0.0, 0.0), False, False)
    cam.set_actor_label("RP_TopCamera")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def clear():
    n = 0
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if actor.get_actor_label().startswith(RING_TAG):
            unreal.EditorLevelLibrary.destroy_actor(actor)
            n += 1
    return n


def build(json_path):
    """关卡 JSON → 场景。返回统计 dict。"""
    with open(json_path, "r", encoding="utf-8") as f:
        L = json.load(f)
    C.validate_level(L)
    cleared = clear()
    w, h = L["width"], L["height"]
    _spawn_stage(w, h)
    rings = {r["id"]: r for r in L["rings"]}
    ring_actors = {}
    tube_px = TUBE_DEFAULT * PX_CM
    for r in sorted(L["rings"], key=lambda q: q.get("z", 0)):
        a = C.asset(r["asset"])
        if a.get("gem"):
            # 钻戒：环带+钻石+六爪双材质（rb_geom 内核顶点表）
            actor = _spawn_multi_pmc(
                "RP_Ring_" + r["id"], G.gem_sections(a.get("gemAngle", -90.0)),
                (r["x"], r["y"]), yaw_deg=r["rotation"],
                scale=r["scale"] / 100.0)
            ring_actors[r["id"]] = actor
            continue
        gap = GAP_3D_DEG if a.get("shape") == "gap" else 0.0
        verts, tris, normals, uvs = _tube_mesh(MID_RADIUS * PX_CM, tube_px,
                                               gap)
        mat = ensure_toon_material(a.get("color", "blue"))
        actor = _spawn_pmc("RP_Ring_" + r["id"], verts, tris, normals, mat,
                           (r["x"], r["y"]), yaw_deg=r["rotation"],
                           scale=r["scale"] / 100.0, uvs=uvs)
        ring_actors[r["id"]] = actor
    # 三环结等静态道具（不可解，扣子可挂）
    for q in sorted(L.get("props") or [], key=lambda q: q.get("z", 0)):
        pa = C.asset(q["asset"])
        if pa.get("kind") != "prop":
            continue
        _spawn_multi_pmc("RP_Prop_" + q["id"], G.knot_sections(),
                         (q["x"], q["y"]), yaw_deg=q.get("rotation", 0),
                         scale=q["scale"] / 100.0)
    clasp_n = 0
    for c in L["clasps"]:
        A = rings.get(c["ringId"])
        if A is None:
            continue
        hook = C.hook_point(A, c)
        w_ = C.clasp_world(A, c)
        cs = c["scale"] / 100.0
        verts, tris, normals = _hoop(tube_px * 1.24 * cs, tube_px * 1.9 * cs)
        mat = ensure_material("silver")
        _spawn_pmc("RP_Clasp_" + c["id"], verts, tris, normals, mat,
                   (hook["x"], hook["y"]), yaw_deg=w_["rotation"],
                   scale=1.0, attach_to=ring_actors.get(c["ringId"]))
        clasp_n += 1
    return {"ok": True, "rings": len(ring_actors), "clasps": clasp_n,
            "cleared": cleared,
            "theme": C.SKIN_ZH.get((L.get("skin") or "default"), "default")}
