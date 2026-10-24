# Runtime mouse pass-through: posted drag on the 3D window must rotate Slicer's camera.
import os, time, traceback, ctypes, ctypes.wintypes as wt
import slicer, qt
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "passthrough.out.txt"); open(OUT, "w").close()
def log(*a):
    with open(OUT, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D, displayxr_coupling as dxr
lg = D.DisplayXRLogic.instance(); u32 = ctypes.windll.user32
u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
u32.WindowFromPoint.argtypes = [wt.POINT]; u32.WindowFromPoint.restype = wt.HWND
def s1():
    mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow()
    lg.medicalLayout(); lg.loadSample("CTChest", "CT-Chest-Contrast-Enhanced"); lg.start(); log("start", lg.active, lg.error)
    qt.QTimer.singleShot(9000, s2)
def s2():
    try:
        h = lg.hostedHwnd; ex = u32.GetWindowLongPtrW(h, -20)
        log("hosted", h, "exstyle", hex(ex), "runtime passes input", dxr.runtime_passes_input(h))
        x, y, w, hh = dxr.window_rect(h); log("hit at centre", u32.WindowFromPoint(wt.POINT(x + w // 2, y + hh // 2)), "== hosted?", u32.WindowFromPoint(wt.POINT(x + w // 2, y + hh // 2)) == h)
        cam = lg.referenceCamera(); before = cam.GetPosition()
        cx, cy = w // 2, hh // 2
        L = lambda px, py: (py << 16) | (px & 0xFFFF)
        u32.PostMessageW(h, 0x0201, 1, L(cx, cy))                 # LBUTTONDOWN
        for i in range(1, 21):
            u32.PostMessageW(h, 0x0200, 1, L(cx + 20 * i, cy))    # MOUSEMOVE
        u32.PostMessageW(h, 0x0202, 0, L(cx + 400, cy))           # LBUTTONUP
        def after():
            a = cam.GetPosition(); log("camera before", [round(v, 1) for v in before], "after", [round(v, 1) for v in a], "moved", any(abs(p - q) > 1 for p, q in zip(a, before)))
            lg.stop(); slicer.app.exit(0)
        qt.QTimer.singleShot(2500, after)
    except Exception: log(traceback.format_exc())
qt.QTimer.singleShot(1500, s1)
