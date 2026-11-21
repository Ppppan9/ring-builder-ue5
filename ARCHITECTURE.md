# 解环项目 · 三平台功能架构（ARCHITECTURE.md）

> 适用仓库：RingBuilder-UE5（本目录）/ ring-builder-c4d（同文档副本）
> 更新：2026-11-21 · 状态：MVP+二期完成，内核级测试全过，真机首跑待验收

## ① 总体数据流

```
                       前端关卡搭建器 (web/index.js)
                            │ 导出关卡 JSON
                            ▼
        ┌─────────────── 关卡 JSON（version:1）───────────────┐
        │  rings[] / clasps[] / props[] / skin / fps / 宽高   │
        └──────┬──────────────────┬──────────────────┬────────┘
               ▼                  ▼                  ▼
        ┌─ Blender ─┐      ┌─ UE5 ──┐         ┌─ C4D ──┐
        │ ring_level│      │ RingBuilder│     │ ring-  │
        │ _builder  │      │ 插件       │     │ builder│
        │ v1.7.0    │      │            │     │ .pyp   │
        └─────┬─────┘      └─────┬──────┘     └───┬────┘
              │                  │                │
              ▼                  ▼                ▼
         场景+解环动画      场景+Sequencer    场景+CTrack
              │                  │                │
              ▼                  ▼                ▼
        kit 表演层+渲染      MRQ 渲染          参数渲染
              │                  │                │
              └────► PNG/MP4 广告成片 ◄───────────┘
```

## ② 共享内核（三端同一份代码，核心资产）

| 文件 | 内容 | 端点消费者 |
|---|---|---|
| `rp_core.py` | 关卡校验 / 扣点几何（`clasp_seat`）/ 解谜规划（`plan_unlock`）/ 时间轴（`bake_timeline`）/ 破碎计划 | 三端全部 |
| `rb_toon.py` | 卡通色带 12 档（TOON_RING_STOPS）→ 256×1 sRGB PNG（纯 Python PNG writer） | UE（Texture 导入）/ C4D（BaseBitmap）/ Blender 走原版 ColorRamp |
| `rb_geom.py` | 三环结扫掠（`knot_sections` 10080 顶点）/ 钻戒（`gem_sections` 环带+刻面+六爪 8 sections）/ 破碎弧段管（`shard_mesh`） | UE / C4D（Blender 端原版自带） |
| `assets_manifest.json` | 81 个素材参数（内外径/缺口角/卡扣 attach） | 三端全部 |

**单位与坐标契约**：1 画布像素 = 0.1 cm（UE/C4D）= 0.001 m（Blender）；
画布 x → 端点 X，画布 y（向下）→ 端点 −Y（C4D 为 −Z）；C 环缺口朝局部 +Y；
环旋转 = 画布顺时针角 × (−1)；素材角常量必须从原插件**程序化提取**（手抄会错）。

## ③ 各端功能架构

### Blender（ring_level_builder v1.7.0 + ua-game-kit 0.2.0）— 主战场

```
┌─ 建模/关卡层（原版插件）──────────────────────────┐
│ rp_server   socket 接收前端 JSON                  │
│ rp_scene    bmesh 程序化建模（8 主题材质/色带/    │
│             布尔挖孔/Voronoi 破碎/俯拍相机灯光）  │
│ 解环动画    apply_unlock / bake_level（淡出材质） │
└──────────────────────────────────────────────────┘
┌─ 买量表演层（ua-game-kit，独占）──────────────────┐
│ ring_lib      C环簇/拔环回弹/飞槽/感叹词/手指     │
│ kit 全家桶    场景/材质/动画/物理/相机/HUD/结尾卡 │
│ 渲染          批量并行/多尺寸矩阵/封面/交付包      │
└──────────────────────────────────────────────────┘
```

### UE5（Plugins/RingBuilder，纯 Content+Python 插件免编译）

```
Content/Python/
├─ rp_core / rb_toon / rb_geom   ← 共享内核（逐字复用）
├─ rb_build.py    关卡建模：PMC 手写顶点（C环/花心/T扣/三环结/
│                 钻戒双材质）+ 卡通色带纹理材质 + 俯拍正交相机 + 灯光地面
├─ rb_unlock.py   Sequencer 动画：旋转步→移出→缩尾/破碎弧段碎片
│                 （12 片/环）+ 相机 cut 绑定
└─ rb_render.py   MRQ 出片：PNG 序列 1080×1920@30 → 渲染队列 RB_AdJob
```

### C4D（ring-builder-c4d，单 .pyp CommandData 插件）

```
ring_builder_c4d.pyp
├─ 扩展菜单「导入关卡 JSON」→ 一键：建模+材质+层级+烘焙动画
├─ 建模：PolygonObject 手写（同公式）+ Phong/UVWTag/纹理
├─ 解环：CTrack 关键帧（旋转/移出/缩尾/破碎碎片）
└─ setup_render：画幅=关卡宽高/帧范围/PNG 序列（命令行 -nogui -render 批量）
```

## ④ 功能矩阵

| 功能 | Blender | UE5 | C4D |
|---|---|---|---|
| 关卡 JSON 导入 | ✅ socket+文件 | ✅ 文件桥 | ✅ 文件对话框 |
| C 环/整环/卡扣 | ✅ 全类型 | ✅ MVP（T 扣占位箍） | ✅ MVP |
| 卡通色带材质 | ✅ 原版 ColorRamp | ✅ 纹理+径向 UV | ✅ 纹理+UVWTag |
| 玉/木/金属/紫水晶主题 | ✅ | 二期 | 二期 |
| 三环结/钻戒 | ✅ | ✅ | ✅ |
| 解环动画（旋转/移出/淡出） | ✅ | ✅ 缩尾代替 | ✅ 缩尾代替 |
| 破碎 | ✅ Voronoi 斜切 | ✅ 弧段碎片 | ✅ 弧段碎片 |
| 俯拍相机 | ✅ 正交 | ✅ 正交+相机 cut | 二期（透视代） |
| 渲染出片 | ✅ kit 全链 | ✅ MRQ | ✅ 参数配置 |
| 广告表演层 | ✅ ua-game-kit 独占 | FBX 中转 | FBX 中转 |

## ⑤ 验证状态与首跑指引

- **内核**（rp_core/rb_toon/rb_geom）：纯 Python 测试全过；几何真值断言
  （三环结中心线 290.0px vs 拟合 289.93、色带明暗关系、扣点落管带、
  钻石 reach 291px / 不穿地、碎片弧段外沿 175.8px）
- **平台层**：stub 干跑全过（控制流/数据流）；真机首跑如遇 API 签名差异，
  按两侧 README「首跑注意」排查（PMC create_mesh_section 重载、Sequencer
  通道 yaw=index5、纹理 sRGB、C4D 材质常量/LUMINANCE_STRENGTH）
- 测试脚本（内核/几何/UE 干跑/C4D 干跑）随文档归档于仓库 tests/ 或对应目录

## ⑥ 二期路线（剩余）

1. 金属/紫水晶主题（影棚反射材质，成本最高）
2. UE Chaos / C4D Voronoi Fracture 原生破碎增强（当前弧段碎片）
3. 材质级 alpha 淡出（替代缩尾）
4. UE MRQ H.264 直出（需 ffmpeg）、C4D 平行投影相机
