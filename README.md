# DisplayXR for 3D Slicer

Glasses-free 3D of 3D Slicer's 3D view on DisplayXR displays (tested on a Leia SR
15.6" panel). The 3D sits **inside Slicer's own 3D view** and weaves at the same
time as other 3D apps on the panel; **F11** shows it on the whole panel. Rotate,
pan and zoom with the mouse as usual. The slice views stay 2D beside it.

> Research and demonstration software. Not a medical device; not for diagnosis.

## Quick start (Windows)

1. Install 3D Slicer: `winget install Kitware.Slicer`.
2. In Slicer: Extensions Manager → install **SlicerVirtualReality** → restart.
3. Run `Launch-Slicer-DisplayXR.cmd`. It opens the **DisplayXR 3D** module in the
   medical layout (3D left, axial / coronal / sagittal right).
4. Load data (or *Load sample: CT chest*), then **Start 3D**. The status reads
   "3D active".

Windowed 3D needs the DisplayXR hosted-window embed (runtime PR #2332); with a
runtime that doesn't have it yet (v2.53) the 3D covers the whole panel instead.

### Launcher options

- **Slicer**: the launcher picks the newest `3D Slicer <version>\Slicer.exe` under
  `%LOCALAPPDATA%\slicer.org` or `%ProgramFiles%\slicer.org`. Set `SLICER_EXE` to the
  full path of `Slicer.exe` to use another install.
- **Runtime**: by default the installed DisplayXR runtime
  (`%ProgramFiles%\DisplayXR\Runtime\DisplayXR_win64.json`, else the system's active
  OpenXR runtime; an `XR_RUNTIME_JSON` you set yourself wins). The machine's active
  runtime is never changed.
- **Dev runtime build** (opt-in): `Launch-Slicer-DisplayXR.cmd -dev`, or set
  `DXR_RUNTIME=dev`. It uses `DXR_DEV_RUNTIME_JSON`, default
  `%USERPROFILE%\dev\displayxr-runtime\_package\bin\DisplayXR_win64.json`.
- `Launch-Slicer-DisplayXR.cmd --which` prints the Slicer and runtime it would use
  and exits. Other arguments are passed on to Slicer.

## What the module does

| | |
|---|---|
| Rendering | SlicerVirtualReality's OpenXR view (VTK `vtkOpenXRRenderWindow`, OpenGL). DisplayXR runs it as a hosted legacy app. |
| Window | `DXR_HOSTED_WINDOW=auto` embeds the woven window over Slicer; the module publishes the 3D view rect as `DXR_HostedViewRect` (follows layout changes and resizes). |
| Mouse | The runtime forwards the mouse over the 3D to Slicer (`DXR_HOSTED_INPUT=app`; older runtimes: the module makes the woven window click-through). Slicer's own rotate, pan, zoom and markups work, and the 3D follows Slicer's 3D camera every frame. |
| Gamepad | An Xbox-style pad (XInput) drives Slicer's own 3D camera while 3D is on and Slicer is in front: left stick orbit, right stick pan, triggers zoom (right in, left out), A resets the 3D view. The runtime's pad fly camera and emulated VR controllers are turned off for Slicer (`DXR_INPUT_GAMEPAD_NAV=0`, `DXR_INPUT_GAMEPAD_EMULATE_CONTROLLERS=0`), since the 3D is pinned to Slicer's camera. Same mapping as the ParaView integration. |
| Camera rig | `DXR_LEGACY_CAMERA_RIG` set per start: glass at the display's nominal viewing distance (display info from `displayxr-cli status --json`, `layout.nominal_viewer_m.z`; 0.6 m if unavailable), vertical FOV = the 3D view's physical height at that distance, eye separation from the Depth setting. Virtual metres map 1:1 onto the panel, so parallax is predictable: `p(z) = K·(1 − g/z)`. |
| Live depth | **Depth** (5–200 %) and **Screen plane** (−50…+100 %) sliders in the module panel, applied while the 3D runs. Depth scales the stereo strength through the runtime (`DXR_HostedDepthRel`, draft #2350; 1.0 = Slicer's comfortable rig). While 3D is on, the module also starts the shared DisplayXR depth slider, vendored in this repo as `tools/DisplayXR-DepthSlider.ps1` (Apache-2.0; run with PowerShell 7 `pwsh -File ... -ProcessId <Slicer pid>` under your execution policy, no bypass; if it can't run, the module logs why and carries on without it), docked at the right of Slicer's menu bar. Both controls stay in sync through `DXR_HostedDepthRelNow`. Screen plane moves the glass inside the module, with no size change. Atlas-verified: 200 % doubles parallax, +50 % puts the glass at exactly 1.5×. |
| Depth | "Keep depth comfortable" moves the screen plane (and, when zoomed in close, the viewpoint) so the visible content stays inside the panel's comfort budget (≈0.14 % of width in front, 0.42 % behind; calibrated on the Leia SR panel and a constant in the module until display info carries it, runtime issue #2388). The panel shows the live depth. |
| Eye tracking | The display's eye tracking (Leia SR in testing) gives motion parallax as you move your head. |
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

- `test_live_sliders.py` / `test_live_depth.py`: live Depth / Screen plane sliders and raw `DXR_HostedDepth`, captured as atlases (sim-display).
- `test_mouse_passthrough.py`: a posted drag over the 3D window rotates Slicer's camera.
- `test_gamepad.py`: a fake pad orbits, pans, zooms and resets Slicer's camera with 3D on; the 3D follows and depth stays in budget.
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
