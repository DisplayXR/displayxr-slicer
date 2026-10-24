"""DisplayXR 3D: glasses-free 3D of Slicer's 3D view on DisplayXR displays
(tested on Leia SR).

How it works
------------
SlicerVirtualReality renders the scene through OpenXR (VTK vtkOpenXRRenderWindow).
DisplayXR runs it as a hosted *legacy* app and, with DXR_HOSTED_WINDOW=auto,
embeds its woven 3D window over Slicer's main window. This module:

* sets a camera rig that matches the panel's true geometry (glass at the
  nominal 0.6 m viewer, vertical FOV of the 3D view's physical height), so
  virtual metres map 1:1 onto the panel and parallax is predictable;
* publishes the 3D view's rect (DXR_HostedViewRect), so the 3D sits exactly
  in Slicer's 3D view at any layout or size;
* makes the 3D window click-through, so Slicer's normal mouse interaction in
  the 3D view keeps working, and drives the 3D from Slicer's 3D camera;
* places the screen plane (the glass) so the visible content stays inside the
  calibrated comfort budget, pushing the viewpoint back when it can't fit.
"""

import json
import math
import os
import sys

import qt
import slicer
import vtk
from slicer.ScriptedLoadableModule import (ScriptedLoadableModule, ScriptedLoadableModuleLogic,
                                           ScriptedLoadableModuleWidget)

import displayxr_coupling as dxr

#: Comfort budget on the Leia SR panel, as a fraction of view width
#: (calibrated with the user 2026-10-23; see displayxr-compat PLAYBOOK §3).
BUDGET_FRONT = 0.0014
BUDGET_BEHIND = 0.0042

#: "Depth" choices: (label, parallax at infinity K as a fraction of view
#: width, budget multiplier). K sets the eye separation for the session; the
#: multiplier scales the comfort budget the screen-plane solver aims for.
DEPTH_LEVELS = [
    ("Gentle", 0.008, 0.7),
    ("Comfortable", 0.012, 1.0),
    ("Strong", 0.020, 1.6),
]
DEFAULT_DEPTH = 1


class DisplayXR(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        parent.title = "DisplayXR 3D"
        parent.categories = ["DisplayXR"]
        parent.dependencies = ["VirtualReality"]
        parent.contributors = ["Joe Hill (Leia Inc.)"]
        parent.helpText = ("Shows Slicer's 3D view in glasses-free 3D on a DisplayXR display "
                           "(e.g. Leia SR), inside the 3D view itself. Rotate, pan and zoom as usual.")
        parent.acknowledgementText = "Built on SlicerVirtualReality (OpenXR) and the DisplayXR runtime."


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
        self.depthCombo = qt.QComboBox()
        for name, _, _ in DEPTH_LEVELS:
            self.depthCombo.addItem(name)
        self.depthCombo.setCurrentIndex(self.logic.depthLevel)
        self.depthCombo.currentIndexChanged.connect(self.onDepth)
        self.depthCombo.setToolTip("Strength of the 3D effect. Comfortable stays inside the panel's "
                                   "low-ghosting range. A change applies the next time 3D starts.")
        form.addRow("Depth:", self.depthCombo)

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
        self.updateStatus()

    def onBone(self):
        try:
            self.logic.segmentBone()
        except Exception as e:
            slicer.util.errorDisplay(str(e))

    def onUsd(self):
        import displayxr_usd
        try:
            path, meshes = displayxr_usd.export_scene()
            self.usdLabel.setText(f"Wrote {len(meshes)} mesh(es) to\n{path}")
        except Exception as e:
            self.usdLabel.setText(str(e))

    def onDepth(self, index):
        self.logic.depthLevel = index
        self.updateStatus()

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
        self.depthLevel = DEFAULT_DEPTH
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

    # -- status ----------------------------------------------------------
    def statusText(self):
        if self.error:
            return "3D unavailable: " + self.error
        if not self.active:
            return "3D ready"
        if self.hostedHwnd is None:
            return "3D starting…"
        return "3D active"

    def depthText(self):
        if not self.active or not self.lastDepth:
            name = DEPTH_LEVELS[self.depthLevel][0]
            return f"Depth: {name}. Start 3D to see the depth of the current view."
        front, behind, pushed, glass = self.lastDepth
        mult = DEPTH_LEVELS[self.rig["level"]][2]
        ok = -front <= BUDGET_FRONT * mult * 1.05 and behind <= BUDGET_BEHIND * mult * 1.05
        txt = (f"In front of the screen: {-front * 100:.2f} %   Behind: {behind * 100:.2f} %\n"
               f"{'Comfortable' if ok else 'Strong'} depth · screen plane {glass:.0f} mm from the camera")
        if pushed > 0.5:
            txt += f"\nViewpoint moved back {pushed:.0f} mm to keep the depth comfortable"
        if self.depthLevel != self.rig["level"]:
            txt += "\nNew depth setting applies when 3D restarts"
        return txt

    def _notify(self):
        if self.statusChanged:
            try:
                self.statusChanged()
            except Exception:
                pass

    # -- Slicer views ----------------------------------------------------
    def threeDWidget(self):
        lm = slicer.app.layoutManager()
        return lm.threeDWidget(0) if lm and lm.threeDViewCount > 0 else None

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
        name, k, mult = DEPTH_LEVELS[self.depthLevel]
        vfov = 2.0 * math.atan(h_m / 2.0 / dxr.NOMINAL_VIEWER_M)
        rig = {
            "convergenceDiopters": 1.0 / dxr.NOMINAL_VIEWER_M,
            "verticalFov": vfov,
            # eye separation so a point at infinity has parallax k of the view width
            "ipdFactor": k * w_m / dxr.IPD_M,
        }
        return {"json": rig, "level": self.depthLevel, "vfov": vfov, "m_per_px": m_per_px,
                "convergence": dxr.NOMINAL_VIEWER_M}

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
    def start(self):
        if self.active:
            return
        self.error = ""
        if self.threeDWidget() is None:
            self.medicalLayout()
            slicer.app.processEvents()
        self.rig = self._makeRig()
        os.environ[dxr.ENV_LEGACY_CAMERA_RIG] = json.dumps(self.rig["json"])
        os.environ.setdefault(dxr.ENV_HOSTED_WINDOW, "auto")

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
        self._cameraObs = cam.AddObserver(vtk.vtkCommand.ModifiedEvent, lambda *a: self.syncCamera())
        self._timer.start()
        self._notify()

    def stop(self):
        if not self.active:
            return
        self.active = False
        self._timer.stop()
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
        except Exception:
            pass
        self.hostedHwnd = None
        self.lastDepth = None

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
                    self._notify()
            if self.hostedHwnd:
                dxr.publish_view_rect(self.mainHwnd(), *self.viewRectPx())
                dxr.set_click_through(self.hostedHwnd, self.clickThrough)
            self.syncCamera()
        except Exception:
            import traceback
            traceback.print_exc()

    def setClickThrough(self, on):
        self.clickThrough = on
        if self.hostedHwnd:
            dxr.set_click_through(self.hostedHwnd, on)

    def toggleFullscreen(self):
        if self.hostedHwnd:
            dxr.post_f11(self.hostedHwnd)

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
        mult = DEPTH_LEVELS[self.rig["level"]][2]
        bf, bb = BUDGET_FRONT * mult, BUDGET_BEHIND * mult
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
        if not self.active:
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
            n, f = depths[0] + b, depths[1] + b
            front = K * (1.0 - g / max(n, 1e-6))
            behind = K * (1.0 - g / max(f, 1e-6))
            new = (front, behind, b, g)
            if self.lastDepth is None or any(abs(x - y) > 1e-4 * (1 + abs(y)) for x, y in zip(new, self.lastDepth)):
                self.lastDepth = new
                self._notify()
