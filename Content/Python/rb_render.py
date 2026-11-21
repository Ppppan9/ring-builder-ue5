# -*- coding: utf-8 -*-
"""RingBuilder：UE Movie Render Queue 渲染出片（广告成片 PNG 序列 1080×1920@30）。

前置：工程需启用 MovieRenderPipeline 插件（设置 → 插件 → Movie Render Pipeline）。
rb_unlock 先生成 Sequence（含相机 cut，缺则本模块自动重建）。

用法：
    import rb_render
    rb_render.render("/path/to/level.json", out_dir="D:/renders/ring_ad")
    # 返回后：窗口 → 电影 → Movie Render Queue → RB_AdJob → Render
    # （若 auto_start 自动启动成功则无需手动）
"""
import json
import sys

import unreal

HERE = "/Users/houtao/Documents/Unreal Projects/test01/Plugins/RingBuilder/Content/Python"
if HERE not in sys.path:
    sys.path.append(HERE)

import rp_core as C          # noqa: E402
import rb_unlock as U        # noqa: E402


def _find_seq(seq_name="RB_Unlock"):
    path = U.SEQ_DIR + "/" + seq_name
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    return None


def _configure_job(job, fps, out_dir):
    conf = job.get_configuration()
    img = conf.find_or_add_setting_by_class(
        unreal.MoviePipelineImageSequenceOutputSetting, True)
    img.set_editor_property("output_directory", unreal.DirectoryName(out_dir))
    img.set_editor_property("file_name_format", "ring_{frame_number}")
    img.set_editor_property("output_resolution", unreal.IntPoint(1080, 1920))
    try:
        aa = conf.find_or_add_setting_by_class(
            unreal.MoviePipelineAntiAliasingSetting, True)
        aa.set_editor_property("spatial_sample_count", 1)
    except (AttributeError, TypeError):
        pass
    job.set_editor_property("fps", unreal.FrameRate(fps, 1))


def render(json_path, seq_name="RB_Unlock", out_dir="D:/renders/ring_ad",
           auto_start=True):
    """配置 MRQ 渲染 job（PNG 序列 1080×1920）并写入渲染队列。返回状态 dict。"""
    with open(json_path, "r", encoding="utf-8") as f:
        L = json.load(f)
    C.validate_level(L)
    seq = _find_seq(seq_name)
    if seq is None:
        U.unlock(json_path, seq_name=seq_name)
        seq = _find_seq(seq_name)
    if seq is None:
        raise RuntimeError("Sequence 生成失败")
    # MRQ 需要已保存的关卡路径
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    sub = unreal.get_engine_subsystem(unreal.MoviePipelineQueueSubsystem)
    queue = sub.get_queue()
    job = unreal.MoviePipelineExecutorJob()
    job.sequence = unreal.SoftObjectPath(seq.get_path_name())
    job.set_author("RingBuilder")
    world_path = unreal.EditorLevelLibrary.get_editor_world().get_path_name()
    job.map = unreal.SoftObjectPath(world_path)
    fps = int(L.get("fps") or 30)
    _configure_job(job, fps, out_dir)
    queue.add_job(job)
    jobs = queue.get_jobs()
    started = False
    if auto_start:
        # executor API 各版本签名有差异：逐个尝试，失败则提示手动渲染
        try:
            ex = unreal.MoviePipelineCPUExecutor()
            ex.execute_unreal_links()
            started = True
        except Exception:
            try:
                sub.begin_familiar_editor_executor(queue)
                started = True
            except Exception:
                started = False
    n_jobs = len(jobs) if hasattr(jobs, "__len__") else jobs.length()
    return {"ok": True, "job": "RB_AdJob", "res": "1080x1920", "fps": fps,
            "out_dir": out_dir, "queue_len": n_jobs, "auto_started": started,
            "seq": seq.get_path_name()}
