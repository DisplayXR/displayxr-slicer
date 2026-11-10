"""DisplayXR 3D: glasses-free 3D of Slicer's 3D view on DisplayXR displays
(tested on Leia SR).

How it works
------------
Default (texture mode, the in-viewport target; runtime v2.55+, needs bin/ from
native/build.bat): Slicer renders two off-axis eyes with its own renderer and
the woven frame is drawn back into its own 3D view (displayxr_viewport.py).
Nothing covers Slicer. The rest of this docstring describes the fallback
(DXR_SLICER_MODE=overlay, or when bin/ is missing), kept as a measurement rig:

SlicerVirtualReality renders the scene through OpenXR (VTK vtkOpenXRRenderWindow).
DisplayXR runs it as a hosted *legacy* app and, with DXR_HOSTED_WINDOW=auto,
embeds its woven 3D window over Slicer's main window. This module:

* sets a camera rig that matches the panel's true geometry (glass at the
  display's nominal viewing distance, vertical FOV of the 3D view's physical
  height), so
  virtual metres map 1:1 onto the panel and parallax is predictable;
* publishes the 3D view's rect (DXR_HostedViewRect), so the 3D sits exactly
  in Slicer's 3D view at any layout or size;
* makes the 3D window click-through, so Slicer's normal mouse interaction in
  the 3D view keeps working, and drives the 3D from Slicer's 3D camera;
* places the screen plane (the glass) so the visible content stays inside the
  calibrated comfort budget, pushing the viewpoint back when it can't fit.
"""

import json
import logging
import math
import os
import sys
import time

import qt
import slicer
import vtk
from slicer.ScriptedLoadableModule import (ScriptedLoadableModule, ScriptedLoadableModuleLogic,
                                           ScriptedLoadableModuleWidget)

import displayxr_coupling as dxr
import displayxr_gamepad
import displayxr_viewport

#: Comfort budget on the Leia SR panel, as a fraction of view width
#: (calibrated by eye on the panel, 2026-10-23). Not in DisplayXR's display
#: info yet (runtime issue #2388), so it is a constant here; background on
#: per-display comfort limits:
#: https://github.com/DisplayXR/displayxr-runtime/discussions/2331#discussioncomment-19185165
BUDGET_FRONT = 0.0014
BUDGET_BEHIND = 0.0042

#: Parallax at infinity (fraction of view width) at Depth 100 %. It sets the
#: session's eye separation; the live Depth slider scales it through the
#: runtime (DXR_HostedDepth) and the Screen plane slider moves the glass.
K_COMFORTABLE = 0.012


class DisplayXR(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "DisplayXR 3D"
        parent.categories = ["DisplayXR"]
        parent.dependencies = []  # SlicerVirtualReality only for the overlay fallback
        parent.contributors = ["Joe Hill (DisplayXR contributors)"]
        parent.helpText = ("Shows Slicer's 3D view in glasses-free 3D on a DisplayXR display "
                           "(tested on Leia SR), inside the 3D view itself. Rotate, pan and zoom as usual.")
        parent.acknowledgementText = "Built on the DisplayXR runtime (texture target); the overlay fallback uses SlicerVirtualReality."


# ----------------------------------------------------------------------------
class DisplayXRWidget(ScriptedLoadableModuleWidget):
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self.logic = DisplayXRLogic.instance()
        lay = self.layout
        font = qt.QFont()
        font.setPointSize(11)

        self.status = qt.QLabel("3D ready")
        self.status.setStyleSheet("QLabel { font-size: 14pt; font-weight: bold; }")
        lay.addWidget(self.status)

        self.startButton = qt.QPushButton("Start 3D")
        self.startButton.setMinimumHeight(44)
        self.startButton.setStyleSheet("QPushButton { font-size: 12pt; }")
        self.startButton.clicked.connect(self.onStartStop)
        lay.addWidget(self.startButton)

        form = qt.QFormLayout()
        lay.addLayout(form)
        import ctk
        self.depthSlider = ctk.ctkSliderWidget()
        self.depthSlider.minimum, self.depthSlider.maximum = 5, 200
        self.depthSlider.singleStep = self.depthSlider.pageStep = 5
        self.depthSlider.decimals = 0
        self.depthSlider.suffix = " %"
        self.depthSlider.value = self.logic.depthPercent
        self.depthSlider.setToolTip("Strength of the 3D effect, live. 100 % stays inside the panel's\n"
                                    "low-ghosting range; more is stronger but ghosts more.")
        self.depthSlider.valueChanged.connect(self.logic.setDepthPercent)
        form.addRow("Depth:", self.depthSlider)
        steps = qt.QHBoxLayout()
        for label, delta in (("\u2212", -25), ("+", 25), ("Reset", None)):
            b = qt.QPushButton(label)
            b.setToolTip("Depth in 25 % steps; Reset = 100 %, the comfortable default")
            b.clicked.connect(lambda checked=False, d=delta: self.stepDepth(d))
            steps.addWidget(b)
        form.addRow("", steps)

        self.planeSlider = ctk.ctkSliderWidget()
        self.planeSlider.minimum, self.planeSlider.maximum = -50, 100
        self.planeSlider.singleStep = self.planeSlider.pageStep = 5
        self.planeSlider.decimals = 0
        self.planeSlider.suffix = " %"
        self.planeSlider.value = self.logic.planePercent
        self.planeSlider.setToolTip("Moves the screen plane, live. 0 = automatic.\n"
                                    "Higher: the screen plane moves farther away and more of the anatomy pops out.\n"
                                    "Lower: it moves nearer and the anatomy sits behind the screen.")
        self.planeSlider.valueChanged.connect(self.onPlane)
        form.addRow("Screen plane:", self.planeSlider)

        self.autoPlane = qt.QCheckBox("Keep depth comfortable")
        self.autoPlane.setChecked(self.logic.autoScreenPlane)
        self.autoPlane.setToolTip("On: the screen plane follows the content so its depth stays comfortable.\n"
                                  "Off: the 3D view's rotation centre sits on the screen plane.")
        self.autoPlane.toggled.connect(lambda on: setattr(self.logic, "autoScreenPlane", on))
        form.addRow(self.autoPlane)

        self.mouse = qt.QCheckBox("Mouse controls the 3D view")
        self.mouse.setChecked(self.logic.clickThrough)
        self.mouse.toggled.connect(self.logic.setClickThrough)
        form.addRow(self.mouse)

        self.depthLabel = qt.QLabel("")
        self.depthLabel.setWordWrap(True)
        self.depthLabel.setStyleSheet("QLabel { font-size: 11pt; }")
        lay.addWidget(self.depthLabel)

        row = qt.QHBoxLayout()
        lay.addLayout(row)
        self.fullButton = qt.QPushButton("Full screen (F11)")
        self.fullButton.setMinimumHeight(36)
        self.fullButton.setToolTip("Fullscreen (F11)")
        self.fullButton.clicked.connect(self.logic.toggleFullscreen)
        row.addWidget(self.fullButton)
        layoutButton = qt.QPushButton("Medical layout")
        layoutButton.setMinimumHeight(36)
        layoutButton.setToolTip("3D view on the left, axial / sagittal / coronal slices on the right")
        layoutButton.clicked.connect(self.logic.medicalLayout)
        row.addWidget(layoutButton)

        sampleButton = qt.QPushButton("Load sample: CT chest (volume rendering)")
        sampleButton.setMinimumHeight(36)
        sampleButton.clicked.connect(lambda: self.logic.loadSample("CTChest", "CT-Chest-Contrast-Enhanced"))
        lay.addWidget(sampleButton)

        import displayxr_monai
        if displayxr_monai.available():
            mon = qt.QGroupBox("MONAI (AI segmentation)")
            lay.addWidget(mon)
            ml = qt.QVBoxLayout(mon)
            monaiButton = qt.QPushButton("AI segment organs (MONAI Auto3DSeg)")
            monaiButton.setMinimumHeight(36)
            monaiButton.setToolTip("Segments the loaded CT with MONAI Auto3DSeg (" + displayxr_monai.DEFAULT_MODEL + ",\n"
                                   "local GPU inference) and shows the organs in 3D. Loads the CTLiver sample\n"
                                   "if no CT is loaded. 3D pauses while the model runs.")
            monaiButton.clicked.connect(self.onMonai)
            ml.addWidget(monaiButton)
            self.monaiLabel = qt.QLabel("")
            self.monaiLabel.setWordWrap(True)
            ml.addWidget(self.monaiLabel)

        omni = qt.QGroupBox("NVIDIA Omniverse")
        lay.addWidget(omni)
        ol = qt.QVBoxLayout(omni)
        boneButton = qt.QPushButton("Segment bone from CT (threshold)")
        boneButton.setMinimumHeight(36)
        boneButton.setToolTip("Quick segmentation of the loaded CT (> 200 HU), shown in 3D")
        boneButton.clicked.connect(self.onBone)
        ol.addWidget(boneButton)
        usdButton = qt.QPushButton("Send to Omniverse (USD)")
        usdButton.setMinimumHeight(36)
        usdButton.setToolTip("Writes the visible segments and models as a .usda file to open or\n"
                             "reference in USD Composer (Documents\\DisplayXR\\Slicer)")
        usdButton.clicked.connect(self.onUsd)
        ol.addWidget(usdButton)
        self.usdLabel = qt.QLabel("")
        self.usdLabel.setWordWrap(True)
        self.usdLabel.setTextInteractionFlags(qt.Qt.TextSelectableByMouse)
        ol.addWidget(self.usdLabel)

        lay.addStretch(1)
        self.logic.statusChanged = self.updateStatus
        self.logic.depthChanged = self.onDepthFromRuntime
        self.updateStatus()

    def onBone(self):
        try:
            self.logic.segmentBone()
        except Exception as e:
            slicer.util.errorDisplay(str(e))

    def onMonai(self):
        self.monaiLabel.setText("Segmenting with MONAI Auto3DSeg\u2026")
        slicer.app.processEvents()
        try:
            with slicer.util.tryWithErrorDisplay("MONAI segmentation failed", waitCursor=True):
                n, secs = self.logic.monaiSegment()
                self.monaiLabel.setText(f"{n} structures segmented in {secs:.0f} s; shown in 3D.")
        except Exception as e:
            self.monaiLabel.setText(str(e))

    def onUsd(self):
        import displayxr_usd
        try:
            path, meshes = displayxr_usd.export_scene()
            self.usdLabel.setText(f"Wrote {len(meshes)} mesh(es) to\n{path}")
        except Exception as e:
            self.usdLabel.setText(str(e))

    def stepDepth(self, delta):
        v = 100 if delta is None else min(max(self.depthSlider.value + delta, self.depthSlider.minimum),
                                          self.depthSlider.maximum)
        self.depthSlider.value = v

    def onDepthFromRuntime(self, percent):
        self.depthSlider.blockSignals(True)
        self.depthSlider.value = percent
        self.depthSlider.blockSignals(False)

    def onPlane(self, value):
        self.logic.planePercent = value
        self.logic.syncCamera()

    def onStartStop(self):
        if self.logic.active:
            self.logic.stop()
        else:
            self.logic.start()
        self.updateStatus()

    def updateStatus(self):
        lg = self.logic
        self.startButton.setText("Stop 3D" if lg.active else "Start 3D")
        self.fullButton.setEnabled(lg.active)
        if lg.vp is not None:
            self.fullButton.setText("Exit full panel" if lg._fullPanel is not None else "Full panel")
        else:
            self.fullButton.setText("Full screen (F11)")
        self.mouse.setVisible(lg.vp is None)
        self.status.setText(lg.statusText())
        self.depthLabel.setText(lg.depthText())

    def cleanup(self):
        self.logic.statusChanged = None


# ----------------------------------------------------------------------------
class DisplayXRLogic(ScriptedLoadableModuleLogic):
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = DisplayXRLogic()
        return cls._instance

    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.active = False
        self.error = ""
        self.depthPercent = 100.0  # live Depth slider, % of K_COMFORTABLE
        self.planePercent = 0.0    # live Screen plane slider: glass distance +/- %
        self._sentDepth = None
        self._lastNow = None
        self.depthChanged = None   # widget hook: depth changed outside the panel
        self.autoScreenPlane = True
        self.clickThrough = True
        self.statusChanged = None
        self.hostedHwnd = None
        self.rig = None            # rig used by the running session
        self.lastDepth = None      # (front, behind, pushed_back_mm, glass_mm) of the last update
        self._saved = {}
        self._cameraObs = None
        self._timer = qt.QTimer()
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        # Gamepad navigation of Slicer's own camera, at display rate (see displayxr_gamepad)
        self._padTimer = qt.QTimer()
        self._padTimer.setInterval(16)
        self._padTimer.timeout.connect(self._padTick)
        self._pad = None
        self._padLast = 0.0
        # Texture mode (default): see displayxr_viewport
        self.vp = None
        self._vpTimer = qt.QTimer()
        self._vpTimer.setInterval(16)
        self._vpTimer.timeout.connect(self._vpTick)
        self._vpChecks = 0
        self._fullPanel = None
        self._keys = None          # (F11, Esc) QShortcuts while 3D is active
        self._takenF11 = []        # (QAction, shortcuts) whose F11 we took over

    # -- status ----------------------------------------------------------
    def statusText(self):
        if self.error:
            return "3D unavailable: " + self.error
        if not self.active:
            return "3D ready"
        if self.vp is not None:
            return "3D active" if self.vp.drawn() > 0 else "3D starting\u2026"
        if self.hostedHwnd is None:
            return "3D starting…"
        return "3D active"

    def depthText(self):
        if not self.active or not self.lastDepth:
            return f"Depth {self.depthPercent:.0f} %. Start 3D to see the depth of the current view."
        front, behind, pushed, glass = self.lastDepth
        ok = -front <= BUDGET_FRONT * 1.05 and behind <= BUDGET_BEHIND * 1.05
        txt = (f"In front of the screen: {-front * 100:.2f} %   Behind: {behind * 100:.2f} %\n"
               f"{'Comfortable' if ok else 'Strong'} depth · screen plane {glass:.0f} mm from the camera")
        if pushed > 0.5:
            txt += f"\nViewpoint moved back {pushed:.0f} mm to keep the depth comfortable"
        if self.vp is not None:
            return txt
        now = dxr.read_hosted_depth_now(self.mainHwnd())
        if now and abs(now[1] / self.rig["convergence"] - 1) > 0.02:
            txt += "\nFocus was changed by another depth control: the numbers above are approximate"
        return txt

    def _notify(self):
        if self.statusChanged:
            try:
                self.statusChanged()
            except Exception:
                pass

    # -- Slicer views ----------------------------------------------------
    def threeDWidget(self):
        """The 3D view on screen: the largest visible one (index 0 can be a
        hidden view left over from another layout or module)."""
        lm = slicer.app.layoutManager()
        if not lm or lm.threeDViewCount == 0:
            return None
        widgets = [lm.threeDWidget(i) for i in range(lm.threeDViewCount)]
        shown = [w for w in widgets if w.isVisible() and w.threeDView().isVisible()]
        if not shown:
            return widgets[0]
        return max(shown, key=lambda w: w.threeDView().width * w.threeDView().height)

    def referenceCamera(self):
        w = self.threeDWidget()
        return w.threeDView().cameraNode().GetCamera() if w else None

    def mainHwnd(self):
        return int(slicer.util.mainWindow().winId())

    def viewRectPx(self):
        """3D view rect in the main window's client area, physical px."""
        mw = slicer.util.mainWindow()
        view = self.threeDWidget().threeDView()
        tl = view.mapTo(mw, qt.QPoint(0, 0))
        dpr = view.devicePixelRatioF()
        return (round(tl.x() * dpr), round(tl.y() * dpr), round(view.width * dpr), round(view.height * dpr))

    def _startSharedSlider(self):
        """The shared DisplayXR depth slider (Depth / Focus for every app,
        vendored in tools/), docked in a reserved corner of Slicer's menu bar
        while 3D is on. Runs under the user's PowerShell execution policy; if
        it can't run, 3D carries on without it (the module's sliders work)."""
        script = dxr.shared_depth_slider_script()
        if not script or getattr(self, "_sliderProc", None) is not None:
            return
        import subprocess
        args = ["pwsh", "-NoProfile", "-WindowStyle", "Hidden", "-File", script,
                "-Process", "SlicerApp-real", "-RightGap", "20", "-Top", "0", "-Height", "52"]
        if dxr.shared_depth_slider_takes_pid(script):
            args += ["-ProcessId", str(os.getpid())]
        try:
            self._sliderProc = subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.reserveDepthSliderSpace()
            qt.QTimer.singleShot(3000, self._checkSharedSlider)
        except OSError:
            self._sliderProc = None
            logging.warning("DisplayXR: depth slider not started (PowerShell 7 'pwsh' not found); "
                            "continuing without it.")

    def _checkSharedSlider(self):
        """Log once and drop the slider's space if it exited right away (e.g. the
        execution policy refused the script)."""
        proc = getattr(self, "_sliderProc", None)
        if proc is None or proc.poll() is None:
            return
        script = dxr.shared_depth_slider_script() or ""
        hint = ""
        if os.path.exists(script + ":Zone.Identifier"):
            hint = " The script is marked as downloaded; run Unblock-File on it."
        logging.warning("DisplayXR: depth slider %s exited (code %s), likely blocked by the PowerShell "
                        "execution policy; continuing without it.%s", script, proc.returncode, hint)
        self._stopSharedSlider()

    def _stopSharedSlider(self):
        proc = getattr(self, "_sliderProc", None)
        if proc is not None:
            proc.terminate()
            self._sliderProc = None
        spacer = getattr(self, "_sliderSpacer", None)
        if spacer is not None:
            spacer.hide()
            slicer.util.mainWindow().menuBar().setMinimumHeight(0)

    def reserveDepthSliderSpace(self, width_px=1340, height_px=52):
        """The shared DisplayXR depth slider (started by the launcher) docks at
        the top right of Slicer's client area; reserve that corner of the menu
        bar so the slider covers empty space, not Slicer's toolbar."""
        mw = slicer.util.mainWindow()
        if mw is None or (getattr(self, "_sliderSpacer", None) is not None and self._sliderSpacer.visible):
            return
        dpr = mw.devicePixelRatioF()
        spacer = qt.QWidget()
        spacer.setFixedSize(round(width_px / dpr), round(height_px / dpr))
        mw.menuBar().setCornerWidget(spacer, qt.Qt.TopRightCorner)
        spacer.show()
        # QMenuBar sizes to its menus, not to a fixed-size corner widget
        mw.menuBar().setMinimumHeight(round(height_px / dpr))
        self._sliderSpacer = spacer

    def medicalLayout(self):
        slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalWidescreenView)

    def loadSample(self, name, preset):
        import SampleData
        vol = SampleData.downloadSample(name)
        vrl = slicer.modules.volumerendering.logic()
        disp = vrl.CreateDefaultVolumeRenderingNodes(vol)
        disp.GetVolumePropertyNode().Copy(vrl.GetPresetByName(preset))
        disp.SetVisibility(True)
        if slicer.app.layoutManager():
            slicer.util.resetThreeDViews()

    def monaiSegment(self, sample=None):
        """MONAI Auto3DSeg on the latest CT (or `sample`), shown in 3D. 3D is
        paused during inference (one heavy GPU job at a time) and resumed after.
        Returns (number of segments, inference seconds)."""
        import displayxr_monai
        vols = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        if sample or not vols:
            import SampleData
            vol = SampleData.downloadSample(sample or displayxr_monai.DEFAULT_SAMPLE)
        else:
            vol = vols[-1]
        was3D = self.active
        if was3D:
            self.stop()
        try:
            seg, secs = displayxr_monai.segment(vol)
            n = displayxr_monai.show_in_3d(seg)
            displayxr_monai.show_credits(sample or (displayxr_monai.DEFAULT_SAMPLE if not vols else None))
        finally:
            if was3D:
                self.start()
        return n, secs

    def segmentBone(self, threshold=200.0, name="Bone"):
        """Threshold the (first) loaded scalar volume into a smoothed segment."""
        vols = slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        if not vols:
            raise RuntimeError("Load a CT volume first.")
        vol = vols[-1]
        import numpy as np
        arr = slicer.util.arrayFromVolume(vol)
        seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", f"{vol.GetName()} segmentation")
        seg.CreateDefaultDisplayNodes()
        seg.SetReferenceImageGeometryParameterFromVolumeNode(vol)
        sid = seg.GetSegmentation().AddEmptySegment(name, name, [0.95, 0.9, 0.8])
        slicer.util.updateSegmentBinaryLabelmapFromArray((arr > threshold).astype(np.uint8), seg, sid, vol)
        seg.GetSegmentation().SetConversionParameter("Smoothing factor", "0.5")
        seg.CreateClosedSurfaceRepresentation()
        # volume rendering would hide the surface; show the segment instead
        for d in slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode"):
            d.SetVisibility(False)
        return seg

    # -- rig -------------------------------------------------------------
    def _makeRig(self):
        pw_m, ph_m, pw_px, ph_px = dxr.panel_geometry()
        x, y, w, h = self.viewRectPx()
        m_per_px = pw_m / pw_px
        h_m = max(h, 1) * m_per_px
        w_m = max(w, 1) * m_per_px
        k = K_COMFORTABLE
        viewer_m = dxr.nominal_viewer_m()
        vfov = 2.0 * math.atan(h_m / 2.0 / viewer_m)
        rig = {
            "convergenceDiopters": 1.0 / viewer_m,
            "verticalFov": vfov,
            # eye separation so a point at infinity has parallax k of the view width
            "ipdFactor": k * w_m / dxr.IPD_M,
        }
        return {"json": rig, "vfov": vfov, "m_per_px": m_per_px,
                "convergence": viewer_m}

    def parallaxAtInfinity(self):
        """K: parallax (fraction of view width) of a point at infinity, for the
        current canvas. The rig maps the canvas 1:1 onto the panel, so the eye
        separation on screen is ipd * ipdFactor regardless of the FOV."""
        if not self.rig:
            return None
        w_px = self.viewRectPx()[2]
        if self.hostedHwnd and dxr.is_panel_fullscreen(self.hostedHwnd):
            w_px = dxr.window_rect(self.hostedHwnd)[2]
        w_m = max(w_px, 1) * self.rig["m_per_px"]
        return dxr.IPD_M * self.rig["json"]["ipdFactor"] / w_m

    # -- start / stop ----------------------------------------------------
    def textureMode(self):
        """In-viewport target unless DXR_SLICER_MODE=overlay or bin/ wasn't built."""
        return displayxr_viewport.available() and os.environ.get("DXR_SLICER_MODE", "viewport") != "overlay"

    def start(self):
        if self.active:
            return
        self.error = ""
        if self.threeDWidget() is None:
            self.medicalLayout()
            slicer.app.processEvents()
        if self.textureMode():
            self._startViewport()
            return
        self.rig = self._makeRig()
        os.environ[dxr.ENV_LEGACY_CAMERA_RIG] = json.dumps(self.rig["json"])
        os.environ.setdefault(dxr.ENV_HOSTED_WINDOW, "auto")
        # Runtimes that support it forward the mouse to Slicer themselves;
        # older ones ignore this and get the click-through fallback in _tick.
        os.environ.setdefault(dxr.ENV_HOSTED_INPUT, "app")
        # The pad drives Slicer's camera (displayxr_gamepad), not the runtime's fly camera.
        os.environ.setdefault(dxr.ENV_GAMEPAD_NAV, "0")
        os.environ.setdefault(dxr.ENV_GAMEPAD_EMULATE, "0")

        cam = self.referenceCamera()
        self._saved["viewAngle"] = cam.GetViewAngle()
        # Same vertical FOV as the 3D, so Slicer's framing, zoom and picking
        # match what the panel shows.
        cam.SetViewAngle(math.degrees(self.rig["vfov"]))

        vrlogic = slicer.modules.virtualreality.logic()
        vn = vrlogic.GetDefaultVirtualRealityViewNode()
        vn.SetXRBackend(dxr.openxr_backend())
        vn.SetControllerModelsVisible(False)
        vn.SetLighthouseModelsVisible(False)
        refNode = self.threeDWidget().mrmlViewNode()
        vn.SetAndObserveReferenceViewNodeID(refNode.GetID())
        vn.SetBackgroundColor(refNode.GetBackgroundColor())
        vn.SetBackgroundColor2(refNode.GetBackgroundColor2())
        vrlogic.SetVirtualRealityConnected(True)
        vrlogic.SetVirtualRealityActive(True)
        if not vrlogic.GetVirtualRealityConnected() or vn.GetError():
            self.error = vn.GetError() or "the DisplayXR runtime did not start"
            self._restore()
            self._notify()
            return
        self.active = True
        self.hostedHwnd = None
        self._installKeys()
        self._cameraObs = cam.AddObserver(vtk.vtkCommand.ModifiedEvent, lambda *a: self.syncCamera())
        self._timer.start()
        self._pad = displayxr_gamepad.Navigator(self.threeDWidget().threeDView())
        self._padLast = time.monotonic()
        self._padTimer.start()
        self._startSharedSlider()
        self._notify()

    def stop(self):
        if not self.active:
            return
        if self.vp is not None:
            self._stopViewport()
            return
        self.active = False
        self._removeKeys()
        self._stopSharedSlider()
        self._timer.stop()
        self._padTimer.stop()
        self._pad = None
        try:
            vrlogic = slicer.modules.virtualreality.logic()
            vrlogic.SetVirtualRealityActive(False)
            vrlogic.SetVirtualRealityConnected(False)
        except Exception:
            pass
        self._restore()
        self._notify()

    def _restore(self):
        cam = self.referenceCamera()
        if cam is not None and self._cameraObs is not None:
            cam.RemoveObserver(self._cameraObs)
        self._cameraObs = None
        if cam is not None and "viewAngle" in self._saved:
            cam.SetViewAngle(self._saved.pop("viewAngle"))
        try:
            dxr.clear_view_rect(self.mainHwnd())
            dxr.clear_hosted_depth(self.mainHwnd())
        except Exception:
            pass
        self._sentDepth = None
        self._lastNow = None
        self.hostedHwnd = None
        self.lastDepth = None

    # -- texture mode (in Slicer's own 3D view) ---------------------------
    def _startViewport(self):
        os.environ.setdefault(dxr.ENV_GAMEPAD_NAV, "0")
        os.environ.setdefault(dxr.ENV_GAMEPAD_EMULATE, "0")
        view = self.threeDWidget().threeDView()
        try:
            vp = displayxr_viewport.ViewportSession(view, self.mainHwnd(), self.viewRectPx)
            err = vp.start()
        except OSError as e:
            err = f"could not load the DisplayXR host core ({e})"
        if err:
            self.error = err
            self._notify()
            return
        self.vp = vp
        vp.set_depth(self.depthPercent / 100.0)
        self.active = True
        self._vpChecks = 0
        self._installKeys()
        self._vpTimer.start()
        self._pad = displayxr_gamepad.Navigator(view)
        self._padLast = time.monotonic()
        self._padTimer.start()
        self._notify()

    def _stopViewport(self):
        self.active = False
        self._vpTimer.stop()
        self._padTimer.stop()
        self._pad = None
        if self._fullPanel is not None:
            self.toggleFullscreen()
        self._removeKeys()
        vp, self.vp = self.vp, None
        try:
            vp.stop()
        except Exception:
            import traceback
            traceback.print_exc()
        self.lastDepth = None
        self._notify()

    def viewportGlass(self, cam, content):
        """Glass distance (mm from Slicer's camera): with "Keep depth comfortable",
        a quarter of the way into the visible content (the behind budget is 3x the
        front one), else the rotation centre; then the Screen plane slider."""
        g = cam.GetDistance()
        if content and self.autoScreenPlane:
            n, f = max(content[0], 1e-3 * g), content[1]
            if f > n:
                g = n + 0.25 * (f - n)
        return g * (1.0 + self.planePercent / 100.0)

    def _vpTick(self):
        vp = self.vp
        if vp is None:
            return
        try:
            cam = self.referenceCamera()
            content = vp.content_depth(cam)
            vp.set_camera(cam, self.viewportGlass(cam, content), content)
            vp.tick(cam)
            self._vpChecks += 1
            if self._vpChecks % 15 == 0:
                if not vp.running():
                    self.error = vp.status() or "the 3D session ended"
                    self._stopViewport()
                    return
                d = vp.depth()
                new = (-d.front_pct / 100.0, d.behind_pct / 100.0, 0.0, d.glass)
                if self.lastDepth != new or self._vpChecks <= 60:
                    self.lastDepth = new
                    self._notify()
        except Exception:
            import traceback
            traceback.print_exc()

    # -- per-tick: window + session state -------------------------------
    def _tick(self):
        try:
            vrlogic = slicer.modules.virtualreality.logic()
            if not vrlogic.GetVirtualRealityActive():
                # ended outside our UI (window closed, runtime error)
                self.stop()
                return
            if self.hostedHwnd is None:
                h = dxr.find_hosted_window()
                if h:
                    self.hostedHwnd = h
                    self._applyDepth()
                    self._notify()
            if self.hostedHwnd:
                dxr.publish_view_rect(self.mainHwnd(), *self.viewRectPx())
                self._followDepthNow()
                if not dxr.runtime_passes_input(self.hostedHwnd):
                    dxr.set_click_through(self.hostedHwnd, self.clickThrough)
            self.syncCamera()
        except Exception:
            import traceback
            traceback.print_exc()

    def _padTick(self):
        if self._pad is None:
            return
        now = time.monotonic()
        try:
            self._pad.update(now - self._padLast)
        except Exception:
            import traceback
            traceback.print_exc()
        self._padLast = now

    def _followDepthNow(self):
        """Another depth control (the shared DisplayXR depth slider) or the
        runtime's comfort clamp changed the strength: show it on our slider."""
        now = dxr.read_hosted_depth_now(self.mainHwnd())
        if not now or now == self._lastNow:
            return
        self._lastNow = now
        if self._sentDepth is not None and abs(now[0] - self._sentDepth) > 0.0015:
            self._sentDepth = now[0]
            self.depthPercent = round(now[0] * 100.0)
            if self.depthChanged:
                self.depthChanged(self.depthPercent)
            self._notify()

    def setDepthPercent(self, value):
        self.depthPercent = float(value)
        if self.vp is not None:
            self.vp.set_depth(self.depthPercent / 100.0)
        self._applyDepth()
        self._notify()

    def _applyDepth(self):
        """Live stereo strength through the runtime (DXR_HostedDepth): 1.0 is
        the rig Slicer seeded; 0 in the focus field leaves convergence alone."""
        if not self.active or not self.hostedHwnd or not self.rig:
            return
        strength = self.depthPercent / 100.0
        if strength != self._sentDepth:
            dxr.write_hosted_depth(self.mainHwnd(), strength, 0.0)
            self._sentDepth = strength

    def setClickThrough(self, on):
        self.clickThrough = on
        if self.hostedHwnd and not dxr.runtime_passes_input(self.hostedHwnd):
            dxr.set_click_through(self.hostedHwnd, on)

    def toggleFullscreen(self):
        if self.vp is not None:
            # Texture mode: the 3D is Slicer's own 3D view, so full panel = that
            # view alone filling the screen (no panels, toolbars, menu or view
            # controller); the target follows the view. F11 or Esc comes back.
            lm, mw = slicer.app.layoutManager(), slicer.util.mainWindow()
            if self._fullPanel is None:
                chrome = self._chromeWidgets()
                self._fullPanel = (lm.layout, mw.isFullScreen(), [(w, w.isVisible()) for w in chrome])
                lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
                slicer.app.processEvents()
                for w in self._chromeWidgets():
                    w.setVisible(False)
                mw.showFullScreen()
            else:
                layout, wasFull, chrome = self._fullPanel
                self._fullPanel = None
                lm.setLayout(layout)
                for w, vis in chrome:
                    try:
                        w.setVisible(vis)
                    except Exception:
                        pass  # gone with the layout
                if not wasFull:
                    mw.showNormal()
                    mw.showMaximized()
            if self._keys:
                self._keys[1].setEnabled(self._fullPanel is not None)
            self._notify()
            return
        if self.hostedHwnd:
            dxr.post_f11(self.hostedHwnd)

    def _chromeWidgets(self):
        """What Full panel hides: docks (module panel, Python console, ...),
        toolbars, menu and status bar, and the 3D view's controller bar."""
        mw = slicer.util.mainWindow()
        ws = list(mw.findChildren(qt.QDockWidget)) + list(mw.findChildren(qt.QToolBar))
        ws += [mw.menuBar(), mw.statusBar()]
        tdw = self.threeDWidget()
        if tdw is not None and tdw.threeDController() is not None:
            ws.append(tdw.threeDController())
        return [w for w in ws if w is not None]

    # -- F11 / Esc while 3D is active ------------------------------------
    def _installKeys(self):
        """F11 toggles Full panel and Esc leaves it, anywhere in Slicer, only while
        3D is active. An action of Slicer's (or an extension's) bound to F11 loses
        that key until 3D stops, then gets it back."""
        if self._keys is not None:
            return
        mw = slicer.util.mainWindow()
        self._takenF11 = []
        for a in mw.findChildren(qt.QAction):
            ks = list(a.shortcuts())
            if any(k.toString() == "F11" for k in ks):
                self._takenF11.append((a, ks))
                a.setShortcuts([k for k in ks if k.toString() != "F11"])
        f11 = qt.QShortcut(qt.QKeySequence("F11"), mw)
        f11.setContext(qt.Qt.ApplicationShortcut)
        f11.connect("activated()", self.toggleFullscreen)
        esc = qt.QShortcut(qt.QKeySequence("Esc"), mw)
        esc.setContext(qt.Qt.ApplicationShortcut)
        esc.connect("activated()", self._onEscape)
        esc.setEnabled(False)  # only while Full panel is on (texture mode)
        self._keys = (f11, esc)

    def _removeKeys(self):
        if self._keys is not None:
            for k in self._keys:
                k.setEnabled(False)
                k.setParent(None)
                k.deleteLater()
            self._keys = None
        for a, ks in self._takenF11:
            try:
                a.setShortcuts(ks)
            except Exception:
                pass
        self._takenF11 = []

    def _onEscape(self):
        """Esc in Full panel: a markups placement in progress is cancelled first
        (what Esc means to Slicer there), otherwise Full panel ends."""
        inode = slicer.app.applicationLogic().GetInteractionNode()
        if inode is not None and inode.GetCurrentInteractionMode() == inode.Place:
            inode.SetCurrentInteractionMode(inode.ViewTransform)
            return
        if self._fullPanel is not None:
            self.toggleFullscreen()

    # -- camera sync and screen plane ------------------------------------
    def _vrRenderWindow(self):
        vw = slicer.modules.virtualreality.viewWidget()
        return vw.renderWindow() if vw else None

    def _contentDepths(self, eye, dop):
        """Nearest/farthest visible content along the view direction (mm)."""
        rw = self._vrRenderWindow()
        ren = rw.GetRenderers().GetFirstRenderer() if rw else None
        b = [0.0] * 6
        if ren is None:
            return None
        ren.ComputeVisiblePropBounds(b)
        if b[0] > b[1]:
            return None
        ds = []
        for i in (0, 1):
            for j in (2, 3):
                for k in (4, 5):
                    p = (b[i], b[j], b[k])
                    ds.append(sum((p[n] - eye[n]) * dop[n] for n in range(3)))
        return min(ds), max(ds)

    def solveScreenPlane(self, focal, near, far, K):
        """Glass distance g and push-back b (world units) keeping the content's
        parallax K(1 - g/z) inside the comfort budget."""
        bf, bb = BUDGET_FRONT, BUDGET_BEHIND
        c = 1.0 + bf / K          # g <= c * near   (front limit)
        a = 1.0 - bb / K          # g >= a * far    (behind limit)
        near = max(near, 1e-3 * max(focal, 1.0))
        b = 0.0
        if a > 0 and a * far > c * near:
            b = (a * far - c * near) / (c - a)
        lo, hi = a * (far + b), c * (near + b)
        g = min(max(focal + b, lo), hi)
        return g, b

    def syncCamera(self):
        if not self.active or self.vp is not None:
            return
        rw = self._vrRenderWindow()
        cam = self.referenceCamera()
        if rw is None or cam is None:
            return
        pos = cam.GetPosition()
        dop = list(cam.GetDirectionOfProjection())
        up = list(cam.GetViewUp())
        focal = cam.GetDistance()
        right = [0.0] * 3
        vtk.vtkMath.Cross(dop, up, right)
        vtk.vtkMath.Normalize(right)
        vtk.vtkMath.Cross(right, dop, up)
        vtk.vtkMath.Normalize(up)

        g, b = focal, 0.0
        K = self.parallaxAtInfinity()
        depths = self._contentDepths(pos, dop)
        if depths and self.autoScreenPlane:
            g, b = self.solveScreenPlane(focal, depths[0], depths[1], K)
        g *= 1.0 + self.planePercent / 100.0
        eye = [pos[n] - b * dop[n] for n in range(3)]
        s = g / self.rig["convergence"]   # world units per physical metre

        # physical -> world: physical x,y,-z = right, up, dop; the rig's nominal
        # eye lands on the (pushed-back) Slicer camera, the glass at distance g.
        m = vtk.vtkMatrix4x4()
        axes = (right, up, [-d for d in dop])
        for r in range(3):
            for col in range(3):
                m.SetElement(r, col, s * axes[col][r])
        e = dxr.RIG_EYE
        for r in range(3):
            m.SetElement(r, 3, eye[r] - s * sum(axes[col][r] * e[col] for col in range(3)))
        rw.SetPhysicalToWorldMatrix(m)
        ren = rw.GetRenderers().GetFirstRenderer()
        if ren:
            ren.ResetCameraClippingRange()

        if depths:
            # A live depth control (shared slider via DXR_HostedDepth) changes
            # the runtime rig itself: ipdFactor scales all parallax, and the
            # convergence moves the glass (s is unchanged). The solver keeps
            # framing for the seeded rig; report what is actually on screen.
            k_now, g_now = K, g
            now = dxr.read_hosted_depth_now(self.mainHwnd())
            if now:
                k_now = K * now[0]
                g_now = g * now[1] / self.rig["convergence"]
            n, f = depths[0] + b, depths[1] + b
            front = k_now * (1.0 - g_now / max(n, 1e-6))
            behind = k_now * (1.0 - g_now / max(f, 1e-6))
            new = (front, behind, b, g_now)
            if self.lastDepth is None or any(abs(x - y) > 1e-4 * (1 + abs(y)) for x, y in zip(new, self.lastDepth)):
                self.lastDepth = new
                self._notify()
