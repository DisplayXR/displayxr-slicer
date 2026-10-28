"""AI segmentation with MONAI Auto3DSeg, then 3D and Omniverse.

The demo flow: a CT -> MONAIAuto3DSeg (local inference, no server) -> the
segments as 3D surfaces in Slicer's own 3D view -> Start 3D -> Send to
Omniverse (USD). Needs the MONAIAuto3DSeg extension and tools/setup_monai.py
(PyTorch, MONAI, the model). Inference runs with 3D stopped: one heavy GPU job
at a time.

Default model: "Abdominal organs TS2" (23 organs, CC BY 4.0, trained on the
TotalSegmentator V2 dataset). Default data: Slicer's CTLiver sample (Medical
Segmentation Decathlon, CC BY-SA 4.0). Research and demonstration only; not a
medical device.
"""

import time

import slicer

DEFAULT_MODEL = "Abdominal organs TS2"
DEFAULT_SAMPLE = "CTLiver"


def _view_widget():
    """The 3D view on screen (same choice as the DisplayXR logic)."""
    import DisplayXR
    return DisplayXR.DisplayXRLogic.instance().threeDWidget()


def available():
    try:
        import MONAIAuto3DSeg  # noqa: F401
        return True
    except ImportError:
        return False


def model_info(title=DEFAULT_MODEL):
    import MONAIAuto3DSeg
    logic = MONAIAuto3DSeg.MONAIAuto3DSegLogic()
    m = next(m for m in logic.models if m.get("title") == title)
    return logic, m


def segment(volume, title=DEFAULT_MODEL, cpu=False):
    """Run the model on `volume`; returns (segmentation node, seconds)."""
    logic, model = model_info(title)
    logic.setupPythonRequirements()
    seg = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", f"{volume.GetName()} {title}")
    seg.CreateDefaultDisplayNodes()
    seg.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    t0 = time.time()
    logic.process([volume], seg, model["id"], cpu=cpu, waitForCompletion=True)
    return seg, time.time() - t0


CREDITS = {
    "CTLiver": "CT: Medical Segmentation Decathlon (CTLiver), CC BY-SA 4.0",
    DEFAULT_MODEL: "Segmentation: MONAI Auto3DSeg, Abdominal organs TS2 (TotalSegmentator V2 data), CC BY 4.0",
}


def show_credits(sample=DEFAULT_SAMPLE, title=DEFAULT_MODEL):
    """Credit the data and the model in the 3D view's corner (so they're in the
    3D image and in any capture too)."""
    import vtk
    w = _view_widget()
    if w is None:
        return
    lines = (CREDITS.get(sample), CREDITS.get(title), "Research and demonstration only; not for diagnosis.")
    text = chr(10).join(t for t in lines if t)
    view = w.threeDView()
    ca = view.cornerAnnotation()
    ca.SetText(vtk.vtkCornerAnnotation.LowerLeft, text)
    ca.GetTextProperty().SetFontSize(14)
    view.scheduleRender()


def show_in_3d(seg, smoothing=0.5):
    """Segments as smooth 3D surfaces; volume rendering off so they show."""
    seg.GetSegmentation().SetConversionParameter("Smoothing factor", str(smoothing))
    seg.CreateClosedSurfaceRepresentation()
    disp = seg.GetDisplayNode()
    disp.SetVisibility3D(True)
    disp.SetOpacity3D(1.0)
    for d in slicer.util.getNodesByClass("vtkMRMLVolumeRenderingDisplayNode"):
        d.SetVisibility(False)
    # Never too zoomed in: the whole anatomy in view at middle size.
    w = _view_widget()
    if w is not None:
        view = w.threeDView()
        view.resetFocalPoint()
        view.resetCamera(True, True, True)
    return seg.GetSegmentation().GetNumberOfSegments()
