"""Seated check helper: load the CT chest and start 3D in Slicer's own 3D view,
then leave Slicer running for the person at the panel. Writes tests/seated.out.txt
every 10 s (rate, drawn frames, texture state, depth)."""
import os, time
import slicer, qt
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "seated.out.txt"); open(OUT, "w").close()
def log(*a):
    with open(OUT, "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
import DisplayXR as D
lg = D.DisplayXRLogic.instance()
last = [0, time.time()]
def go():
    mw = slicer.util.mainWindow(); mw.showMaximized(); mw.raise_(); mw.activateWindow()
    lg.medicalLayout(); lg.loadSample("CTChest", "CT-Chest-Contrast-Enhanced"); slicer.util.selectModule("DisplayXR")
    qt.QTimer.singleShot(1500, start)
def start():
    lg.start(); log("start", lg.active, repr(lg.error), "texture mode", lg.vp is not None)
def report():
    vp = lg.vp
    if vp is None:
        log("3D off", repr(lg.error)); return
    now = time.time(); rate = (vp.pairs - last[0]) / (now - last[1]); last[0], last[1] = vp.pairs, now
    d = vp.depth()
    log("%s | pairs/s %.1f drawn %d state 0x%x | depth %.0f %% front %.3f %% behind %.3f %% | %s" % (
        lg.statusText(), rate, vp.drawn(), vp.texture_state() or 0, d.strength * 100, d.front_pct, d.behind_pct, vp.gl_info()))
qt.QTimer.singleShot(1000, go)
t = qt.QTimer(); t.setInterval(10000); t.timeout.connect(report); t.start()
