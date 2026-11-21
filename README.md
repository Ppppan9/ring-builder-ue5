# RingBuilder for Unreal Engine 5

解环关卡 JSON → UE5 场景（程序化建模 + 解环 Sequencer 动画）。与 Blender 端
（ring_level_builder）和 C4D 端共享同一份 `rp_core.py` 解谜内核与 `assets_manifest.json`。

## 安装

把 `RingBuilder/` 整个目录放入工程的 `Plugins/` 下（如 `test01/Plugins/RingBuilder`），
重启编辑器（纯 Content+Python 插件，无需编译）。

## 用法

编辑器 Python 控制台（输出日志 → Cmd/Ctrl + 输入 `py`）：

```python
import rb_build, rb_unlock

# 1) 关卡建模（俯拍相机/灯光/地面一并生成）
rb_build.build("C:/path/to/level.json")

# 2) 解环动画（Level Sequence：旋转步 → 移出 → 缩尾消失）
rb_unlock.unlock("C:/path/to/level.json")   # 生成 /Game/RingBuilder/RB_Unlock
```

命令行（CI/批量）：

```bash
UnrealEditor-Cmd <工程>.uproject -run=pythonscript -script="build_level.py" -stdout -unattended
```

关卡 JSON 来自前端搭建器（ring_level_builder web 版导出），样例见
`Content/Python/rb_level_sample.json`（花心 + 四 C 环，内核级测试已验证扣点精确、可解）。

## 单位与坐标

1 画布像素 = 0.1 cm；画布 x → UE X，画布 y（向下）→ UE -Y；C 环缺口朝局部 +Y。
环 = ProceduralMeshComponent（EmptyActor 根组件），扣子独立 Actor `attach_to` 到所属环
（解环旋转时扣子自动跟随）。

## 首跑注意（无法在无引擎环境验证的 API 点）

本插件在纯 Python 干跑（stub）下验证了全部控制流；真机首跑如遇 API 签名差异，
按下列点排查（均为 5.x 已知易变处）：

1. `ProceduralMeshComponent.create_mesh_section` 重载——若报参数不匹配，改用带
   `create_collision: bool` 的短重载（去掉 uv1/uv2/uv3）。
2. `unreal.EmptyActor` 若不存在，脚本已自动回退 `unreal.Actor`。
3. Sequencer 通道索引：`section.get_channels()` 顺序为
   LocX/Y/Z、Roll/Pitch/Yaw、ScaleX/Y/Z（yaw 在 index 5）。
4. 缩尾消失代替 AE 淡出（scale 1 → 0.01），扣子随父环缩没；材质级 alpha 动画二期。
5. 俯拍正交相机：`CameraComponent.projection_mode = ORTHOGRAPHIC` +
   `ortho_width = max(宽,高)·0.11`。
6. 卡通色带：256×1 sRGB 渐变纹理经 `AssetImportTask` 导入 `/Game/RingBuilder/`，
   UV.u = 管径向（内沿 0 → 外沿 1）。若导入后纹理偏灰，检查纹理资产
   `sRGB` 是否为开（脚本已 try 设置）。

## 已含（MVP + 二期）

- 默认主题：C 环/整环（缺口 80° 夸张版 + 半球圆头）、T 扣（实心箍占位）
- **卡通色带材质**：256×1 sRGB 渐变纹理 + 径向 UV（对齐 Blender 端俯拍观感）
- **三环结道具**：傅里叶中心线扫掠（`rb_geom.knot_sections`，10080 顶点，暖银）
- **钻戒**：环带 + 简化明亮式圆钻（flat 刻面）+ 六爪镶（`rb_geom.gem_sections`，metal/gem 双材质 8 section）
- **破碎**：`unlock(json, shatter=True)` 按 rp_core 碎片计划生成弧段碎片（12 片/环，
  drift/spin/缩尾关键帧，原环 hideAt 隐藏）——与 Blender 端 shatter 模式同时间轴
- 解环动画与 Blender 端同一时间轴（`rp_core.bake_timeline`：旋转步/移出 160px/缩尾）
- 俯拍正交相机 + 主光 + 天光 + 灰色地面
- 样例关卡：`rb_level_sample.json`（花心+四C环）、`rb_level_sample2.json`（花心+C环+钻戒+三环结）

## 渲染出片（Movie Render Queue）

前置：工程启用 **MovieRenderPipeline** 插件（设置 → 插件 → 搜索启用并重启）。

```python
import rb_render
rb_render.render("/path/to/level.json", out_dir="D:/renders/ring_ad")
# 自动：Sequence 校验（含相机 cut）→ 保存关卡 → 配置 MRQ job
#      （PNG 序列 / 1080×1920@30 / 全帧范围 / 抗锯齿 1 采样）→ 写入渲染队列
# auto_start 尝试自动启动（executor API 因版本而异），失败则手动：
# 窗口 → 电影 → Movie Render Queue → RB_AdJob → Render
```

命令行批量（CI）：`UnrealEditor-Cmd <工程>.uproject -run=pythonscript
-script="rb_render调用脚本" -moviepipelinelocalexecutor ...`（首跑校准后固化）。

## 二期路线（剩余）

金属/紫水晶主题（影棚反射材质）、材质级 alpha 淡出（替代缩尾）、
UE Chaos 原生 Voronoi 增强（当前为弧段碎片）、MRQ H.264 直出（需 ffmpeg）。
