"""F11 / Esc / Full panel button (texture mode), with real keystrokes
(keybd_event, so Qt's shortcut map sees them as a user's would). Checks:
F11 does nothing before 3D; while 3D is active F11 toggles Full panel (Slicer's
3D view alone, full screen, the weave follows the view) and Esc leaves it;
Esc during a markups placement cancels the placement and stays in Full panel;
an action already bound to F11 loses the key while 3D runs and gets it back on
stop, without firing; Stop in Full panel restores the layout; F11 after Stop
does nothing. Writes tests/f11.out.txt. Run with DXR_PLUGIN_EXCLUSIVE=sim-display."""
import ctypes, os, time, traceback
import slicer, qt
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "f11.out.txt"); open(OUT, "w").close()
fails = []
def log(*a):
    with open(OUT, "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
def check(name, ok, detail=""):
    log("ok  " if ok else "FAIL", name, detail)
    if not ok: fails.append(name)
import DisplayXR as D
lg = D.DisplayXRLogic.instance()
mw = slicer.util.mainWindow()
lm = slicer.app.layoutManager()
u32 = ctypes.windll.user32
VK = {"F11": 0x7A, "Esc": 0x1B}
other = {"fired": 0}
dummy = qt.QAction("Someone else's F11", mw)
dummy.setShortcut(qt.QKeySequence("F11"))
dummy.setShortcutContext(qt.Qt.ApplicationShortcut)
dummy.connect("triggered()", lambda: other.__setitem__("fired", other["fired"] + 1))
mw.addAction(dummy)

def key(name):
    hwnd = int(mw.winId())
    u32.SetForegroundWindow(hwnd)
    slicer.app.processEvents()
    vk = VK[name]
    u32.keybd_event(vk, 0, 0, 0); u32.keybd_event(vk, 0, 2, 0)
    for _ in range(20):
        slicer.app.processEvents(); time.sleep(0.02)

def state():
    return dict(full=lg._fullPanel is not None, fs=mw.isFullScreen(), layout=lm.layout,
                text=slicer.modules.DisplayXRWidget.fullButton.text if hasattr(slicer.modules, "DisplayXRWidget") else None)

base = {}
steps = []
def step(fn):
    steps.append(fn); return fn

@step
def s_before():
    mw.showMaximized(); mw.raise_(); mw.activateWindow()
    lg.medicalLayout(); lg.loadSample("CTChest", "CT-Chest-Contrast-Enhanced"); slicer.util.selectModule("DisplayXR")
    slicer.app.processEvents()
    base.update(layout=lm.layout)
    import re
    tip = re.sub("<[^>]+>", "", slicer.modules.DisplayXRWidget.fullButton.toolTip)  # Slicer stores tooltips as rich text
    check("button tooltip", tip == "Fullscreen (F11)", repr(tip))
    key("F11")
    s = state()
    check("F11 before 3D: Slicer's own action, no Full panel", not s["full"] and other["fired"] == 1, "%s fired=%d" % (s, other["fired"]))
    if mw.isFullScreen(): mw.showNormal(); mw.showMaximized()

@step
def s_start():
    lg.start()
    check("3D started (texture mode)", lg.active and lg.vp is not None, repr(lg.error))
    ks = [k.toString() for k in dummy.shortcuts()]
    check("other F11 action loses the key while 3D runs", "F11" not in ks, ks)

@step
def s_f11_on():
    other["fired"] = 0
    key("F11")
    s = state()
    check("F11 -> Full panel", s["full"] and s["fs"] and s["layout"] == slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView, s)
    check("button reads Exit full panel", s["text"] == "Exit full panel", s["text"])
    check("other F11 action not fired", other["fired"] == 0)

@step
def s_weave_follows():
    vp = lg.vp
    check("weave target = the full-screen 3D view", vp.target == tuple(lg.viewRectPx()) and vp.drawn() > 0,
          "target %s view %s drawn %s" % (vp.target, lg.viewRectPx(), vp.drawn()))
    scr = mw.screen().geometry; dpr = mw.devicePixelRatioF()
    full = (0, 0, round(scr.width() * dpr), round(scr.height() * dpr))
    check("the 3D view fills the screen", tuple(lg.viewRectPx()) == full, "view %s screen %s" % (lg.viewRectPx(), full))

@step
def s_esc_place():
    inode = slicer.app.applicationLogic().GetInteractionNode()
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLMarkupsFiducialNode")
    sel = slicer.app.applicationLogic().GetSelectionNode()
    sel.SetReferenceActivePlaceNodeClassName("vtkMRMLMarkupsFiducialNode"); sel.SetActivePlaceNodeID(node.GetID())
    inode.SetCurrentInteractionMode(inode.Place)
    key("Esc")
    check("Esc while placing: placement cancelled, still Full panel",
          inode.GetCurrentInteractionMode() == inode.ViewTransform and state()["full"], state())
    slicer.mrmlScene.RemoveNode(node)

@step
def s_esc_off():
    key("Esc")
    s = state()
    check("Esc -> leaves Full panel, layout back", not s["full"] and not s["fs"] and s["layout"] == base["layout"], s)
    panel = mw.findChild(qt.QDockWidget, "PanelDockWidget")
    check("module panel, menu and toolbars back", panel.isVisible() and mw.menuBar().isVisible()
          and any(tb.isVisible() for tb in mw.findChildren(qt.QToolBar)))
    check("button reads Full panel", s["text"] == "Full panel", s["text"])

@step
def s_f11_twice():
    key("F11"); a = state()
    key("F11"); b = state()
    check("F11 on, F11 off", a["full"] and not b["full"] and b["layout"] == base["layout"], "%s -> %s" % (a, b))

@step
def s_stop_in_full():
    key("F11")
    lg.stop(); slicer.app.processEvents()
    s = state()
    check("Stop in Full panel restores the layout", not lg.active and not s["full"] and not s["fs"] and s["layout"] == base["layout"], s)
    ks = [k.toString() for k in dummy.shortcuts()]
    check("other F11 action gets its key back", "F11" in ks, ks)

@step
def s_after():
    other["fired"] = 0
    key("F11")
    s = state()
    check("F11 after Stop: Slicer's own again, no Full panel", not s["full"] and other["fired"] == 1, "%s fired=%d" % (s, other["fired"]))
    log("RESULT", "PASS" if not fails else "FAIL %s" % fails)
    slicer.app.exit(0 if not fails else 1)

def run(i=0):
    try:
        steps[i]()
    except Exception:
        log(traceback.format_exc()); fails.append(steps[i].__name__)
    if i + 1 < len(steps):
        qt.QTimer.singleShot(6000 if steps[i] is s_start else 1500, lambda: run(i + 1))
qt.QTimer.singleShot(1500, run)
