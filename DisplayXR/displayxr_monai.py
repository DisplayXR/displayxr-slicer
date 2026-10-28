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
    lm = slicer.app.layoutManager()
    if lm and lm.threeDViewCount > 0:
        view = lm.threeDWidget(0).threeDView()
        view.resetFocalPoint()
        view.resetCamera(True, True, True)
    return seg.GetSegmentation().GetNumberOfSegments()
