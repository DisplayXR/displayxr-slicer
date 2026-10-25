"""Gamepad navigation for Slicer's 3D view while 3D is active.

The pad drives Slicer's own 3D camera, the one the mouse drives, not the XR
rig: the 3D is pinned to that camera every frame, so the slices, the 3D, the
comfort depth and the USD export all stay on one camera. The launcher turns the
runtime's own pad handling off for Slicer (DXR_INPUT_GAMEPAD_NAV=0,
DXR_INPUT_GAMEPAD_EMULATE_CONTROLLERS=0): its fly camera would move the 3D off
Slicer's camera, and the emulated VR hands would fight the pin.

    left stick      orbit (rotate about the focal point)
    right stick     pan
    (sticks move the scene the way dragging the mouse does in Slicer)
    triggers        zoom: right in, left out
    A               reset the 3D view to the visible data

Read with XInput, only while a Slicer window is in the foreground, so a pad
used with another 3D app on the panel doesn't move Slicer too. Same mapping as
the ParaView integration.
"""

import ctypes
import math
import os

DEADZONE = 0.15
ORBIT_DPS = 90.0  # degrees per second at full deflection
PAN_PER_S = 1.0  # view half-heights per second
ZOOM_PER_S = 1.0  # doublings of magnification per second, full trigger
BUTTON_A = 0x1000

_user32 = ctypes.WinDLL("user32") if os.name == "nt" else None
_xinput = None
for _name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
    try:
        _xinput = ctypes.WinDLL(_name)
        break
    except (OSError, AttributeError):
        pass


class _State(ctypes.Structure):
    _fields_ = [
        ("packet", ctypes.c_uint),
        ("buttons", ctypes.c_ushort),
        ("left_trigger", ctypes.c_ubyte),
        ("right_trigger", ctypes.c_ubyte),
        ("lx", ctypes.c_short),
        ("ly", ctypes.c_short),
        ("rx", ctypes.c_short),
        ("ry", ctypes.c_short),
    ]


#: Tests set this to a dict like read() returns, in place of a real pad.
fake = None


def _stick(x, y):
    x, y = x / 32767.0, y / 32767.0
    m = math.hypot(x, y)
    if m < DEADZONE:
        return 0.0, 0.0
    s = min((m - DEADZONE) / (1.0 - DEADZONE), 1.0) / m
    return x * s, y * s


def read():
    """The first connected pad: {lx, ly, rx, ry (-1..1, +y up), lt, rt (0..1), buttons}, or None."""
    if fake is not None:
        return fake
    if _xinput is None:
        return None
    for i in range(4):
        st = _State()
        if _xinput.XInputGetState(i, ctypes.byref(st)) == 0:
            lx, ly = _stick(st.lx, st.ly)
            rx, ry = _stick(st.rx, st.ry)
            return {
                "lx": lx, "ly": ly, "rx": rx, "ry": ry,
                "lt": max(st.left_trigger - 30, 0) / 225.0,
                "rt": max(st.right_trigger - 30, 0) / 225.0,
                "buttons": st.buttons,
            }
    return None


def _slicer_in_foreground():
    """The foreground window belongs to this process (Slicer's main window, a
    dialog, or the runtime's 3D window over the 3D view)."""
    if fake is not None:
        return True
    if _user32 is None:
        return False
    fg = _user32.GetForegroundWindow()
    if not fg:
        return False
    pid = ctypes.c_ulong()
    _user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
    return pid.value == os.getpid()


class Navigator:
    """Applies the pad to a qMRMLThreeDView's camera; call update(dt) every frame."""

    def __init__(self, view):
        self.view = view
        self.prev_buttons = 0

    def _camera(self):
        return self.view.cameraNode().GetCamera()

    def _reset(self):
        # Slicer 5: resetCamera(rotation, translation, distance); older: centre only
        if hasattr(self.view, "resetCamera"):
            self.view.resetCamera(False, True, True)
        else:
            self.view.resetFocalPoint()

    def update(self, dt):
        """Returns True if the camera changed."""
        pad = read() if _slicer_in_foreground() else None
        if pad is None:
            self.prev_buttons = 0
            return False
        pressed = pad["buttons"] & ~self.prev_buttons
        self.prev_buttons = pad["buttons"]
        changed = False
        if pressed & BUTTON_A:
            self._reset()
            changed = True
        cam = self._camera()
        dt = min(dt, 0.25)  # no jump after a stall (Slicer can tick slowly while 3D renders)
        if pad["lx"] or pad["ly"]:
            cam.Azimuth(-pad["lx"] * ORBIT_DPS * dt)
            cam.Elevation(pad["ly"] * ORBIT_DPS * dt)
            cam.OrthogonalizeViewUp()
            changed = True
        if pad["rx"] or pad["ry"]:
            half = cam.GetDistance() * math.tan(math.radians(cam.GetViewAngle()) / 2.0)
            if cam.GetParallelProjection():
                half = cam.GetParallelScale()
            dop = cam.GetDirectionOfProjection()
            up = cam.GetViewUp()
            right = (dop[1] * up[2] - dop[2] * up[1], dop[2] * up[0] - dop[0] * up[2], dop[0] * up[1] - dop[1] * up[0])
            step = half * PAN_PER_S * dt
            d = [-(pad["rx"] * right[i] + pad["ry"] * up[i]) * step for i in range(3)]
            fp, pos = cam.GetFocalPoint(), cam.GetPosition()
            cam.SetFocalPoint(*[fp[i] + d[i] for i in range(3)])
            cam.SetPosition(*[pos[i] + d[i] for i in range(3)])
            changed = True
        zoom = pad["rt"] - pad["lt"]
        if zoom:
            f = 2.0 ** (zoom * ZOOM_PER_S * dt)
            if cam.GetParallelProjection():
                cam.SetParallelScale(cam.GetParallelScale() / f)
            else:
                cam.Dolly(f)
            changed = True
        if changed:
            ren = self.view.renderWindow().GetRenderers().GetFirstRenderer()
            if ren is not None:
                ren.ResetCameraClippingRange()
            self.view.scheduleRender()
        return changed
