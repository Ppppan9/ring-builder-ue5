# -*- coding: utf-8 -*-
"""RingBuilder：沙粒破碎 → Level Sequence 关键帧（同步 Blender 0.3.15）。

与 Blender 端沙粒模式同一节奏：起始帧整环缩没（扣件 attach 随环消失），
原环切出的实体弧段沿 C 口依次脱落、绕 Z 翻滚滑出（俯拍平面），
随后在弧段自身网格表面分批生成哑光细沙 Actor，减速滑停。
UE 俯拍版以平面滑动替代立式下落；细沙走关键帧（非物理模拟）。

用法：
    import rb_sand
    rb_sand.sand("/path/to/level.json")          # 建模（若未建）+ 沙粒破碎动画
    rb_sand.sand(path, ring_id="r1", start_sec=2.0, sections=8, reverse=True)
"""
import json
import math
import os
import sys

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.append(HERE)

import rp_core as C          # noqa: E402
import rb_build as B         # noqa: E402
import rb_geom as G          # noqa: E402
import rb_unlock as U        # noqa: E402  复用 Sequencer 绑定助手


def _yaw_world(local_xy, yaw_deg):
    """环局部平面方向 → 世界平面方向（UE yaw = -rot0）。"""
    f = math.radians(-yaw_deg)
    dx, dy = local_xy
    return (dx * math.cos(f) - dy * math.sin(f),
            dx * math.sin(f) + dy * math.cos(f))


def _spin_keys(wx, wy, x0, y0, detach, end, fps, v_plane, spin_rate):
    """实体弧段的逐帧位置/自转关键帧（秒 → 帧，绝对世界坐标 cm）。
    首帧 = detach，末帧 = end（精确收尾，不重复）。"""
    out = []
    last = int(round(end * fps))
    f = max(1, int(round(detach * fps)))
    while f < last:
        t = f / fps - detach
        out.append((f, (x0 + wx * v_plane * t, y0 + wy * v_plane * t),
                    spin_rate * t))
        f += 1
    t = end - detach
    out.append((last, (x0 + wx * v_plane * t, y0 + wy * v_plane * t),
                spin_rate * t))
    return out


def sand(json_path, seq_name="RB_Sand", ring_id=None, start_sec=0.0,
         sections=12, grains=240, spread=1.0, reverse=False, sweep_sec=0.6):
    """沙粒破碎动画。ring_id=None 时全部环同时破碎；reverse=True 从另一端开始。
    sections=1 即整体脱落。返回 {"ok", "frames", "sections", "grains", "seq"}。"""
    with open(json_path, "r", encoding="utf-8") as f:
        L = json.load(f)
    C.validate_level(L)
    fps = int(L.get("fps") or 30)
    rings_actors = U._find_rings()
    if not rings_actors:
        B.build(json_path)
        rings_actors = U._find_rings()
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        label = actor.get_actor_label()
        if label.startswith(("RP_Sand_", "RP_Grain_")):
            unreal.EditorLevelLibrary.destroy_actor(actor)
    base = {r["id"]: r for r in L["rings"]}
    targets = [ring_id] if ring_id else sorted(base)
    missing = [k for k in targets if k not in rings_actors or k not in base]
    if missing:
        raise RuntimeError("场景里找不到环：%s" % ", ".join(missing))
    sections = max(1, min(G.SAND_SECTIONS_MAX, sections))
    end_frame = int(round((start_sec + sweep_sec + G.SAND_FALL_SEC
                           + G.SAND_CRUMBLE_SEC + G.SAND_STOP_SEC + 0.2) * fps))
    seq = U._new_sequence(seq_name, fps, end_frame)
    n_sections = n_grains = 0
    for rid in targets:
        actor = rings_actors[rid]
        r = base[rid]
        s = r["scale"] / 100.0
        color = C.asset(r["asset"]).get("color", "blue")
        mat = B.ensure_toon_material(color)
        bind, section = U._bind_transform(seq, actor)
        loc0 = U._canvas_to_cm((r["x"], r["y"]))
        f_start = max(1, int(round(start_sec * fps)))
        U._key_transform(section, f_start, loc0, r["rotation"], s)
        U._key_transform(section, f_start + 1, loc0, r["rotation"], 0.01)
        rng = __import__("random").Random(97 + grains + sections * 13
                                          + sum(ord(ch) for ch in rid))
        plan = C.shard_layout({"asset": r["asset"]}, sections, reverse)["shards"]
        windows = G.sand_windows(len(plan), start_sec, sweep_sec, reverse, fps)
        grain_variants = [G.sphere_mesh(0.145 * B.TUBE_DEFAULT * B.PX_CM, 8, v)
                          for v in range(3)]
        for idx, (sh, (detach, crumble, end)) in enumerate(zip(plan, windows)):
            verts, tris, normals = G.shard_mesh(B.MID_RADIUS * B.PX_CM,
                                                B.TUBE_DEFAULT * B.PX_CM,
                                                sh["a0"], sh["a1"])
            carrier = B._spawn_pmc("RP_Sand_%s_%02d" % (rid, idx), verts, tris,
                                   normals, mat, (r["x"], r["y"]),
                                   yaw_deg=r["rotation"], scale=s)
            c_bind, c_sect = U._bind_transform(seq, carrier)
            cx = sum(v[0] for v in verts) / len(verts)
            cy = sum(v[1] for v in verts) / len(verts)
            dl = math.hypot(cx, cy) or 1.0
            wx, wy = _yaw_world((cx / dl, cy / dl), r["rotation"])
            v_plane = spread * 45.3 * s * 2.0
            spin_rate = (120 + 25 * (idx % 4)) * (-1 if idx % 2 else 1)
            f_detach = max(1, int(round(detach * fps)))
            f_crumble = max(f_detach + 1, int(round(crumble * fps)))
            f_end = max(f_crumble + 1, int(round(end * fps)))
            U._key_transform(c_sect, f_detach, loc0, r["rotation"], s)
            for f, pos, spin in _spin_keys(wx, wy, loc0[0], loc0[1], detach,
                                           end, fps, v_plane, spin_rate):
                if f <= f_detach:
                    continue
                if f <= f_crumble:
                    sc = s
                elif f < f_end:
                    sc = s * (1.0 - 0.9 * (f - f_crumble)
                              / max(1, f_end - f_crumble))
                else:
                    sc = 0.01
                # spin 为世界 Z 角（度）：通道值 = -rot0 + spin → yaw_deg = rot0 - spin
                U._key_transform(c_sect, f, pos, r["rotation"] - spin, sc)
            n_sections += 1
            births = G.shard_surface_samples(
                verts, tris,
                grains // len(plan) + (1 if idx < grains % len(plan) else 0),
                rng)
            for k, local in enumerate(births):
                birth = round((crumble + G.SAND_CRUMBLE_SEC * k / max(1, len(births)))
                              * fps) / fps
                f_birth = max(1, int(round(birth * fps)))
                spin_deg = spin_rate * (birth - detach)
                phi = math.radians(-r["rotation"] + spin_deg)
                cb, sb = math.cos(phi), math.sin(phi)
                bx = loc0[0] + wx * v_plane * (birth - detach) \
                    + s * (local[0] * cb - local[1] * sb)
                by = loc0[1] + wy * v_plane * (birth - detach) \
                    + s * (local[0] * sb + local[1] * cb)
                bz = s * local[2]
                scx, scy = G.sand_scatter(rng, spread, s)
                vx = wx * v_plane + scx
                vy = wy * v_plane + scy
                size = 0.65 + 0.60 * rng.random()
                mesh_v, tris_v, normals_v = grain_variants[n_grains % 3]
                grain = B._spawn_pmc("RP_Grain_%s_%03d" % (rid, n_grains),
                                     mesh_v, tris_v, normals_v, mat,
                                     (0.0, 0.0), scale=s * size)
                g_bind, g_sect = U._bind_transform(seq, grain)
                tau = 0.0
                step = 1.0 / fps
                while True:
                    fall = (tau - tau * tau / (2.0 * G.SAND_STOP_SEC)
                            if tau < G.SAND_STOP_SEC
                            else 0.5 * G.SAND_STOP_SEC)
                    U._key_transform(
                        g_sect, max(1, int(round((birth + tau) * fps))),
                        (bx + vx * fall, by + vy * fall), r["rotation"],
                        s * size, z_cm=bz * max(0.0, 1.0 - tau / 0.2))
                    if tau >= G.SAND_STOP_SEC:
                        break
                    tau = round((tau + step) * fps) / fps
                n_grains += 1
    unreal.EditorAssetLibrary.save_asset(seq.get_path_name())
    cam = None
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if actor.get_actor_label() == "RP_TopCamera":
            cam = actor
            break
    if cam is not None:
        U._bind_camera_cut(seq, cam, end_frame)
        unreal.EditorAssetLibrary.save_asset(seq.get_path_name())
    return {"ok": True, "frames": [0, end_frame], "sections": n_sections,
            "grains": n_grains, "seq": seq.get_path_name()}
