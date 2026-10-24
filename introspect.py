import slicer, vtk
lg = slicer.modules.virtualreality.logic()
vn = lg.GetVirtualRealityViewNode() if hasattr(lg,'GetVirtualRealityViewNode') else None
print("LOGIC", [m for m in dir(lg) if not m.startswith('_') and m[0].isupper() and 'Observer' not in m])
import vtkSlicerVirtualRealityModuleMRMLPython as M
c = M.vtkMRMLVirtualRealityViewNode
print("VIEWNODE", [m for m in dir(c) if m[0].isupper() and any(k in m for k in ('Set','Get','Runtime','Backend','XR','Enable'))])
slicer.app.exit(0)
