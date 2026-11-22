# -*- coding: utf-8 -*-
"""RingBuilder：解环动画 → Level Sequence 关键帧。

复用 rp_core.bake_timeline（与 Blender 端同一解谜时间轴）：
旋转步（keys）→ 移出（outros.move）→ 缩尾消失（代替淡出，扣子已 attach 随环缩没）。

用法：
    import rb_unlock
    rb_unlock.unlock("/path/to/level.json")     # 建模（若未建）+ 写解环动画
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

SEQ_DIR = "/Game/RingBuilder"


def _world_drift(drift_xy, rot_deg, scale):
    """环局部漂移（素材像素，canvas y 向下）→ 世界 cm 偏移（UE，yaw = -rot）。"""
    yaw = math.radians(-rot_deg)
    lx, ly = drift_xy[0] * scale * B.PX_CM, -drift_xy[1] * scale * B.PX_CM
    return (lx * math.cos(yaw) - ly * math.sin(yaw),
            lx * math.sin(yaw) + ly * math.cos(yaw))


def _find_rings():
    """label 前缀扫描：RP_Ring_<rid> → actor。"""
    out = {}
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        label = actor.get_actor_label()
        if label.startswith("RP_Ring_"):
            out[label[len("RP_Ring_"):]] = actor
    return out


def _canvas_to_cm(p):
    return (p[0] * B.PX_CM, -p[1] * B.PX_CM)


def _new_sequence(name, fps, end_frame):
    path = SEQ_DIR + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        unreal.EditorAssetLibrary.delete_asset(path)
    at = unreal.AssetToolsHelpers.get_asset_tools()
    seq = at.create_asset(name, SEQ_DIR, unreal.LevelSequence,
                          unreal.LevelSequenceFactoryNew)
    seq.set_display_rate(unreal.FrameRate(fps, 1))
    seq.set_playback_start(0)
    seq.set_playback_end(end_frame)
    return seq


def _bind_transform(seq, actor):
    binding = seq.add_possessable(actor)
    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    section = track.add_section()
    return binding, section


def _bind_camera_cut(seq, cam_actor, end_frame):
    """俯拍相机绑定到 Sequencer 相机 cut（MRQ 拍摄机位）。返回 binding。"""
    binding = seq.add_possessable(cam_actor)
    track = seq.add_master_track(unreal.MovieSceneCameraCutTrack)
    section = track.add_section()
    section.set_start_frame(0)
    section.set_end_frame(end_frame)
    section.set_camera_binding_id(binding.get_id())
    return binding


def _key_transform(section, frame, loc_cm, yaw_deg, scale, z_cm=0.0):
    ch = section.get_channels()
    x, y = loc_cm
    vals = [x, y, z_cm, 0.0, 0.0, -yaw_deg, scale, scale, scale]
    for i, v in enumerate(vals):
        ch[i].add_key(unreal.FrameNumber(frame), v)


def unlock(json_path, seq_name="RB_Unlock", move_out=True, shatter=False):
    """建模（若场景里没有环）→ bake_timeline → 写 Level Sequence。
    shatter=True 时按 rp_core 碎片计划生成弧段碎片（drift/spin/缩尾）。"""
    with open(json_path, "r", encoding="utf-8") as f:
        L = json.load(f)
    C.validate_level(L)
    rings_actors = _find_rings()
    if not rings_actors:
        B.build(json_path)
        rings_actors = _find_rings()
    if not rings_actors:
        raise RuntimeError("场景里没有 RingBuilder 的环，且建模失败")
    fps = int(L.get("fps") or 30)
    T = C.bake_timeline(L, {"moveOut": move_out, "fade": True,
                            "shatter": shatter, "shards": 12,
                            "shatterSec": 0.8,
                            "secPerStep": 0.6, "degPerSec": 120,
                            "moveDist": 160, "moveSec": 0.5}, start=0.0)
    if not T.get("ok"):
        raise RuntimeError(T.get("error") or "解谜时间轴生成失败")
    base = {r["id"]: r for r in L["rings"]}
    end_frame = int(T["end"] * fps) + 2
    seq = _new_sequence(seq_name, fps, end_frame)
    bindings = {}
    n_keys = 0
    rid_actors = _find_rings()
    for k in T["keys"]:
        rid = k["ring"]
        actor = rid_actors.get(rid)
        if actor is None:
            continue
        if rid not in bindings:
            bindings[rid], section0 = None, None
            binding, section = _bind_transform(seq, actor)
            bindings[rid] = (binding, section)
        r0 = base[rid]["rotation"]
        f0, f1 = max(1, round(k["t0"] * fps)), round(k["t1"] * fps)
        loc = _canvas_to_cm((base[rid]["x"], base[rid]["y"]))
        s = base[rid]["scale"] / 100.0
        _key_transform(section, f0, loc, r0 + k["v0"], s)
        _key_transform(section, f1, loc, r0 + k["v1"], s)
        n_keys += 2
    for O in T["outros"]:
        rid = O["ring"]
        actor = rid_actors.get(rid)
        if actor is None:
            continue
        if rid not in bindings:
            binding, section = _bind_transform(seq, actor)
            bindings[rid] = (binding, section)
        binding, section = bindings[rid]
        fps_ = fps
        r = base[rid]
        s = r["scale"] / 100.0
        loc0 = _canvas_to_cm((r["x"], r["y"]))
        rot0 = r["rotation"]
        mv = O.get("move")
        if mv:
            f0, f1 = max(1, round(mv["t0"] * fps_)), round(mv["t1"] * fps_)
            _key_transform(section, f0, loc0, rot0, s)
            _key_transform(section, f1, _canvas_to_cm(mv["to"]), rot0, s)
            n_keys += 2
        if O.get("op"):
            f_shrink0 = max(1, round(O["op"][0][0] * fps_))
            f_shrink1 = max(1, round(O["op"][-1][0] * fps_))
            _key_transform(section, f_shrink0, loc0, rot0, s)
            _key_transform(section, f_shrink1, loc0, rot0, 0.01)
            n_keys += 2
        if O.get("shards"):
            # 原环在 hideAt 隐藏（scale 0.01），碎片各自 drift/spin/缩尾
            f_hide = max(1, round(O["hideAt"] * fps_))
            _key_transform(section, f_hide, loc0, rot0, s)
            _key_transform(section, f_hide + 1, loc0, rot0, 0.01)
            n_keys += 2
            a = C.asset(base[rid]["asset"])
            color = a.get("color", "blue")
            tube_px = B.TUBE_DEFAULT * B.PX_CM
            for sh in O["shards"]:
                verts, tris, normals = G.shard_mesh(
                    B.MID_RADIUS * B.PX_CM, tube_px, sh["a0"], sh["a1"])
                sh_actor = B._spawn_pmc(
                    "RP_Shard_%s_%d" % (rid, sh["i"]), verts, tris, normals,
                    B.ensure_toon_material(color), (base[rid]["x"],
                                                    base[rid]["y"]),
                    yaw_deg=rot0, scale=s)
                sh_bind, sh_sect = _bind_transform(seq, sh_actor)
                dx, dy = _world_drift(sh["drift"], rot0, s)
                f_tb = max(1, round(sh["tb"] * fps_))
                f_t1 = max(f_tb + 1, round(sh["t1"] * fps_))
                f_end = max(1, round(sh["op"][-1][0] * fps_))
                _key_transform(sh_sect, f_tb, loc0, rot0, s)
                _key_transform(sh_sect, f_t1,
                               (loc0[0] + dx, loc0[1] + dy),
                               rot0 + sh["spin"], s)
                _key_transform(sh_sect, f_end,
                               (loc0[0] + dx, loc0[1] + dy),
                               rot0 + sh["spin"], 0.01)
                n_keys += 3
    unreal.EditorAssetLibrary.save_asset(seq.get_path_name())
    # 俯拍相机绑定相机 cut（缺它 MRQ 拍不到机位）
    cam = None
    for actor in unreal.EditorLevelLibrary.get_all_level_actors():
        if actor.get_actor_label() == "RP_TopCamera":
            cam = actor
            break
    if cam is not None:
        _bind_camera_cut(seq, cam, end_frame)
    unreal.EditorAssetLibrary.save_asset(seq.get_path_name())
    return {"ok": True, "frames": [0, end_frame], "keys": n_keys,
            "rings": len(bindings), "seq": seq.get_path_name(),
            "camera_cut": cam is not None}
