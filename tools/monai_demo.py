# The live segment, one command (Launch-Slicer-MONAI-3D.cmd):
# CT -> MONAI Auto3DSeg -> organs in 3D in Slicer's own 3D view -> Send to Omniverse (USD).
# Times each step to tools/monai_demo.out.txt and leaves Slicer running in 3D.
# DXR_DEMO_EXIT=<seconds>: quit that long after the export (tests).
import os, time
import slicer, qt
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monai_demo.out.txt")
open(OUT, "w").close()
def log(*a):
    with open(OUT, "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D
lg = D.DisplayXRLogic.instance()
T0 = time.time()
def step1():
    mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow()
    lg.medicalLayout(); slicer.util.selectModule("DisplayXR"); slicer.app.processEvents()
    import displayxr_monai
    t = time.time()
    n, secs = lg.monaiSegment(sample=displayxr_monai.DEFAULT_SAMPLE)
    log("CT %s loaded + MONAI Auto3DSeg (%s): %d structures, inference %.1f s, step %.1f s" % (
        displayxr_monai.DEFAULT_SAMPLE, displayxr_monai.DEFAULT_MODEL, n, secs, time.time() - t))
    qt.QTimer.singleShot(500, step2)
def step2():
    lm = slicer.app.layoutManager()
    log("3D views:", [(lm.threeDWidget(i).threeDView().mrmlViewNode().GetName(), lm.threeDWidget(i).isVisible(),
                       lm.threeDWidget(i).threeDView().width, lm.threeDWidget(i).threeDView().height)
                      for i in range(lm.threeDViewCount)], "-> using", lg.threeDWidget().threeDView().mrmlViewNode().GetName())
    lg.start(); log("Start 3D", lg.active, repr(lg.error), "texture mode", lg.vp is not None)
    qt.QTimer.singleShot(6000, step3)
def step3():
    import displayxr_usd
    vp = lg.vp
    if vp is not None:
        d = vp.depth()
        log("3D: %s, drawn %d, state 0x%x, depth %.0f %% front %.3f %% behind %.3f %% of panel width" % (
            lg.statusText(), vp.drawn(), vp.texture_state() or 0, d.strength * 100, d.front_pct, d.behind_pct))
        log("  render size", vp.render_size(), "target", vp.target, "pairs", vp.pairs, "serial", vp.serial,
            "running", vp.running(), "status", repr(vp.status()), "gl", repr(vp.gl_info()))
        cap = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "probe", "monai_eyes_sbs.png")
        os.makedirs(os.path.dirname(cap), exist_ok=True)
        log("eye capture", vp.save_eyes(cap), cap)
    t = time.time(); path, meshes = displayxr_usd.export_scene()
    log("Send to Omniverse: %d meshes -> %s (%.1f s)" % (len(meshes), path, time.time() - t))
    log("LIVE SEGMENT TOTAL %.1f s (load CT -> segment -> 3D -> USD)" % (time.time() - T0))
    ex = os.environ.get("DXR_DEMO_EXIT")
    if ex:
        qt.QTimer.singleShot(int(float(ex) * 1000), lambda: (lg.stop(), slicer.app.exit(0)))
qt.QTimer.singleShot(1000, step1)
