# -*- coding: utf-8 -*-
"""沙粒破碎（rb_sand.sand）宿主桩测试：python3 -I tests/test_sand_stub.py"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(ROOT, "Content", "Python")
sys.path.insert(0, HERE)
sys.path.insert(0, PY)

import ue_stub
ue_stub.install()

import unreal

import rb_sand
import rb_unlock as U

SAMPLE = os.path.join(PY, "rb_level_sample.json")

def plane_dist(xy):
    return math.hypot(xy[0], xy[1])


def channel_keys(section):
    return [list(ch.keys) for ch in section.get_channels()]


def scale_keys(section):
    return channel_keys(section)[7]


def loc_keys(section):
    xs, ys, zs = channel_keys(section)[0], channel_keys(section)[1], channel_keys(section)[2]
    return [(xs[i][0], (xs[i][1], ys[i][1], zs[i][1]))
            for i in range(len(xs))]


def main():
    # 旧功能回归：解环动画 / 碎块模式不受 rb_sand 与 _key_transform 改动影响
    u0 = U.unlock(SAMPLE, shatter=True)
    assert u0["ok"] and u0["keys"] > 0, u0
    for actor in list(ue_stub.REGISTRY["actors"]):
        ue_stub.EditorLevelLibrary.destroy_actor(actor)

    result = rb_sand.sand(SAMPLE)
    assert result["ok"], result
    assert result["sections"] == 5 * 12 and result["grains"] == 5 * 240, result
    seq = ue_stub.REGISTRY["assets"]["/Game/RingBuilder/RB_Sand"]
    assert seq.display_rate == (30, 1), seq.display_rate
    assert result["frames"][1] == seq.playback[1] > 0
    assert seq.master_tracks, "缺相机 cut"

    actors = {a.get_actor_label(): a for a in ue_stub.REGISTRY["actors"]}
    rid = sorted(k for k in actors if k.startswith("RP_Ring_"))[0][len("RP_Ring_"):]
    ring_binding = next(b for b in seq.bindings if b.actor is actors["RP_Ring_" + rid])
    ring_scale = scale_keys(ring_binding.tracks[0].sections[0])
    assert ring_scale[0][0] == 1 and abs(ring_scale[0][1] - 1.0) < 1e-6
    assert ring_scale[1][0] == 2 and ring_scale[1][1] < 0.02, "整环在起始帧缩没"

    carriers = [a for a in ue_stub.REGISTRY["actors"]
                if a.get_actor_label().startswith("RP_Sand_%s_" % rid)]
    assert len(carriers) == 12, len(carriers)
    carrier = next(a for a in carriers if a.get_actor_label().endswith("_00"))
    c_bind = next(b for b in seq.bindings if b.actor is carrier)
    c_loc = loc_keys(c_bind.tracks[0].sections[0])
    times = [f for f, _p in c_loc]
    assert times == sorted(set(times)), times
    assert c_loc[0][1][2] == 0.0 and c_loc[-1][1][2] == 0.0, "俯拍滑动：弧段不抬高"
    d0 = plane_dist(c_loc[0][1])
    d1 = plane_dist(c_loc[-1][1])
    assert d1 > d0 + 1.0, (d0, d1)
    yaw = channel_keys(c_bind.tracks[0].sections[0])[5]
    assert yaw[-1][1] != yaw[0][1], "弧段翻滚自转"
    c_scale = scale_keys(c_bind.tracks[0].sections[0])
    assert any(0.05 < v < 0.95 for _f, v in c_scale), "弧段在撒沙窗口逐渐缩小"
    assert c_scale[-1][1] < 0.02, "弧段结束后缩没"

    grains = [a for a in ue_stub.REGISTRY["actors"]
              if a.get_actor_label().startswith("RP_Grain_%s_" % rid)]
    assert len(grains) == 240, len(grains)
    grain = grains[0]
    g_bind = next(b for b in seq.bindings if b.actor is grain)
    g_loc = loc_keys(g_bind.tracks[0].sections[0])
    gtimes = [f for f, _p in g_loc]
    assert gtimes[0] == 5, gtimes[:3]  # crumble = round(0.16 * 30)
    assert gtimes == sorted(set(gtimes))
    zs = [abs(p[2]) for _f, p in g_loc]
    assert zs[0] < 2.0, "细沙出生在环管高度内"
    assert zs[-1] < 1e-6 and all(a >= b - 1e-9 for a, b in zip(zs, zs[1:])), \
        "细沙贴地滑停"
    travel = [plane_dist(p) for _f, p in g_loc]
    span = [abs(travel[i + 1] - travel[i]) for i in range(len(travel) - 1)]
    assert sum(span[:3]) > sum(span[-3:]), "细沙减速滑停"

    # 指定单环 + 反向 + 减量
    ue_stub.REGISTRY["actors"].clear()
    ue_stub.REGISTRY["assets"].clear()
    rb_build_result = __import__("rb_build").build(SAMPLE)
    result2 = rb_sand.sand(SAMPLE, seq_name="RB_Sand2", ring_id=rid,
                           sections=6, grains=60, sweep_sec=0.3, reverse=True)
    assert result2["sections"] == 6 and result2["grains"] == 60, result2
    seq2 = ue_stub.REGISTRY["assets"]["/Game/RingBuilder/RB_Sand2"]
    carriers2 = [a for a in ue_stub.REGISTRY["actors"]
                 if a.get_actor_label().startswith("RP_Sand_%s_" % rid)]
    detach = []
    for a in carriers2:
        b = next(x for x in seq2.bindings if x.actor is a)
        detach.append(loc_keys(b.tracks[0].sections[0])[0][0])
    assert detach == sorted(detach, reverse=True), "reverse=True 从另一端开始"
    assert detach[-1] - detach[0] <= 1, detach
    assert not [a for a in ue_stub.REGISTRY["actors"]
                if a.get_actor_label().startswith("RP_Sand_")
                and a not in carriers2], "重跑替换而不是叠加"
    print("UE SAND STUB: ALL PASS (%d sections, %d grains)"
          % (result["sections"], result["grains"]))


main()
