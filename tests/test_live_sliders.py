# Module's live sliders: atlas at Depth 100 %, Depth 200 %, Depth 100 % + Screen plane +50 %.
# Run with DXR_PLUGIN_EXCLUSIVE=sim-display (fixed eyes).
import os, time, shutil, traceback
import slicer, qt, vtk
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "test_live_sliders.out.txt"); open(OUT, "w").close()
def log(*a):
    with open(OUT, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D, displayxr_coupling as dxr
lg = D.DisplayXRLogic.instance()
F = 1000.0; Z = [0.6, 0.8, 1.0, 1.4, 2.0]; X = [-150, -75, 0, 75, 150]
trig, atlas = dxr.atlas_paths("SlicerApp-real", True)
def capture(tag):
    if os.path.exists(atlas): os.remove(atlas)
    open(trig, "w").close()
    def keep():
        if os.path.exists(atlas): shutil.copy(atlas, os.path.join(os.environ["TEMP"], f"slicer_slider_{tag}.png"))
        log("captured", tag, "now", dxr.read_hosted_depth_now(lg.mainHwnd()), "|", lg.depthText().replace("\n", " | "))
    qt.QTimer.singleShot(1500, keep)
def s1():
    mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_()
    lg.medicalLayout(); slicer.util.selectModule("DisplayXR"); slicer.app.processEvents()
    for z, x in zip(Z, X):
        src = vtk.vtkSphereSource(); src.SetRadius(12 * z); src.SetCenter(x * z, F - z * F, 0); src.SetThetaResolution(48); src.SetPhiResolution(48); src.Update()
        m = slicer.modules.models.logic().AddModel(src.GetOutput()); m.GetDisplayNode().SetColor(1, 0.85, 0.2)
    vn = lg.threeDWidget().mrmlViewNode(); vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
    lg.autoScreenPlane = False
    lg.start()
    cam = lg.referenceCamera(); cam.SetPosition(0, F, 0); cam.SetFocalPoint(0, 0, 0); cam.SetViewUp(0, 0, 1)
w = lambda: slicer.modules.DisplayXRWidget
steps = [(1500, s1), (10000, lambda: capture("d100")),
         (13000, lambda: setattr(w().depthSlider, "value", 200)), (15000, lambda: capture("d200")),
         (18000, lambda: (setattr(w().depthSlider, "value", 100), setattr(w().planeSlider, "value", 50))), (20000, lambda: capture("plane50")),
         (23000, lambda: (lg.stop(), log("after stop prop now", dxr.read_hosted_depth_now(lg.mainHwnd())), slicer.app.exit(0)))]
def wrap(fn):
    def f():
        try: fn()
        except Exception: log(traceback.format_exc())
    return f
for ms, fn in steps: qt.QTimer.singleShot(ms, wrap(fn))
