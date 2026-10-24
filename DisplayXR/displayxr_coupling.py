"""Everything this module depends on from the DisplayXR runtime and from
SlicerVirtualReality that is NOT a public contract.

Each item is an implementation detail observed on DisplayXR 2.53 (+ draft
PRs #2332/#2334) and SlicerVirtualReality c9179ed (Slicer 5.12). Keep them
here so a runtime or extension change breaks one file, not the module.
"""

import ctypes
import ctypes.wintypes as wt
import json
import os

# --- DisplayXR runtime (not a contract) ------------------------------------

#: Inline camera-rig JSON for legacy (hosted) OpenXR apps; read when the
#: session is created, so set it before each start.
ENV_LEGACY_CAMERA_RIG = "DXR_LEGACY_CAMERA_RIG"
#: auto = embed the runtime's 3D window over the app's main window (#2332).
ENV_HOSTED_WINDOW = "DXR_HOSTED_WINDOW"
#: app = the embedded 3D window posts mouse messages to the app's window
#: (runtime branch hosted/input-passthrough). Read once per process.
ENV_HOSTED_INPUT = "DXR_HOSTED_INPUT"
#: Window class of the runtime-owned 3D window (D3D11/GL native compositor).
HOSTED_WINDOW_CLASS = "DisplayXRD3D11"
#: Window property on the app's main window: the viewer rect in physical client
#: pixels, packed x | y<<16 | w<<32 | h<<48. Re-read by the runtime every 250 ms.
HOSTED_VIEW_RECT_PROP = "DXR_HostedViewRect"
#: Per-exe atlas capture trigger in %TEMP% (exe basename without ".exe").
ATLAS_TRIGGER = "displayxr_atlas_trigger.{exe}{suffix}"
ATLAS_OUTPUT = "displayxr_atlas.{exe}{suffix}.png"
#: The legacy rig's nominal eye in the runtime's LOCAL_FLOOR/STAGE space (m).
RIG_EYE = (0.0, 1.6, 0.0)
#: Nominal viewing distance of the Leia SR panel (display info "nominal z").
NOMINAL_VIEWER_M = 0.6
#: Leia SR 15.6" panel used for testing, if displayxr-cli can't be asked.
DEFAULT_PANEL_M = (0.3444, 0.2153)
DEFAULT_PANEL_PX = (3840, 2400)
#: Average interpupillary distance the runtime scales ipdFactor against.
IPD_M = 0.063

# --- SlicerVirtualReality (not a contract) ---------------------------------

#: XR backend enum lives on the MRML view node class.
def openxr_backend():
    import vtkSlicerVirtualRealityModuleMRMLPython as vrmrml
    return vrmrml.vtkMRMLVirtualRealityViewNode.OpenXR


# --- Win32 helpers ----------------------------------------------------------

_u32 = ctypes.windll.user32 if os.name == "nt" else None
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
GWL_EXSTYLE = -20
WM_KEYDOWN, WM_KEYUP, VK_F11 = 0x0100, 0x0101, 0x7A

if _u32:
    _u32.SetPropW.argtypes = [wt.HWND, wt.LPCWSTR, ctypes.c_void_p]
    _u32.RemovePropW.argtypes = [wt.HWND, wt.LPCWSTR]
    _u32.RemovePropW.restype = ctypes.c_void_p
    _u32.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    _u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _u32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    _u32.GetWindow.restype = wt.HWND
    _u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


def find_hosted_window(pid=None):
    """The runtime's 3D window in this process, or None."""
    if not _u32:
        return None
    pid = pid or os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        p = wt.DWORD()
        _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            cls = ctypes.create_unicode_buffer(64)
            _u32.GetClassNameW(hwnd, cls, 64)
            if cls.value == HOSTED_WINDOW_CLASS:
                found.append(hwnd)
        return True

    _u32.EnumWindows(cb, 0)
    return found[0] if found else None


def window_owner(hwnd):
    return _u32.GetWindow(hwnd, 4) if _u32 and hwnd else None  # GW_OWNER


def window_rect(hwnd):
    r = wt.RECT()
    _u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def publish_view_rect(main_hwnd, x, y, w, h):
    """Tell the runtime where the 3D viewer is (physical client px)."""
    x, y, w, h = (max(0, min(int(v), 0xFFFF)) for v in (x, y, w, h))
    packed = x | (y << 16) | (w << 32) | (h << 48)
    _u32.SetPropW(main_hwnd, HOSTED_VIEW_RECT_PROP, ctypes.c_void_p(packed))


def clear_view_rect(main_hwnd):
    if _u32 and main_hwnd:
        _u32.RemovePropW(main_hwnd, HOSTED_VIEW_RECT_PROP)


def runtime_passes_input(hwnd):
    """The runtime forwards the mouse itself (DXR_HOSTED_INPUT=app marks its
    window WS_EX_NOACTIVATE); then leave the window styles alone."""
    WS_EX_NOACTIVATE = 0x08000000
    return bool(_u32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_NOACTIVATE)


def set_click_through(hwnd, on):
    """Let the mouse reach Slicer's own 3D view under the woven window."""
    ex = _u32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    want = (ex | WS_EX_LAYERED | WS_EX_TRANSPARENT) if on else (ex & ~WS_EX_TRANSPARENT)
    if want != ex:
        _u32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, want)
        if on:
            _u32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)  # LWA_ALPHA, opaque


def post_f11(hwnd):
    """Toggle the runtime's own panel-fullscreen mode (its F11 handler)."""
    _u32.PostMessageW(hwnd, WM_KEYDOWN, VK_F11, 0x00570001)
    _u32.PostMessageW(hwnd, WM_KEYUP, VK_F11, 0xC0570001)


def is_panel_fullscreen(hwnd):
    """The runtime's F11 mode: the 3D window covers its whole monitor."""
    MONITOR_DEFAULTTONEAREST = 2

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    mon = _u32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(mi)
    _u32.GetMonitorInfoW(mon, ctypes.byref(mi))
    x, y, w, h = window_rect(hwnd)
    m = mi.rcMonitor
    return x <= m.left and y <= m.top and w >= m.right - m.left and h >= m.bottom - m.top


def panel_geometry():
    """(width_m, height_m, width_px, height_px) of the 3D panel."""
    import subprocess
    cli = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "DisplayXR", "Runtime", "displayxr-cli.exe")
    try:
        out = subprocess.run([cli, "status", "--json"], capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        st = json.loads(out)
        for s in st.get("screens", []):
            mm = s.get("physical_mm") or {}
            nat = s.get("native") or {}
            if mm.get("width") and nat.get("width"):
                return mm["width"] / 1000.0, mm["height"] / 1000.0, nat["width"], nat["height"]
    except Exception:
        pass
    return DEFAULT_PANEL_M + DEFAULT_PANEL_PX


def atlas_paths(exe_basename, projection=True):
    tmp = os.environ.get("TEMP", r"C:\Temp")
    sfx = ".projection" if projection else ""
    return (os.path.join(tmp, ATLAS_TRIGGER.format(exe=exe_basename, suffix=sfx)),
            os.path.join(tmp, ATLAS_OUTPUT.format(exe=exe_basename, suffix=sfx)))
