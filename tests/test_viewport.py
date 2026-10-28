"""Texture mode (3D in Slicer's own 3D view): start on the CT chest, check the
woven frame is drawn into the 3D view at the view's exact size, the depth
stays in budget, and Stop is clean. Writes tests/viewport.out.txt and
probe/viewport_*.png. Run with DXR_PLUGIN_EXCLUSIVE=sim-display for numbers
that don't need a seated viewer."""
import os, time
import slicer, qt, vtk
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "viewport.out.txt"); open(OUT, "w").close()
PROBE = os.path.join(os.path.dirname(HERE), "probe"); os.makedirs(PROBE, exist_ok=True)
def log(*a):
    with open(OUT, "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D
lg = D.DisplayXRLogic.instance()
t0 = [0.0, 0]
def grab(name):
    rw = lg.threeDWidget().threeDView().renderWindow()
    w2i = vtk.vtkWindowToImageFilter(); w2i.SetInput(rw); w2i.ReadFrontBufferOff(); w2i.ShouldRerenderOff(); w2i.Update()
    wr = vtk.vtkPNGWriter(); wr.SetFileName(os.path.join(PROBE, name)); wr.SetInputConnection(w2i.GetOutputPort()); wr.Write()
def s_start():
    mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow()
    lg.medicalLayout(); lg.loadSample("CTChest", "CT-Chest-Contrast-Enhanced"); slicer.util.selectModule("DisplayXR")
    slicer.app.processEvents()
    log("texture mode available", lg.textureMode())
    lg.start()
    log("start", lg.active, "error", repr(lg.error), "vp", lg.vp is not None)
def s_check(tag):
    def f():
        vp = lg.vp
        if vp is None:
            log(tag, "no session; error", repr(lg.error)); return
        rw = vp.rw
        if tag == "a":
            t0[0], t0[1] = time.time(), vp.pairs
        else:
            log("pair rate %.1f /s" % ((vp.pairs - t0[1]) / max(time.time() - t0[0], 1e-3)))
        log(tag, "status", repr(vp.status()), "|", lg.statusText(), "| drawn", vp.drawn(), "pairs", vp.pairs,
            "state 0x%x" % (vp.texture_state() or 0))
        log(tag, "gl:", vp.gl_info())
        log(tag, "target", vp.target, "render size", vp.render_size(), "GetSize", rw.GetSize(), "actual", rw.GetActualSize(), "aspect err %.4f" % vp.aspect_error)
        d = vp.depth()
        log(tag, "depth strength %.2f glass %.1f front %.3f%% behind %.3f%% ipd %.3f" % (
            d.strength, d.glass, d.front_pct, d.behind_pct, d.ipd_factor), "content", vp.content)
        log(tag, "readout:", lg.depthText().replace("\n", " | "))
        grab(f"viewport_{tag}.png")
    return f
def project(cam, p, w, h):
    m = cam.GetCompositeProjectionTransformMatrix(w / h, -1, 1)
    v = [sum(m.GetElement(r, c) * (list(p) + [1.0])[c] for c in range(4)) for r in range(4)]
    return ((v[0] / v[3] + 1) / 2 * w, (1 - v[1] / v[3]) / 2 * h)  # px, top-left origin
def expect(eye, p, w, h):
    import math
    import displayxr_viewport as V
    q = eye.pose
    right, up, back = V._axes_from_quat((q.qx, q.qy, q.qz, q.qw))
    d = [p[i] - (q.px, q.py, q.pz)[i] for i in range(3)]
    xc = sum(d[i] * right[i] for i in range(3))
    yc = sum(d[i] * up[i] for i in range(3))
    zc = -sum(d[i] * back[i] for i in range(3))
    tl, tr, tu, td = (math.tan(a) for a in (eye.angle_left, eye.angle_right, eye.angle_up, eye.angle_down))
    return ((xc / zc - tl) / (tr - tl) * w, (tu - yc / zc) / (tu - td) * h)
def s_geom():
    vp = lg.vp
    w, h = vp.render_size()
    cam = lg.referenceCamera()
    pos, dop = cam.GetPosition(), cam.GetDirectionOfProjection()
    pts = {"glass": [pos[i] + dop[i] * vp.glass for i in range(3)], "focal": cam.GetFocalPoint()}
    if vp.content:
        for name, z in (("near", vp.content[0]), ("far", vp.content[1])):
            pts[name] = [pos[i] + dop[i] * z for i in range(3)]
    for name, p in pts.items():
        got = [project(vp.eye_cams[i], p, w, h) for i in range(2)]
        exp = [expect(vp.last_eyes[i], p, w, h) for i in range(2)]
        err = max(abs(got[i][k] - exp[i][k]) for i in range(2) for k in range(2))
        disp = (got[1][0] - got[0][0]) / w * 100
        log("geom %-5s VTK L %.2f,%.2f R %.2f,%.2f | expected L %.2f,%.2f R %.2f,%.2f | max err %.3f px | disparity %.3f %% of view" % (
            name, *got[0], *got[1], *exp[0], *exp[1], err, disp))
def s_atlas():
    import displayxr_coupling as dxr, shutil
    trig, out = dxr.atlas_paths("SlicerApp-real", True)
    if os.path.exists(out):
        os.remove(out)
    open(trig, "w").close()
    def done(n=[0]):
        if os.path.exists(out):
            dst = os.path.join(PROBE, "viewport_atlas.png"); shutil.copy(out, dst); log("atlas", dst)
        elif n[0] < 20:
            n[0] += 1; qt.QTimer.singleShot(200, done)
        else:
            log("atlas: none written (trigger still there: %s)" % os.path.exists(trig))
    qt.QTimer.singleShot(200, done)
def s_depth():
    lg.setDepthPercent(50); log("depth -> 50 %")
def s_stop():
    lg.stop(); slicer.app.processEvents()
    log("stopped", lg.active, "vp", lg.vp, "error", repr(lg.error), "| status", lg.statusText())
    grab("viewport_after_stop.png")
    slicer.app.exit(0)
for ms, fn in [(1000, s_start), (9000, s_check("a")), (12000, s_check("b")), (12200, s_geom), (12300, s_atlas), (17500, s_depth),
               (19000, s_check("c")), (20000, s_stop)]:
    qt.QTimer.singleShot(ms, fn)
