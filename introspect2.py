import slicer, vtk
w = slicer.modules.virtualreality.widgetRepresentation()
import qSlicerVirtualRealityModuleWidgetsPythonQt as W
print("VIEWCLS", [m for m in dir(W.qMRMLVirtualRealityView) if not m.startswith('_')][:400])
import vtkmodules.vtkRenderingOpenXR as X
print("OXRWIN", [m for m in dir(X.vtkOpenXRRenderWindow) if m.startswith(('Set','Get')) and any(k in m for k in ('Physical','Window','Graphics','Stereo','Size','Pose','Head','Model','Runtime','Base'))])
import vtkmodules.vtkRenderingVR as V
print("VRCAM", [m for m in dir(V.vtkVRCamera) if m.startswith(('Set','Get','Use'))][:120])
slicer.app.exit(0)
