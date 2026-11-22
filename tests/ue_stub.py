# -*- coding: utf-8 -*-
"""Headless fake `unreal` module：覆盖 rb_build / rb_unlock / rb_sand 用到的 API 子集，
Actor / Sequencer 关键帧全部记录在 Python 对象上供断言。仅测试用。"""

import sys
import types


class _Const:
    """任意常量/未建模类的兜底：属性链无限取。"""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, name):
        return _Const("%s.%s" % (self._name, name))

    def __call__(self, *args, **kwargs):
        return _Rec(self._name, args)

    def __repr__(self):
        return "<const %s>" % self._name


class _Rec:
    def __init__(self, kind, args=()):
        self.kind = kind
        self.args = args
        self.props = {}
        self.records = []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Const("%s.%s" % (self.kind, name))

    def set_editor_property(self, name, value):
        self.props[name] = value

    def get_editor_property(self, name):
        return self.props.get(name)

    def __call__(self, *args, **kwargs):
        return _Rec(self.kind, args)


class Vector:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = float(x), float(y), float(z)

    def __repr__(self):
        return "Vector(%g, %g, %g)" % (self.x, self.y, self.z)


class Rotator:
    def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
        self.pitch, self.yaw, self.roll = pitch, yaw, roll


class Vector2D:
    def __init__(self, x=0.0, y=0.0):
        self.x, self.y = x, y


class FrameNumber:
    def __init__(self, value=0):
        self.value = int(value)


class Name:
    def __init__(self, value=""):
        self.value = str(value)

    def __str__(self):
        return self.value


class ProcMeshTangent:
    def __init__(self, x=0.0, y=0.0, z=0.0, flip=False):
        self.x, self.y, self.z = x, y, z


class Channel:
    def __init__(self):
        self.keys = []

    def add_key(self, frame, value):
        self.keys.append((frame.value, value))


class Section:
    def __init__(self):
        self.start = self.end = 0
        self.camera_id = None
        self.channels = [Channel() for _ in range(9)]

    def get_channels(self):
        return self.channels

    def set_start_frame(self, f):
        self.start = f

    def set_end_frame(self, f):
        self.end = f

    def set_camera_binding_id(self, guid):
        self.camera_id = guid


class TransformTrack:
    def __init__(self):
        self.sections = []

    def add_section(self):
        s = Section()
        self.sections.append(s)
        return s


class CameraCutTrack:
    def __init__(self):
        self.sections = []

    def add_section(self):
        s = Section()
        self.sections.append(s)
        return s


class Binding:
    _next = 1

    def __init__(self, actor):
        self.actor = actor
        self.tracks = []
        self.guid = Binding._next
        Binding._next += 1

    def get_id(self):
        return self.guid

    def add_track(self, cls):
        t = cls()
        self.tracks.append(t)
        return t


class LevelSequence:
    def __init__(self, name, folder):
        self.name = name
        self.folder = folder
        self.bindings = []
        self.master_tracks = []
        self.display_rate = None
        self.playback = [0, 0]

    def set_display_rate(self, rate):
        self.display_rate = rate

    def set_playback_start(self, f):
        self.playback[0] = f

    def set_playback_end(self, f):
        self.playback[1] = f

    def add_possessable(self, actor):
        b = Binding(actor)
        self.bindings.append(b)
        return b

    def add_master_track(self, cls):
        t = cls()
        self.master_tracks.append(t)
        return t

    def get_path_name(self):
        return "%s/%s" % (self.folder, self.name)


class Actor:
    def __init__(self, label, pos):
        self.label = label
        self.pos = pos
        self.rotation = Rotator()
        self.scale3d = Vector(1.0, 1.0, 1.0)
        self.root = None
        self.components = []

    def set_actor_label(self, label):
        self.label = label

    def get_actor_label(self):
        return self.label

    def set_actor_root_component(self, comp):
        self.root = comp

    def add_instance_component(self, comp):
        self.components.append(comp)

    def set_actor_rotation(self, rot, *a):
        self.rotation = rot

    def set_actor_scale3d(self, v):
        self.scale3d = v

    def attach_to_actor(self, parent, *a):
        self.parent = parent

    def get_component_by_class(self, cls):
        return _Rec("component")


class ProceduralMeshComponent(_Rec):
    def __init__(self, name, owner):
        super().__init__("ProceduralMeshComponent", (name, owner))
        self.name = name
        self.sections = []

    def create_mesh_section(self, index, *args):
        self.sections.append((index, args))

    def set_material(self, index, mat):
        self.props.setdefault("materials", {})[index] = mat

    def register_component(self):
        pass


REGISTRY = {"actors": [], "assets": {}, "saved": [], "destroyed": []}


class EditorLevelLibrary:
    @staticmethod
    def get_all_level_actors():
        return list(REGISTRY["actors"])

    @staticmethod
    def spawn_actor_from_class(cls, pos):
        actor = Actor("Actor", pos)
        REGISTRY["actors"].append(actor)
        return actor

    @staticmethod
    def destroy_actor(actor):
        REGISTRY["destroyed"].append(actor.get_actor_label())
        if actor in REGISTRY["actors"]:
            REGISTRY["actors"].remove(actor)


class EditorAssetLibrary:
    @staticmethod
    def does_asset_exist(path):
        return path in REGISTRY["assets"]

    @staticmethod
    def load_asset(path):
        return REGISTRY["assets"].get(path)

    @staticmethod
    def delete_asset(path):
        REGISTRY["assets"].pop(path, None)
        return True

    @staticmethod
    def save_asset(path):
        REGISTRY["saved"].append(path)
        return True


class AssetTools:
    def create_asset(self, name, folder, cls, factory):
        seq = LevelSequence(name, folder)
        REGISTRY["assets"]["%s/%s" % (folder, name)] = seq
        return seq

    def import_asset_tasks(self, tasks):
        for task in tasks:
            REGISTRY["assets"]["%s/%s" % (task.destination_path,
                                          task.destination_name)] = _Rec("Texture")
        REGISTRY.setdefault("imports", []).extend(tasks)


class AssetToolsHelpers:
    @staticmethod
    def get_asset_tools():
        return AssetTools()


class MaterialEditingLibrary:
    @staticmethod
    def create_material(name, folder):
        mat = _Rec("Material", (name, folder))
        REGISTRY["assets"]["%s/%s" % (folder, name)] = mat
        return mat

    @staticmethod
    def create_material_expression(mat, cls):
        return _Rec("Expression")

    @staticmethod
    def connect_material_property(*a):
        pass

    @staticmethod
    def connect_material_expressions(*a):
        pass


def install():
    mod = types.ModuleType("unreal")
    mod.__getattr__ = lambda name: _Const(name)
    mod.Vector = Vector
    mod.Rotator = Rotator
    mod.Vector2D = Vector2D
    mod.FrameNumber = FrameNumber
    mod.Name = Name
    mod.ProcMeshTangent = ProcMeshTangent
    mod.ProceduralMeshComponent = ProceduralMeshComponent
    mod.LevelSequence = _Const("LevelSequence")
    mod.LevelSequenceFactoryNew = _Const("LevelSequenceFactoryNew")
    mod.MovieScene3DTransformTrack = TransformTrack
    mod.MovieSceneCameraCutTrack = CameraCutTrack
    mod.FrameRate = lambda fps, base: (fps, base)
    mod.EmptyActor = _Const("EmptyActor")
    mod.Actor = _Const("Actor")
    mod.AssetImportTask = lambda *a, **kw: _Rec("AssetImportTask", a)
    mod.EditorLevelLibrary = EditorLevelLibrary
    mod.EditorAssetLibrary = EditorAssetLibrary
    mod.AssetToolsHelpers = AssetToolsHelpers
    mod.MaterialEditingLibrary = MaterialEditingLibrary
    sys.modules["unreal"] = mod
    return mod
