# End-to-end check: medical layout, CT chest volume rendering, Start 3D, then
# capture the projection atlas + log depth/window state.
import os, time, json, traceback, ctypes
import slicer, qt, vtk
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "test_module.out.txt"); open(OUT, "w").close()
def log(*a):
    with open(OUT, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D, displayxr_coupling as dxr
lg = D.DisplayXRLogic.instance()
def step1():
    try:
        mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow()
        lg.medicalLayout()
        lg.loadSample(os.environ.get("TEST_SAMPLE", "CTChest"), os.environ.get("TEST_PRESET", "CT-Chest-Contrast-Enhanced"))
        slicer.util.selectModule("DisplayXR")
        lg.start()
        log("started active", lg.active, "err", lg.error, "rig", json.dumps(lg.rig["json"]), "vfov deg", round(lg.rig["vfov"]*57.2958, 2))
        qt.QTimer.singleShot(int(os.environ.get("TEST_T2", "10000")), step2)
        if os.environ.get("TEST_EXIT"):
            qt.QTimer.singleShot(int(os.environ["TEST_EXIT"]), lambda: (lg.stop(), slicer.app.exit(0)))
    except Exception: log(traceback.format_exc())
def step2():
    try:
        log("hosted", lg.hostedHwnd, "owner", dxr.window_owner(lg.hostedHwnd), "main", lg.mainHwnd())
        log("viewRect", lg.viewRectPx(), "hostedRect", dxr.window_rect(lg.hostedHwnd) if lg.hostedHwnd else None)
        log("depth", lg.lastDepth, "K", lg.parallaxAtInfinity()); log(lg.statusText(), "|", lg.depthText().replace("\n", " | "))
        cam = lg.referenceCamera(); log("cam pos", cam.GetPosition(), "fp", cam.GetFocalPoint(), "dist", cam.GetDistance())
        trig, _ = dxr.atlas_paths("SlicerApp-real", True); open(trig, "w").close()
        trig2, _ = dxr.atlas_paths("SlicerApp-real", False); open(trig2, "w").close()
    except Exception: log(traceback.format_exc())
qt.QTimer.singleShot(1500, step1)
