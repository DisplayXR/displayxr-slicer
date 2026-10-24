# Live depth via DXR_HostedDepth (shared slider): atlas at seed, 2x strength, focus 0.9 m.
# Run with DXR_PLUGIN_EXCLUSIVE=sim-display (fixed eyes).
import os, time, shutil, traceback, ctypes, ctypes.wintypes as wt
import slicer, qt, vtk
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "test_live_depth.out.txt"); open(OUT, "w").close()
def log(*a):
    with open(OUT, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D, displayxr_coupling as dxr
lg = D.DisplayXRLogic.instance(); u32 = ctypes.windll.user32
u32.SetPropW.argtypes = [wt.HWND, wt.LPCWSTR, ctypes.c_void_p]
F = 1000.0; Z = [0.6, 0.8, 1.0, 1.4, 2.0]; X = [-150, -75, 0, 75, 150]
trig, atlas = dxr.atlas_paths("SlicerApp-real", True)
def capture(tag):
    if os.path.exists(atlas): os.remove(atlas)
    open(trig, "w").close()
    def keep():
        if os.path.exists(atlas): shutil.copy(atlas, os.path.join(os.environ["TEMP"], f"slicer_depth_{tag}.png")); log("captured", tag, lg.depthText().replace("\n", " | "))
        else: log("no atlas for", tag)
    qt.QTimer.singleShot(1500, keep)
def setdepth(strength, conv_m):
    v = int(strength * 1000) | (int(conv_m * 1000) << 16)
    u32.SetPropW(lg.mainHwnd(), dxr.HOSTED_DEPTH_PROP, ctypes.c_void_p(v)); log("set DXR_HostedDepth", strength, conv_m)
def s1():
    mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_()
    lg.medicalLayout(); slicer.app.processEvents()
    for z, x in zip(Z, X):
        src = vtk.vtkSphereSource(); src.SetRadius(12 * z); src.SetCenter(x * z, F - z * F, 0); src.SetThetaResolution(48); src.SetPhiResolution(48); src.Update()
        m = slicer.modules.models.logic().AddModel(src.GetOutput()); m.GetDisplayNode().SetColor(1, 0.85, 0.2)
    vn = lg.threeDWidget().mrmlViewNode(); vn.SetBoxVisible(False); vn.SetAxisLabelsVisible(False)
    lg.autoScreenPlane = False
    lg.start()
    cam = lg.referenceCamera(); cam.SetPosition(0, F, 0); cam.SetFocalPoint(0, 0, 0); cam.SetViewUp(0, 0, 1)
    log("seed ipdFactor", lg.rig["json"]["ipdFactor"], "now", dxr.read_hosted_depth_now(lg.mainHwnd()))
steps = [(1500, s1), (10000, lambda: (log("now", dxr.read_hosted_depth_now(lg.mainHwnd())), capture("seed"))),
         (13000, lambda: setdepth(2 * lg.rig["json"]["ipdFactor"], 0)), (14500, lambda: (log("now", dxr.read_hosted_depth_now(lg.mainHwnd())), capture("strength2x"))),
         (17500, lambda: setdepth(0, 0.9)), (19000, lambda: (log("now", dxr.read_hosted_depth_now(lg.mainHwnd())), capture("focus0.9"))),
         (22500, lambda: (lg.stop(), slicer.app.exit(0)))]
def wrap(fn):
    def f():
        try: fn()
        except Exception: log(traceback.format_exc())
    return f
for ms, fn in steps: qt.QTimer.singleShot(ms, wrap(fn))
