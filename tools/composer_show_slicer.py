"""USD Composer --exec: the Slicer (MONAI) organs in Composer, RTX, in 3D through
the displayxr.omniverse extension (used as-is; this script only drives it).

New stage -> reference Documents/DisplayXR/Slicer/SlicerScene.usda (Kit layout:
Y-up cm, anterior = -Z) at /World/Slicer -> dome light -> camera in front of the
body, DXR_SLICER_PITCH degrees down (default 35; >= 50 overshoots the framing) ->
RTX warm-up -> Start 3D -> frame the organs. Log: %TEMP%/composer_show_slicer.log
"""
import asyncio
import math
import os
import traceback

import omni.kit.app
import omni.usd

LOG = os.path.join(os.environ.get("TEMP", "."), "composer_show_slicer.log")
USD = os.environ.get("DXR_SLICER_USD") or os.path.join(
    os.path.expanduser("~"), "Documents", "DisplayXR", "Slicer", "SlicerScene.usda")
PITCH = float(os.environ.get("DXR_SLICER_PITCH", "35"))


def log(*a):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(" ".join(str(x) for x in a) + "\n")


def build_stage():
    from pxr import Gf, Sdf, UsdGeom, UsdLux
    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    ref = stage.DefinePrim("/World/Slicer", "Xform")
    ref.GetReferences().AddReference(USD)
    dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome.CreateIntensityAttr(1000.0)
    key = UsdLux.DistantLight.Define(stage, "/World/KeyLight")
    key.CreateIntensityAttr(2500.0)
    UsdGeom.Xformable(key).AddRotateXYZOp().Set(Gf.Vec3f(-45, -20, 0))

    cache = UsdGeom.BBoxCache(0, [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    rng = cache.ComputeWorldBound(ref).ComputeAlignedRange()
    mid, size = rng.GetMidpoint(), rng.GetSize()
    radius = size.GetLength() * 0.5
    # In front of the body (anterior = -Z in Kit's layout), PITCH degrees down.
    dist = radius * 3.0
    p = math.radians(PITCH)
    eye = Gf.Vec3d(mid[0], mid[1] + dist * math.sin(p), mid[2] - dist * math.cos(p))
    from omni.kit.viewport.utility import get_active_viewport
    vp = get_active_viewport()
    cam = stage.GetPrimAtPath(vp.camera_path)
    m = Gf.Matrix4d().SetLookAt(eye, Gf.Vec3d(mid), Gf.Vec3d(0, 1, 0)).GetInverse()
    xf = UsdGeom.Xformable(cam)
    xf.ClearXformOpOrder()
    xf.AddTransformOp().Set(m)
    log("stage: bbox mid", tuple(round(v, 1) for v in mid), "size", tuple(round(v, 1) for v in size),
        "cm; camera", tuple(round(v, 1) for v in eye), "pitch", PITCH)
    return rng


async def main():
    try:
        app = omni.kit.app.get_app()
        for _ in range(240):
            await app.next_update_async()
        await omni.usd.get_context().new_stage_async()
        for _ in range(30):
            await app.next_update_async()
        build_stage()
        omni.usd.get_context().get_selection().set_selected_prim_paths(["/World/Slicer"], True)
        for _ in range(600):  # RTX + shader warm-up before XR
            await app.next_update_async()
        from displayxr.omniverse.extension import get_session
        s = get_session()
        ok = await s.start_async()
        log("3D start", ok, getattr(s, "last_error", ""))
        for _ in range(300):
            await app.next_update_async()
        omni.usd.get_context().get_selection().set_selected_prim_paths(["/World/Slicer"], True)
        s.frame_selection()
        for _ in range(300):
            await app.next_update_async()
        log("running", s.is_running(), "comfortable range (m)", s.comfortable_depth_range())
        log("READY")
    except Exception:
        log("EXC", traceback.format_exc())


open(LOG, "w").close()
asyncio.ensure_future(main())
