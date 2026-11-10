"""Picking from the rig's centre eye (texture mode). Spheres at known depths
and off-axis offsets; for each sphere, the pixel where the viewer sees its
centre (the average of its two eye images) is clicked with markups placement
on, once picking from the centre eye (default) and once from Slicer's mono
camera (DXR_SLICER_PICK=mono behaviour, toggled live). The placed point should
land on that sphere, on the viewer's ray to its centre. Also logs the pure
geometry: how far each camera's ray through that pixel passes from the centre.
Writes tests/picking.out.txt. Run with DXR_PLUGIN_EXCLUSIVE=sim-display (fixed
eyes, no seated viewer needed)."""
import math, os, time, traceback
import slicer, qt, vtk
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "picking.out.txt"); open(OUT, "w").close()
def log(*a):
    with open(OUT, "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D
import displayxr_viewport as V
lg = D.DisplayXRLogic.instance()
F = 1000.0
SPHERES = [(z, x * z, 12 * z) for z, x in zip([0.6, 0.8, 1.0, 1.4, 2.0], [-150, -75, 0, 75, 150])]  # (z/f, x, r)
centres = []
results = {}

def s_start():
    try:
        mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow()
        lg.medicalLayout(); slicer.app.processEvents()
        for z, x, r in SPHERES:
            src = vtk.vtkSphereSource(); src.SetRadius(r); src.SetCenter(x, F - z * F, 0)
            src.SetThetaResolution(64); src.SetPhiResolution(64); src.Update()
            m = slicer.modules.models.logic().AddModel(src.GetOutput()); m.GetDisplayNode().SetColor(1, 0.85, 0.2)
            centres.append(((x, F - z * F, 0.0), r))
        vn = lg.threeDWidget().mrmlViewNode(); vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
        cam = lg.referenceCamera(); cam.SetPosition(0, F, 0); cam.SetFocalPoint(0, 0, 0); cam.SetViewUp(0, 0, 1)
        lg.autoScreenPlane = False
        lg.start()
        log("start", lg.active, "error", repr(lg.error), "vp", lg.vp is not None,
            "pick_centre", lg.vp.pick_centre if lg.vp else None)
    except Exception:
        log(traceback.format_exc())

def seen_px(eyes, p, w, h):
    """VTK display px (bottom-left origin) where the viewer sees world point p:
    the average of its two eye images."""
    xs, ys = [], []
    for e in eyes:
        q = e.pose
        right, up, back = V._axes_from_quat((q.qx, q.qy, q.qz, q.qw))
        d = [p[i] - (q.px, q.py, q.pz)[i] for i in range(3)]
        xc, yc, zc = V._dot(d, right), V._dot(d, up), -V._dot(d, back)
        tl, tr, tu, td = (math.tan(a) for a in (e.angle_left, e.angle_right, e.angle_up, e.angle_down))
        xs.append((xc / zc - tl) / (tr - tl) * w)
        ys.append((yc / zc - td) / (tu - td) * h)
    return sum(xs) / 2, sum(ys) / 2

def miss(o, v, p):
    """Distance from p to the ray o + t v."""
    d = [p[i] - o[i] for i in range(3)]
    t = V._dot(d, v)
    c = [d[i] - t * v[i] for i in range(3)]
    return math.sqrt(V._dot(c, c))

def place(px, py):
    """Click at display px with markups placement on; the new point, or None."""
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
    sel = slicer.app.applicationLogic().GetSelectionNode()
    sel.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode"); sel.SetActivePlaceNodeID(node.GetID())
    inode = slicer.app.applicationLogic().GetInteractionNode()
    inode.SetPlaceModePersistence(0); inode.SetCurrentInteractionMode(inode.Place)
    iren = lg.threeDWidget().threeDView().interactor()
    x, y = int(round(px)), int(round(py))
    for ev in ("MouseMoveEvent", "LeftButtonPressEvent", "LeftButtonReleaseEvent"):
        iren.SetEventPosition(x, y)
        iren.InvokeEvent(ev)
        slicer.app.processEvents()
    inode.SetCurrentInteractionMode(inode.ViewTransform)
    p = [0.0] * 3
    ok = node.GetNumberOfControlPoints() > 0
    if ok:
        node.GetNthControlPointPositionWorld(0, p)
    slicer.mrmlScene.RemoveNode(node)
    return p if ok else None

def s_measure(mode):
    def f():
        try:
            vp = lg.vp
            if vp is None:
                log(mode, "no session; error", repr(lg.error)); return
            vp.pick_centre = (mode == "centre")
            lg.threeDWidget().threeDView().forceRender(); slicer.app.processEvents()  # display pass in this mode
            w, h = vp.render_size()
            eyes = vp.last_eyes
            log(mode, "render size", (w, h), "centre eye", None if vp.centre is None else
                "pos %.1f,%.1f,%.1f" % (vp.centre.pose.px, vp.centre.pose.py, vp.centre.pose.pz),
                "| Slicer camera", "%.1f,%.1f,%.1f" % lg.referenceCamera().GetPosition())
            worst = 0.0
            for i, (c, r) in enumerate(centres):
                px, py = seen_px(eyes, c, w, h)
                o, v = vp.pick_ray(px, py)
                ray_miss = miss(o, v, c)
                p = place(px, py)
                if p is None:
                    log(mode, "sphere %d at %.0f,%.0f px: nothing placed" % (i, px, py)); worst = float("inf"); continue
                on = math.sqrt(sum((p[k] - c[k]) ** 2 for k in range(3))) - r       # 0 = on this sphere's surface
                # The viewer's ray: from the centre eye of the pair through the sphere centre.
                ce = vp.centre if vp.centre is not None else V.centre_eye(eyes)
                co = (ce.pose.px, ce.pose.py, ce.pose.pz)
                cv = [c[k] - co[k] for k in range(3)]; n = math.sqrt(V._dot(cv, cv)); cv = [x / n for x in cv]
                off = miss(co, cv, p)
                worst = max(worst, abs(on), off)
                results.setdefault(mode, []).append((on, off))
                log(mode, "sphere %d r %.1f at %.1f,%.1f px | ray misses centre by %.2f mm | placed %.1f,%.1f,%.1f: "
                    "%.2f mm off the surface, %.2f mm off the viewer's ray" % (i, r, px, py, ray_miss, *p, on, off))
            log(mode, "worst %.2f mm" % worst)
        except Exception:
            log(traceback.format_exc())
    return f

def s_stop():
    try:
        vp = lg.vp
        restored = vp is not None and vp._event_saved is None and vp._render_saved is None
        cam = lg.threeDWidget().threeDView().renderWindow().GetRenderers().GetFirstRenderer().GetActiveCamera()
        log("between events: renderer camera is Slicer's", cam is lg.referenceCamera(), "| restore state clean", restored)
        c, m = results.get("centre", []), results.get("mono", [])
        if c and m:
            log("SUMMARY centre: max off-ray %.2f mm, max off-surface %.2f mm | mono: max off-ray %.2f mm, max off-surface %.2f mm" % (
                max(o for _, o in c), max(abs(s) for s, _ in c), max(o for _, o in m), max(abs(s) for s, _ in m)))
        lg.stop(); slicer.app.processEvents()
        log("stopped", lg.active, "| status", lg.statusText())
    except Exception:
        log(traceback.format_exc())
    slicer.app.exit(0)

for ms, fn in [(1500, s_start), (10000, s_measure("centre")), (14000, s_measure("mono")), (18000, s_stop)]:
    qt.QTimer.singleShot(ms, fn)
