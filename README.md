# DisplayXR for 3D Slicer

Glasses-free 3D of 3D Slicer's 3D view on DisplayXR displays (tested on a Leia SR
15.6" panel). The 3D is drawn **inside Slicer's own 3D view** (the texture target,
runtime v2.55+): Slicer renders both eyes, and the woven image goes back into the
view, so nothing covers Slicer's menus, markups or mouse. **Full panel** shows the
3D view alone on the whole panel. Rotate, pan and zoom with the mouse as usual.
The slice views stay 2D beside it.

**Seated-verified 2026-10-28:** a person at the Leia SR panel ("looks good"), with
3D Slicer 5.12.4, the installed DisplayXR runtime v2.55.0 + Leia plug-in 2.18.3,
and the default launcher.

> Research and demonstration software. Not a medical device; not for diagnosis.

## Quick start (Windows)

1. Install 3D Slicer: `winget install Kitware.Slicer`, and the DisplayXR runtime
   (v2.55 or later).
2. Build the native part once: `native\build.bat` (VS 2022 x64 C++). It writes
   `DisplayXR\bin\` (the host core and the GL presenter).
3. Run `Launch-Slicer-DisplayXR.cmd`. It opens the **DisplayXR 3D** module in the
   medical layout (3D left, axial / coronal / sagittal right).
4. Load data (or *Load sample: CT chest*), then **Start 3D**. The status reads
   "3D active".

Without `DisplayXR\bin\` (or with `DXR_SLICER_MODE=overlay`) the module falls back
to the older overlay path, kept as a measurement rig: SlicerVirtualReality's OpenXR
view, hosted by the runtime (needs the SlicerVirtualReality extension; windowed
only with the unreleased hosted-window embed #2332).

## In Slicer's own 3D view (texture mode)

| | |
|---|---|
| Eyes | Two off-axis `vtkCamera`s rendered by Slicer's own renderer in the 3D view (no OpenXR render window, no SlicerVirtualReality). Each eye's projection is pinned to the runtime's eye tangents. |
| Session | `native/core`: the app-neutral host core shared with the MotionBuilder, Nuke and Houdini adapters (`dxrh_*` C API), built with Slicer's identity. It runs the OpenXR session on its own thread with `XR_DXR_win32_window_binding` v9 (texture target: Slicer's main window + the 3D view's rect), the true-geometry rig and the comfort budget. |
| Draw-back | `native/gl_present.cpp`: in the last `vtkRenderer`'s EndEvent, the woven shared D3D11 texture is blitted into the 3D view through WGL_NV_DX_interop2, one texel per pixel (VTK's core-profile context, so a framebuffer blit). Skipped whenever the view and the published rect disagree in size. |
| Camera | Slicer's 3D camera is the only camera: its pose, view angle and content depth go to the core every frame; mouse and gamepad move it as usual. The core keeps Slicer's framing (pull-back along the view axis, #2422). |
| Depth | Glass a quarter of the way into the visible content ("Keep depth comfortable"), the core fits the eye separation to the budget (0.14 % front / 0.42 % behind of panel width); Depth − / + / Reset in 25 % steps and the Depth slider (above 100 % is an explicit opt-in); Screen plane moves the glass. |
| Display values | Panel size and nominal viewing distance from the runtime's display info; the comfort budget is a constant until display info carries it (#2388). |

Measured (`tests/test_viewport.py`, sim-display, CT chest): VTK's eye projections
match the core's eyes to 0.001 px; disparity −0.140 % / +0.342 % of panel width at
the nearest / farthest content (budget −0.14 % / +0.42 %), 0 on the glass; Depth 50 %
halves it. Rates on this PC (RTX 5070 Ti, 3D view 1689×1815): ~28 eye pairs/s on the
Leia panel. With LeiaSR 1.38 the runtime uses its anchor fallback (state 0x2);
LeiaSR ≥ 1.39 gives the windowless phase.

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

## MONAI AI segmentation (demo)

`Launch-Slicer-MONAI-3D.cmd` runs the live segment in one command: the CTLiver CT →
**MONAI Auto3DSeg** (local GPU inference, model *Abdominal organs TS2*) → the organs
as 3D surfaces in Slicer's own 3D view → Start 3D → *Send to Omniverse (USD)*. The
module panel has the same as an **AI segment organs** button (3D pauses while the
model runs). The 3D view's corner credits the data and the model.

One-time setup (asks nothing; needs ~6 GB of disk for PyTorch + MONAI):

    Slicer.exe --no-splash --no-main-window --python-script tools\install_extension.py MONAIAuto3DSeg
    Slicer.exe --no-splash --no-main-window --python-script tools\setup_monai.py

`setup_monai.py` installs PyTorch with CUDA 12.8 (RTX 50-series needs it) and MONAI
into Slicer's Python, and downloads the model and the sample.

| | Licence |
|---|---|
| MONAIAuto3DSeg extension | MIT |
| Model: Abdominal organs TS2 (TotalSegmentator V2 data) | CC BY 4.0 |
| CT: CTLiver (Medical Segmentation Decathlon, Task03 liver_100) | CC BY-SA 4.0 |

Measured 2026-10-28 (RTX 5070 Ti): 19 organs in ~17 s of inference; the whole live
segment (load → segment → 3D → USD of 19 meshes) in ~52 s. Depth at 100 %: −0.140 % /
+0.27…0.37 % of panel width. Seated on the Leia SR panel: "looks good".

## Platforms

| OS | Status |
|---|---|
| Windows 11 (Leia SR) | Seated-verified 2026-10-28 in Slicer's own 3D view: Slicer 5.12.4, DisplayXR v2.55.0 (installed), Leia plug-in 2.18.3. Overlay path tested 2026-10-24 (SlicerVirtualReality c9179ed, DisplayXR 2.53 dev). |
| Linux | Blocked: Slicer renders OpenGL; DisplayXR on Linux is Vulkan-only and has no Leia SR plug-in yet. |
| macOS | Untested: no Leia SR plug-in on macOS; DisplayXR has an OpenGL path there (sim-display only). |

## Testing

`tests/` holds scripts run with
`Slicer.exe --additional-module-paths DisplayXR --python-script tests/<file>.py`:

- `test_viewport.py`: texture mode on the CT chest: woven frames drawn in the 3D view at its exact size, eye projections against the core's eyes, depth readout, Depth 50 %, clean stop. Run with `DXR_PLUGIN_EXCLUSIVE=sim-display`.
- `seated_start.py`: loads the CT chest and starts 3D for a person at the panel; logs rate, drawn frames and depth to `tests/seated.out.txt`.
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
