import os, time, json, traceback, ctypes, ctypes.wintypes as wt
import slicer, qt, vtk
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "functional.out.txt"); open(OUT, "w").close()
def log(*a):
    with open(OUT, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D, displayxr_coupling as dxr
lg = D.DisplayXRLogic.instance(); u32 = ctypes.windll.user32
u32.WindowFromPoint.argtypes = [wt.POINT]; u32.WindowFromPoint.restype = wt.HWND
def cls(h):
    b = ctypes.create_unicode_buffer(64); u32.GetClassNameW(h, b, 64); return b.value
seq = []
def at(ms, fn): seq.append((ms, fn))
def s_start():
    mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow()
    lg.medicalLayout(); lg.loadSample("CTChest", "CT-Chest-Contrast-Enhanced"); slicer.util.selectModule("DisplayXR")
    lg.start(); log("start1", lg.active, lg.error)
def s_hit():
    x, y, w, h = dxr.window_rect(lg.hostedHwnd); hit = u32.WindowFromPoint(wt.POINT(x + w // 2, y + h // 2))
    view = lg.threeDWidget().threeDView()
    log("hit", hit, cls(hit), "hosted", lg.hostedHwnd, "fg", u32.GetForegroundWindow(), "main", lg.mainHwnd(), "clickThrough", lg.clickThrough)
def s_rotate():
    before = lg.lastDepth
    lg.threeDWidget().threeDView().yaw() if hasattr(lg.threeDWidget().threeDView(), "yaw") else None
    cam = lg.referenceCamera(); cam.Azimuth(60); cam.Elevation(25); cam.OrthogonalizeViewUp()
    slicer.app.processEvents()
    m = vtk.vtkMatrix4x4(); slicer.modules.virtualreality.viewWidget().renderWindow().GetPhysicalToWorldMatrix(m)
    log("rotated; depth before", before, "after", lg.lastDepth, "P2W row0", [round(m.GetElement(0, j), 3) for j in range(4)])
    open(dxr.atlas_paths("SlicerApp-real", True)[0], "w").close()
def s_zoom():
    cam = lg.referenceCamera(); cam.Dolly(2.5); slicer.app.processEvents(); lg.syncCamera()
    log("zoomed in 2.5x; depth", lg.lastDepth, "|", lg.depthText().replace("\n", " | "))
def s_f11():
    dxr.post_f11(lg.hostedHwnd)
def s_f11check():
    log("after F11 fullscreen?", dxr.is_panel_fullscreen(lg.hostedHwnd), dxr.window_rect(lg.hostedHwnd), "K", lg.parallaxAtInfinity())
    dxr.post_f11(lg.hostedHwnd)
def s_f11back():
    log("after 2nd F11 fullscreen?", dxr.is_panel_fullscreen(lg.hostedHwnd), dxr.window_rect(lg.hostedHwnd))
def s_stop():
    lg.stop(); log("stopped", lg.active, "viewAngle", lg.referenceCamera().GetViewAngle(), "hosted win", dxr.find_hosted_window())
def s_restart():
    lg.start(); log("start2", lg.active, lg.error)
def s_check2():
    log("after restart hosted", lg.hostedHwnd, lg.statusText(), "depth", lg.lastDepth)
    lg.stop(); slicer.app.exit(0)
at(1500, s_start); at(11000, s_hit); at(12000, s_rotate); at(15000, s_zoom); at(17000, s_f11); at(20000, s_f11check); at(23000, s_f11back)
at(25000, s_stop); at(30000, s_restart); at(40000, s_check2)
def wrap(fn):
    def f():
        try: fn()
        except Exception: log(fn.__name__, traceback.format_exc())
    return f
for ms, fn in seq: qt.QTimer.singleShot(ms, wrap(fn))
