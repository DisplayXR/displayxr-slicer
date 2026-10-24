"""Export Slicer's visible segmentations and models to USD (ASCII .usda) for
NVIDIA Omniverse (USD Composer and the other Kit apps).

Plain text writer: no USD libraries needed inside Slicer. Units stay Slicer's
(RAS millimetres) and are declared on the stage (metersPerUnit 0.001,
upAxis Z), so Kit scales and orients the anatomy correctly when it opens or
references the file. Each segment/model becomes a Mesh with normals, a
displayColor/displayOpacity and a bound UsdPreviewSurface material.
"""

import os
import re

import slicer
import vtk


def _name(text, used):
    base = re.sub(r"[^A-Za-z0-9_]", "_", text or "Mesh")
    if not base or base[0].isdigit():
        base = "_" + base
    name, i = base, 1
    while name in used:
        i += 1
        name = f"{base}_{i}"
    used.add(name)
    return name


#: Per-mesh triangle cap: keeps a CT bone segment around 15-30 MB of .usda.
MAX_TRIANGLES = 250000


def _world_polydata(polydata, node, max_triangles=MAX_TRIANGLES):
    """Triangles with point normals, in world RAS (parent transforms applied),
    decimated to at most max_triangles."""
    pd = polydata
    if node is not None and node.GetParentTransformNode():
        t = vtk.vtkGeneralTransform()
        slicer.vtkMRMLTransformNode.GetTransformBetweenNodes(node.GetParentTransformNode(), None, t)
        f = vtk.vtkTransformPolyDataFilter()
        f.SetTransform(t)
        f.SetInputData(pd)
        f.Update()
        pd = f.GetOutput()
    tri = vtk.vtkTriangleFilter()
    tri.SetInputData(pd)
    tri.PassLinesOff()
    tri.PassVertsOff()
    tri.Update()
    src = tri
    ntri = tri.GetOutput().GetNumberOfPolys()
    if max_triangles and ntri > max_triangles:
        dec = vtk.vtkQuadricDecimation()
        dec.SetInputConnection(tri.GetOutputPort())
        dec.SetTargetReduction(1.0 - max_triangles / ntri)
        dec.VolumePreservationOn()
        src = dec
    nrm = vtk.vtkPolyDataNormals()
    nrm.SetInputConnection(src.GetOutputPort())
    nrm.SplittingOff()
    nrm.ConsistencyOn()
    nrm.AutoOrientNormalsOff()
    nrm.Update()
    return nrm.GetOutput()


def collect_meshes():
    """[(label, polydata_world, (r,g,b), opacity)] for everything visible in 3D."""
    out = []
    for seg_node in slicer.util.getNodesByClass("vtkMRMLSegmentationNode"):
        disp = seg_node.GetDisplayNode()
        if disp is None or not disp.GetVisibility() or not disp.GetVisibility3D():
            continue
        seg_node.CreateClosedSurfaceRepresentation()
        seg = seg_node.GetSegmentation()
        for i in range(seg.GetNumberOfSegments()):
            sid = seg.GetNthSegmentID(i)
            if not disp.GetSegmentVisibility(sid) or not disp.GetSegmentVisibility3D(sid):
                continue
            pd = vtk.vtkPolyData()
            seg_node.GetClosedSurfaceRepresentation(sid, pd)
            if pd.GetNumberOfPoints() == 0:
                continue
            s = seg.GetSegment(sid)
            out.append((f"{seg_node.GetName()} {s.GetName()}", _world_polydata(pd, seg_node),
                        s.GetColor(), disp.GetSegmentOpacity3D(sid) * disp.GetOpacity3D()))
    for model in slicer.util.getNodesByClass("vtkMRMLModelNode"):
        disp = model.GetDisplayNode()
        if model.GetHideFromEditors() or disp is None or not disp.GetVisibility() or not disp.GetVisibility3D():
            continue
        pd = model.GetPolyData()
        if pd is None or pd.GetNumberOfPoints() == 0:
            continue
        out.append((model.GetName(), _world_polydata(pd, model), disp.GetColor(), disp.GetOpacity()))
    return out


def _floats(values, per):
    parts = []
    for i in range(0, len(values), per):
        parts.append("(" + ", ".join(f"{v:.6g}" for v in values[i:i + per]) + ")")
    return ", ".join(parts)


def write_usda(path, meshes, root="Slicer"):
    used = set()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("#usda 1.0\n(\n")
        f.write(f'    defaultPrim = "{root}"\n    metersPerUnit = 0.001\n    upAxis = "Z"\n')
        f.write('    doc = "Exported from 3D Slicer by the DisplayXR module (RAS millimetres)"\n)\n\n')
        f.write(f'def Xform "{root}" (\n    kind = "component"\n)\n{{\n')
        f.write('    def Scope "Looks"\n    {\n')
        names = [_name(label, used) for label, _, _, _ in meshes]
        for name, (_, _, color, opacity) in zip(names, meshes):
            r, g, b = color
            f.write(f'        def Material "{name}_mat"\n        {{\n')
            f.write(f'            token outputs:surface.connect = </{root}/Looks/{name}_mat/Surface.outputs:surface>\n')
            f.write('            def Shader "Surface"\n            {\n')
            f.write('                uniform token info:id = "UsdPreviewSurface"\n')
            f.write(f'                color3f inputs:diffuseColor = ({r:.4f}, {g:.4f}, {b:.4f})\n')
            f.write(f'                float inputs:opacity = {opacity:.4f}\n')
            f.write('                float inputs:roughness = 0.5\n')
            f.write('                token outputs:surface\n            }\n        }\n')
        f.write('    }\n\n')
        for name, (label, pd, color, opacity) in zip(names, meshes):
            pts = pd.GetPoints().GetData()
            n = pd.GetNumberOfPoints()
            p = [pts.GetComponent(i, c) for i in range(n) for c in range(3)]
            nr = pd.GetPointData().GetNormals()
            polys = pd.GetPolys()
            ids = vtk.vtkIdList()
            idx = []
            polys.InitTraversal()
            while polys.GetNextCell(ids):
                if ids.GetNumberOfIds() == 3:
                    idx.extend(ids.GetId(k) for k in range(3))
            ntri = len(idx) // 3
            bounds = pd.GetBounds()
            f.write(f'    def Mesh "{name}" (\n        prepend apiSchemas = ["MaterialBindingAPI"]\n    )\n    {{\n')
            f.write(f'        float3[] extent = [({bounds[0]:.6g}, {bounds[2]:.6g}, {bounds[4]:.6g}), '
                    f'({bounds[1]:.6g}, {bounds[3]:.6g}, {bounds[5]:.6g})]\n')
            f.write(f'        int[] faceVertexCounts = [{", ".join(["3"] * ntri)}]\n')
            f.write(f'        int[] faceVertexIndices = [{", ".join(map(str, idx))}]\n')
            f.write(f'        point3f[] points = [{_floats(p, 3)}]\n')
            if nr is not None:
                nv = [nr.GetComponent(i, c) for i in range(n) for c in range(3)]
                f.write(f'        normal3f[] normals = [{_floats(nv, 3)}] (\n            interpolation = "vertex"\n        )\n')
            r, g, b = color
            f.write(f'        color3f[] primvars:displayColor = [({r:.4f}, {g:.4f}, {b:.4f})] (\n            interpolation = "constant"\n        )\n')
            f.write(f'        float[] primvars:displayOpacity = [{opacity:.4f}] (\n            interpolation = "constant"\n        )\n')
            f.write('        uniform token subdivisionScheme = "none"\n')
            f.write(f'        rel material:binding = </{root}/Looks/{name}_mat>\n')
            label_esc = label.replace('"', "'")
            f.write(f'        custom string slicer:name = "{label_esc}"\n    }}\n\n')
        f.write("}\n")
    return [(label, pd.GetNumberOfPoints()) for label, pd, _, _ in meshes]


def default_export_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "DisplayXR", "Slicer")
    os.makedirs(d, exist_ok=True)
    return d


def export_scene(path=None):
    """Write all visible segments/models; returns (path, [(label, points)])."""
    meshes = collect_meshes()
    if not meshes:
        raise RuntimeError("Nothing to export: show a segmentation or model in 3D first.")
    if path is None:
        scene = os.path.splitext(os.path.basename(slicer.mrmlScene.GetURL() or ""))[0] or "SlicerScene"
        path = os.path.join(default_export_dir(), scene + ".usda")
    return path, write_usda(path, meshes)
