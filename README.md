# DisplayXR for 3D Slicer

Glasses-free 3D of 3D Slicer's 3D view on DisplayXR displays (tested on a Leia SR
15.6" panel). The 3D sits **inside Slicer's own 3D view** and weaves at the same
time as other 3D apps on the panel; **F11** shows it on the whole panel. Rotate,
pan and zoom with the mouse as usual. The slice views stay 2D beside it.

> Research and demonstration software. Not a medical device; not for diagnosis.

## Quick start (Windows)

1. Install 3D Slicer 5.12: `winget install Kitware.Slicer`.
2. In Slicer: Extensions Manager → install **SlicerVirtualReality** → restart.
3. Run `Launch-Slicer-DisplayXR.cmd`. It opens the **DisplayXR 3D** module in the
   medical layout (3D left, axial / coronal / sagittal right).
4. Load data (or *Load sample: CT chest*), then **Start 3D**. The status reads
   "3D active".

Windowed 3D needs the DisplayXR hosted-window embed (runtime PR #2332). The
launcher uses `~/dev/displayxr-runtime/_package` when it exists; with the released
runtime (v2.53) the 3D covers the whole panel instead.

## What the module does

| | |
|---|---|
| Rendering | SlicerVirtualReality's OpenXR view (VTK `vtkOpenXRRenderWindow`, OpenGL). DisplayXR runs it as a hosted legacy app. |
| Window | `DXR_HOSTED_WINDOW=auto` embeds the woven window over Slicer; the module publishes the 3D view rect as `DXR_HostedViewRect` (follows layout changes and resizes). |
| Mouse | The runtime forwards the mouse over the 3D to Slicer (`DXR_HOSTED_INPUT=app`; older runtimes: the module makes the woven window click-through). Slicer's own rotate, pan, zoom and markups work, and the 3D follows Slicer's 3D camera every frame. |
| Camera rig | `DXR_LEGACY_CAMERA_RIG` set per start: glass at the 0.6 m nominal viewer, vertical FOV = the 3D view's physical height at 0.6 m, eye separation from the Depth setting. Virtual metres map 1:1 onto the panel, so parallax is predictable: `p(z) = K·(1 − g/z)`. |
| Depth | "Keep depth comfortable" moves the screen plane (and, when zoomed in close, the viewpoint) so the visible content stays inside the panel's comfort budget (≈0.14 % of width in front, 0.42 % behind). The panel shows the live depth. |
| Eye tracking | Leia SR eye tracking gives motion parallax as you move your head. |
| Omniverse | *Send to Omniverse (USD)* writes visible segments/models as `.usda` (UsdPreviewSurface, vertex normals) to `Documents\DisplayXR\Slicer`. It's authored in Kit's default layout, Y-up centimetres, baked in, so it opens or references into USD Composer upright and life size without a correction transform. Kit doesn't convert units or axes on scripted references. Verified in USD Composer (Kit 110.4, RTX) 2026-10-24. `export_scene(omniverse=False)` keeps Slicer's native RAS millimetres (Z-up, metersPerUnit 0.001). Positions stay in Slicer's RAS frame, so separate exports stay registered. |

All runtime/extension internals the module relies on are in
`DisplayXR/displayxr_coupling.py` (none of them is a public contract).

## Platforms

| OS | Status |
|---|---|
| Windows 11 (Leia SR) | Tested 2026-10-24: Slicer 5.12.4, SlicerVirtualReality c9179ed, DisplayXR 2.53 dev. |
| Linux | Blocked: Slicer renders OpenGL; DisplayXR on Linux is Vulkan-only and has no Leia SR plug-in yet. |
| macOS | Untested: no Leia SR plug-in on macOS; DisplayXR has an OpenGL path there (sim-display only). |

## Testing

`tests/` holds scripts run with
`Slicer.exe --additional-module-paths DisplayXR --python-script tests/<file>.py`:

- `test_mouse_passthrough.py`: a posted drag over the 3D window rotates Slicer's camera.
- `test_functional.py`: start, mouse hit-test through the 3D, camera sync,
  comfort solver after zoom, F11 round trip, stop/restart.
- `calibrate_spheres.py`: spheres at known depths. Run with
  `DXR_PLUGIN_EXCLUSIVE=sim-display` (fixed eyes), then
  `tools/measure_spheres.py` on `%TEMP%\displayxr_atlas.SlicerApp-real.projection.png`.
  With nobody in front of a Leia panel the tracker reports both eyes at one
  point, so on-panel captures show no disparity.
- `tools/measure_parallax.py`: block-matched parallax percentiles of any atlas.

Measured (sim-display, Comfortable): spheres at 0.8× / 1.4× the glass distance
show −0.26 % / +0.29 % of view width, against −0.30 % / +0.34 % predicted. The
model is about 15 % conservative. CT chest at the reset view shows −0.05 % … +0.10 %.

## License

Apache-2.0, see LICENSE and NOTICE.
