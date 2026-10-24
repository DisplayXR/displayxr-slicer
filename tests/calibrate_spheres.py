# Calibration: textured spheres at known distances along the view axis; glass at the focal point.
import os, time, json, traceback
import slicer, qt, vtk
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "calib.out.txt"); open(OUT, "w").close()
def log(*a):
    with open(OUT, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D, displayxr_coupling as dxr
lg = D.DisplayXRLogic.instance()
if os.environ.get("CALIB_K"): D.DEPTH_LEVELS[1] = ("Comfortable", float(os.environ["CALIB_K"]), 1.0)
F = 1000.0
Z = [0.6, 0.8, 1.0, 1.4, 2.0]   # fractions of focal distance
X = [-150, -75, 0, 75, 150]
def step1():
    try:
        mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow()
        lg.medicalLayout(); slicer.app.processEvents()
        for z, x in zip(Z, X):
            src = vtk.vtkSphereSource(); src.SetRadius(12 * z); src.SetCenter(x * z, F - z * F, 0); src.SetThetaResolution(48); src.SetPhiResolution(48); src.Update()
            m = slicer.modules.models.logic().AddModel(src.GetOutput()); m.GetDisplayNode().SetColor(1, 0.85, 0.2); m.GetDisplayNode().SetEdgeVisibility(True)
        vn = lg.threeDWidget().mrmlViewNode(); vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
        cam = lg.referenceCamera(); cam.SetPosition(0, F, 0); cam.SetFocalPoint(0, 0, 0); cam.SetViewUp(0, 0, 1)
        lg.autoScreenPlane = False
        lg.start()
        cam.SetPosition(0, F, 0); cam.SetFocalPoint(0, 0, 0); cam.SetViewUp(0, 0, 1)
        log("started", lg.active, json.dumps(lg.rig["json"]))
        qt.QTimer.singleShot(8000, step2)
    except Exception: log(traceback.format_exc())
def step2():
    try:
        K = lg.parallaxAtInfinity()
        log("K", K, "viewRect", lg.viewRectPx(), "hosted", dxr.window_rect(lg.hostedHwnd) if lg.hostedHwnd else None)
        for z, x in zip(Z, X): log("sphere z/f", z, "x", x * z, "predicted %", round(100 * K * (1 - 1 / z), 4))
        open(dxr.atlas_paths("SlicerApp-real", True)[0], "w").close()
        qt.QTimer.singleShot(3000, lambda: (lg.stop(), slicer.app.exit(0)))
    except Exception: log(traceback.format_exc())
qt.QTimer.singleShot(1500, step1)
