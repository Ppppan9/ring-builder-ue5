# -*- coding: utf-8 -*-
"""RingBuilder 共享内核 II：卡通色带（与 ring_level_builder rp_scene.TOON_RING_STOPS 同源）。

环管截面从内沿到外沿的色带（俯拍观感对齐原版贴图）：
    位置 0.00–1.00（0 = 管内沿，1 = 管外沿），每档 (位置, 明度系数 k, 混白量 w)
    最终色 = sRGB(hex)·k 再混白 w，编码回 sRGB 写入 256×1 纹理（u 方向采样）。

三端采样方式：
    UE5  = 网格 UV.u 径向 + TextureSample（纹理 sRGB 导入自动线性化）
    C4D  = UVWTag 径向 + bitmap shader
    Blender（ring_level_builder）= rp_tube 顶点属性 → ColorRamp（原版）
"""
import math

TOON_RING_STOPS = [
    (0.00, 0.62, 0.0), (0.045, 0.62, 0.0), (0.075, 1.00, 0.0),
    (0.235, 1.00, 0.0), (0.255, 1.04, 0.16), (0.335, 1.04, 0.16),
    (0.355, 1.00, 0.0), (0.745, 1.00, 0.0), (0.775, 0.70, 0.0),
    (0.925, 0.70, 0.0), (0.95, 0.56, 0.0), (1.00, 0.56, 0.0)]
TOON_EMISSION = 0.55          # 自发光 = 色带原色 × 0.55
TOON_DIFFUSE = 0.45           # 受光底色 = 色带 × 0.45
RAMP_W = 256                  # 纹理宽度（档间线性插值）


def _hex_lin(hexstr):
    """sRGB hex → 线性 RGB（0-1）。"""
    def f(x):
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return [f(int(hexstr[i:i + 2], 16) / 255.0) for i in (0, 2, 4)]


def _srgb_enc(v):
    """线性 0-1 → sRGB 0-255。"""
    v = min(1.0, max(0.0, v))
    s = v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
    return max(0, min(255, round(s * 255)))


def toon_rgb_row(hexstr):
    """一色 → 色带 256 行像素（sRGB 0-255 三元组列表，u = 管内沿→外沿）。"""
    base = _hex_lin(hexstr)
    row = []
    for i in range(RAMP_W):
        t = i / (RAMP_W - 1.0)
        lo, hi = TOON_RING_STOPS[0], TOON_RING_STOPS[-1]
        for j in range(len(TOON_RING_STOPS) - 1):
            if TOON_RING_STOPS[j][0] <= t <= TOON_RING_STOPS[j + 1][0]:
                lo, hi = TOON_RING_STOPS[j], TOON_RING_STOPS[j + 1]
                break
        span = (hi[0] - lo[0]) or 1.0
        u = (t - lo[0]) / span
        k = lo[1] + (hi[1] - lo[1]) * u
        w = lo[2] + (hi[2] - lo[2]) * u
        row.append(tuple(_srgb_enc(min(1.0, c * k) * (1 - w) + w)
                         for c in base))
    return row


def tube_to_u(tube):
    """管截面径向位置（-1 内沿 … +1 外沿）→ 纹理 u（0..1）。"""
    return (tube + 1.0) * 0.5


# 说明：色带 PNG（256×1 sRGB）由仓库预生成提交（Content/Python/_ramp_<色>.png，
# 共 11 色），运行时不写文件——UE 端 AssetImportTask 直接引用仓库文件，
# C4D 端用 BaseBitmap 内存生成 + Save。生成脚本见仓库外本地工具。
