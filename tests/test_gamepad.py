"""Gamepad navigation while 3D is active, with a fake pad (no hardware):
orbit / pan / zoom move Slicer's camera, the 3D (P2W) follows, A resets.
Writes tests/gamepad.out.txt."""
import os, time, math
import slicer, qt, vtk
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "gamepad.out.txt"); open(OUT, "w").close()
def log(*a):
    with open(OUT, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D, displayxr_gamepad as gp
lg = D.DisplayXRLogic.instance()
IDLE = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "lt": 0.0, "rt": 0.0, "buttons": 0}
def p2w():
    m = vtk.vtkMatrix4x4(); slicer.modules.virtualreality.viewWidget().renderWindow().GetPhysicalToWorldMatrix(m)
    return [round(m.GetElement(i, 3), 1) for i in range(3)]
def cam():
    c = lg.referenceCamera()
    return [round(v, 1) for v in c.GetPosition()], [round(v, 1) for v in c.GetFocalPoint()], round(c.GetDistance(), 1)
def pad(**kw):
    # the module's own copy of displayxr_gamepad (Slicer may import it twice)
    type(lg._pad).update.__globals__["fake"] = dict(IDLE, **kw)
def s_start():
    mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow()
    lg.medicalLayout(); lg.loadSample("CTChest", "CT-Chest-Contrast-Enhanced"); slicer.util.selectModule("DisplayXR")
    lg.start()
    log("start", lg.active, lg.error, "env nav", os.environ.get("DXR_INPUT_GAMEPAD_NAV"),
        "emulate", os.environ.get("DXR_INPUT_GAMEPAD_EMULATE_CONTROLLERS"), "xinput", gp._xinput is not None)
def s_base():
    log("base cam", cam(), "p2w", p2w()); pad()
def s_orbit():
    log("idle pad cam", cam()); pad(lx=1.0)
def s_pan():
    log("after 1 s left stick right: cam", cam(), "p2w", p2w()); pad(ry=1.0)
def s_zoom():
    log("after 1 s right stick up: cam", cam(), "p2w", p2w()); pad(rt=1.0)
def s_reset():
    log("after 1 s right trigger: cam", cam(), "p2w", p2w(), "depth", lg.lastDepth); pad(buttons=gp.BUTTON_A)
def s_probe():
    v = lg.threeDWidget().threeDView()
    log("has resetCamera", hasattr(v, "resetCamera"), "doc", getattr(getattr(v, "resetCamera", None), "__doc__", None))
    try:
        lg._pad._reset(); log("direct reset ok", cam())
    except Exception:
        import traceback; log("reset error", traceback.format_exc())
def s_after():
    log("after A: cam", cam(), "p2w", p2w()); type(lg._pad).update.__globals__["fake"] = None
def s_stop():
    log("real pad read:", gp.read()); lg.stop(); log("stopped", lg.active, "pad timer", lg._padTimer.isActive()); slicer.app.exit(0)
for ms, fn in [(1000, s_start), (9000, s_base), (10000, s_orbit), (11000, s_pan), (12000, s_zoom),
               (13000, s_reset), (14000, s_after), (14500, s_probe), (15500, s_stop)]:
    qt.QTimer.singleShot(ms, fn)
