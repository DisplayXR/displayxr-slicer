"""3D in Slicer's own 3D view: the in-viewport target (texture mode).

No OpenXR render window and no SlicerVirtualReality. Slicer renders two
off-axis eyes with its own renderer (plain vtkCameras, UseOffAxisProjection
style through ViewAngle + WindowCenter), the host core (bin/displayxr_host.dll,
the app-neutral core shared with the MotionBuilder / Nuke / Houdini adapters)
hands them to the runtime through XR_DXR_win32_window_binding v9 (runtime
v2.55+), and the woven frame is drawn back into the 3D view by
bin/displayxr_slicer_gl.dll in the last vtkRenderer's EndEvent. Nothing covers
Slicer: its menus, markups and mouse stay its own.

Per tick:
  1. publish the 3D view's rect (main-window client px) as the target;
  2. hand the core Slicer's camera (pose, view angle, glass, content depth);
  3. if the core located new eyes, render both, read them back and submit;
  4. render once more (the display pass): EndEvent draws the woven frame.

Picking goes through the rig's centre eye, not Slicer's mono camera. The core
moves the eyes off Slicer's camera (pushed back to the true-geometry glass,
pitched up to the nominal viewer, offset by the tracked head), so the mono
camera's ray through the cursor misses what the viewer sees there. The centre
eye of the pair on screen is swapped in as the renderer's active camera for
the display pass (so the z-buffer the quick picker reads is the centre eye's)
and for each mouse / key event (so the accurate pickers, markups hover and
placement use it); Slicer's camera is back as soon as the event is handled.
Navigation is unaffected: Slicer's camera widget moves the camera node's
camera, never the renderer's active one. DXR_SLICER_PICK=mono turns it off
(A/B checks).
"""

import ctypes
import math
import os

import vtk

BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
HOST_DLL = "displayxr_host.dll"
GL_DLL = "displayxr_slicer_gl.dll"


class _Pose(ctypes.Structure):
    _fields_ = [(n, ctypes.c_float) for n in ("px", "py", "pz", "qx", "qy", "qz", "qw")]


class _Camera(ctypes.Structure):
    _fields_ = [("pose", _Pose), ("vertical_fov", ctypes.c_float), ("glass_distance", ctypes.c_float),
                ("near_z", ctypes.c_float), ("far_z", ctypes.c_float)]


class _Eye(ctypes.Structure):
    _fields_ = [("pose", _Pose)] + [(n, ctypes.c_float) for n in
                                    ("angle_left", "angle_right", "angle_up", "angle_down")]


class _DepthInfo(ctypes.Structure):
    _fields_ = [(n, ctypes.c_float) for n in ("strength", "glass", "front_pct", "behind_pct", "ipd_factor")]


_libs = None


def available():
    return os.path.exists(os.path.join(BIN, HOST_DLL)) and os.path.exists(os.path.join(BIN, GL_DLL))


def _load():
    global _libs
    if _libs is None:
        os.add_dll_directory(BIN)
        host = ctypes.CDLL(os.path.join(BIN, HOST_DLL))
        gl = ctypes.CDLL(os.path.join(BIN, GL_DLL))
        host.dxrh_start_in_viewport.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4
        host.dxrh_set_target.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4
        host.dxrh_set_camera.argtypes = [ctypes.POINTER(_Camera)]
        host.dxrh_set_depth.argtypes = [ctypes.c_float, ctypes.c_int]
        host.dxrh_get_depth.argtypes = [ctypes.POINTER(_DepthInfo)]
        host.dxrh_get_eyes.argtypes = [ctypes.POINTER(_Eye * 2), ctypes.POINTER(ctypes.c_uint32)]
        host.dxrh_render_size.argtypes = [ctypes.POINTER(ctypes.c_int)] * 2
        host.dxrh_submit_rgba8.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 3 + [ctypes.c_uint32]
        host.dxrh_status.argtypes = [ctypes.c_char_p, ctypes.c_int]
        host.dxrh_texture_info.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int),
                                           ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint64)]
        gl.dxs_info.argtypes = [ctypes.c_char_p, ctypes.c_int]
        _libs = (host, gl)
    return _libs


def _quat_from_axes(right, up, back):
    """Quaternion (x, y, z, w) of the rotation whose columns are right, up, back."""
    m00, m01, m02 = right[0], up[0], back[0]
    m10, m11, m12 = right[1], up[1], back[1]
    m20, m21, m22 = right[2], up[2], back[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        return ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        return (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        return ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2
    return ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)


def _axes_from_quat(q):
    """(right, up, back) columns of quaternion q = (x, y, z, w)."""
    x, y, z, w = q
    right = (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y))
    up = (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x))
    back = (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))
    return right, up, back


def eye_camera(cam, eye, glass):
    """Set vtkCamera `cam` to the core's off-axis eye (world = Slicer RAS mm)."""
    p = eye.pose
    right, up, back = _axes_from_quat((p.qx, p.qy, p.qz, p.qw))
    tl, tr = math.tan(eye.angle_left), math.tan(eye.angle_right)
    tu, td = math.tan(eye.angle_up), math.tan(eye.angle_down)
    cam.SetPosition(p.px, p.py, p.pz)
    d = max(glass, 1e-3)
    cam.SetFocalPoint(p.px - back[0] * d, p.py - back[1] * d, p.pz - back[2] * d)
    cam.SetViewUp(*up)
    cam.SetParallelProjection(False)
    # VTK frustum: y in [(wy-1)t, (wy+1)t], x in [(wx-1)t*aspect, (wx+1)t*aspect],
    # t = tan(viewAngle/2); aspect = the render's, which the core keeps canvas-true.
    cam.SetViewAngle(math.degrees(2.0 * math.atan((tu - td) / 2.0)))
    cam.SetWindowCenter((tr + tl) / (tr - tl), (tu + td) / (tu - td))
    return (tr - tl) / (tu - td)  # aspect the eye expects


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def centre_eye(eyes):
    """The cyclopean eye of a stereo pair: at the midpoint of the two eyes, with
    eye 0's orientation, and a frustum through the same window (the 3D view on
    the glass) as both eyes' frusta. A point is perceived on screen where its two
    eye images average, which is where this eye sees it, so the ray from it
    through the cursor is the one the viewer looks along. Exact when the eyes
    share an orientation (the runtime's eyes are display-aligned)."""
    e0, e1 = eyes[0], eyes[1]
    q = (e0.pose.qx, e0.pose.qy, e0.pose.qz, e0.pose.qw)
    p0 = (e0.pose.px, e0.pose.py, e0.pose.pz)
    p1 = (e1.pose.px, e1.pose.py, e1.pose.pz)
    right, up, back = _axes_from_quat(q)
    d = [p1[i] - p0[i] for i in range(3)]
    x1, y1, z1 = _dot(d, right), _dot(d, up), _dot(d, back)   # eye 1 in eye 0's frame
    t0 = [math.tan(a) for a in (e0.angle_left, e0.angle_right, e0.angle_up, e0.angle_down)]
    t1 = [math.tan(a) for a in (e1.angle_left, e1.angle_right, e1.angle_up, e1.angle_down)]
    # Both look down -z; with the glass at z = zs, eye i's window edge sits at
    # offset_i + tan_i * (z_i - zs). Eye 0 is the origin, so an edge both eyes
    # share gives zs = (offset_1 + tan_1 * z1) / (tan_1 - tan_0). Take the
    # best-conditioned edge; none (coincident eyes: no viewer tracked) -> average.
    zs, best = None, 1e-6
    for k, off in ((0, x1), (1, x1), (2, y1), (3, y1)):
        den = t1[k] - t0[k]
        if abs(den) > best:
            cand = (off + t1[k] * z1) / den
            if cand < min(0.0, z1):  # the glass is in front of both eyes
                zs, best = cand, abs(den)
    cx, cy, cz = x1 / 2.0, y1 / 2.0, z1 / 2.0
    if zs is None:
        tans = [(t0[k] + t1[k]) / 2.0 for k in range(4)]
    else:
        dc = cz - zs
        edges = [-t * zs for t in t0]  # window edges in eye 0's frame, on the glass
        tans = [(edges[0] - cx) / dc, (edges[1] - cx) / dc, (edges[2] - cy) / dc, (edges[3] - cy) / dc]
    c = _Eye()
    c.pose = _Pose((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0, (p0[2] + p1[2]) / 2.0, *q)
    c.angle_left, c.angle_right, c.angle_up, c.angle_down = (math.atan(t) for t in tans)
    return c


def set_exact_frustum(cam, eye):
    """Pin the eye's projection to its exact tangents (VTK otherwise takes the
    width from the render's aspect, off when the panel's pixels aren't square,
    e.g. sim-display). Call after the clipping range is set. False if this VTK
    has no explicit projection."""
    if not hasattr(cam, "SetExplicitProjectionTransformMatrix"):
        return False
    n, f = cam.GetClippingRange()
    l, r = math.tan(eye.angle_left) * n, math.tan(eye.angle_right) * n
    b, t = math.tan(eye.angle_down) * n, math.tan(eye.angle_up) * n
    m = vtk.vtkMatrix4x4()
    m.Zero()
    m.SetElement(0, 0, 2 * n / (r - l))
    m.SetElement(0, 2, (r + l) / (r - l))
    m.SetElement(1, 1, 2 * n / (t - b))
    m.SetElement(1, 2, (t + b) / (t - b))
    m.SetElement(2, 2, -(f + n) / (f - n))
    m.SetElement(2, 3, -2 * f * n / (f - n))
    m.SetElement(3, 2, -1.0)
    cam.SetExplicitProjectionTransformMatrix(m)
    cam.SetUseExplicitProjectionTransformMatrix(True)
    return True


class ViewportSession:
    """One texture-mode 3D session on a qMRMLThreeDView."""

    def __init__(self, view, main_hwnd, rect_fn):
        self.host, self.gl = _load()
        self.view = view
        self.main_hwnd = main_hwnd
        self.rect_fn = rect_fn          # () -> (x, y, w, h) of the 3D view, main-window client px
        self.rw = view.renderWindow()
        self.target = None
        self.serial = 0
        self.pairs = 0
        self.eye_cams = (vtk.vtkCamera(), vtk.vtkCamera())
        self._in_eyes = False
        self._obs = None
        self._obs_ren = None
        self.glass = 0.0
        self.content = None            # (near, far) along the view, mm
        self.aspect_error = 0.0
        self.last_eyes = None
        # Picking from the centre eye of the pair on screen (see the module doc).
        self.pick_centre = os.environ.get("DXR_SLICER_PICK", "centre").lower() != "mono"
        self.centre = None             # _Eye of the pair on screen, None until one is
        self.centre_cam = vtk.vtkCamera()
        self._main_obs = []            # (renderer, tag) for the display pass
        self._input_obs = []           # (interactor, tag)
        self._render_saved = None      # active camera to put back after a display pass
        self._event_saved = None       # Slicer's camera to put back after an event
        self._restore_queued = False

    # -- lifecycle --------------------------------------------------------
    def start(self):
        x, y, w, h = self.rect_fn()
        self.target = (x, y, w, h)
        if self.host.dxrh_start_in_viewport(ctypes.c_void_p(self.main_hwnd), x, y, w, h) != 0:
            return self.status()
        self._observe()
        return None

    def stop(self):
        self.host.dxrh_stop()
        # One more render with the observer on releases the GL objects on VTK's context.
        try:
            self.rw.Render()
        except Exception:
            pass
        if self._obs is not None:
            self._obs_ren.RemoveObserver(self._obs)
        self._obs = self._obs_ren = None
        self._unobserve_picking()
        self.view.scheduleRender()

    def running(self):
        return bool(self.host.dxrh_is_running())

    def status(self):
        buf = ctypes.create_string_buffer(256)
        self.host.dxrh_status(buf, 256)
        return buf.value.decode("utf-8", "replace")

    def gl_info(self):
        buf = ctypes.create_string_buffer(512)
        self.gl.dxs_info(buf, 512)
        return buf.value.decode("utf-8", "replace")

    def drawn(self):
        return self.gl.dxs_drawn()

    def texture_state(self):
        h, w, hh, f = ctypes.c_void_p(), ctypes.c_int(), ctypes.c_int(), ctypes.c_uint64()
        if self.host.dxrh_texture_info(ctypes.byref(h), ctypes.byref(w), ctypes.byref(hh), ctypes.byref(f)):
            return f.value
        return None

    def save_eyes(self, path):
        """The last submitted eye pair, side by side (left | right), as PNG."""
        import numpy as np
        from vtk.util.numpy_support import numpy_to_vtk
        pair = getattr(self, "last_pair", None)
        if not pair:
            return False
        sbs = np.ascontiguousarray(np.concatenate(pair, axis=1)[::-1])  # VTK images are bottom row first
        h, w = sbs.shape[:2]
        img = vtk.vtkImageData()
        img.SetDimensions(w, h, 1)
        img.GetPointData().SetScalars(numpy_to_vtk(sbs.reshape(-1, 4), deep=True))
        wr = vtk.vtkPNGWriter()
        wr.SetFileName(path)
        wr.SetInputData(img)
        wr.Write()
        return True

    def depth(self):
        d = _DepthInfo()
        self.host.dxrh_get_depth(ctypes.byref(d))
        return d

    def set_depth(self, strength):
        self.host.dxrh_set_depth(float(strength), 1 if strength > 1.0 else 0)

    # -- per tick ---------------------------------------------------------
    def _last_renderer(self):
        rens = self.rw.GetRenderers()
        last, layer = None, -1
        for i in range(rens.GetNumberOfItems()):
            r = rens.GetItemAsObject(i)
            if r.GetLayer() >= layer:
                last, layer = r, r.GetLayer()
        return last

    def _main_renderer(self):
        return self.rw.GetRenderers().GetFirstRenderer()

    def _observe(self):
        ren = self._last_renderer()
        self._obs_ren = ren
        self._obs = ren.AddObserver(vtk.vtkCommand.EndEvent, self._on_end)
        if self.pick_centre:
            self._observe_picking()

    def _on_end(self, *_):
        if not self._in_eyes:
            self.gl.dxs_present()

    # -- picking from the centre eye ----------------------------------------
    #: Interactor events Slicer's interactor style handles (and picks on).
    INPUT_EVENTS = ("MouseMoveEvent", "LeftButtonPressEvent", "LeftButtonReleaseEvent",
                    "LeftButtonDoubleClickEvent", "MiddleButtonPressEvent", "MiddleButtonReleaseEvent",
                    "MiddleButtonDoubleClickEvent", "RightButtonPressEvent", "RightButtonReleaseEvent",
                    "RightButtonDoubleClickEvent", "MouseWheelForwardEvent", "MouseWheelBackwardEvent",
                    "EnterEvent", "LeaveEvent", "KeyPressEvent", "KeyReleaseEvent", "CharEvent",
                    "StartPinchEvent", "PinchEvent", "EndPinchEvent", "StartRotateEvent", "RotateEvent",
                    "EndRotateEvent", "StartPanEvent", "PanEvent", "EndPanEvent", "TapEvent", "LongTapEvent")
    #: Above Slicer's interactor style (priority 0), so the swap precedes its picks.
    INPUT_PRIORITY = 10.0

    def _observe_picking(self):
        ren = self._main_renderer()
        self._main_obs = [(ren, ren.AddObserver(vtk.vtkCommand.StartEvent, self._on_main_start)),
                          (ren, ren.AddObserver(vtk.vtkCommand.EndEvent, self._on_main_end))]
        iren = self.rw.GetInteractor()
        if iren is not None:
            for name in self.INPUT_EVENTS:
                try:
                    self._input_obs.append((iren, iren.AddObserver(name, self._on_input, self.INPUT_PRIORITY)))
                except Exception:
                    pass  # an event this VTK doesn't have

    def _unobserve_picking(self):
        for obj, tag in self._main_obs + self._input_obs:
            obj.RemoveObserver(tag)
        self._main_obs, self._input_obs = [], []
        self._restore_slicer_camera()
        self.centre = None

    def _centre_ready(self):
        return self.pick_centre and self.centre is not None and not self._in_eyes

    def _on_main_start(self, *_):
        """Display pass: render it from the centre eye. Its colour is replaced by
        the woven frame; its depth is what the quick (z-buffer) picker reads."""
        if not self._centre_ready():
            return
        ren = self._main_renderer()
        self._render_saved = ren.GetActiveCamera()
        ren.SetActiveCamera(self.centre_cam)
        if hasattr(self.centre_cam, "SetUseExplicitProjectionTransformMatrix"):
            self.centre_cam.SetUseExplicitProjectionTransformMatrix(False)
        ren.ResetCameraClippingRange()
        set_exact_frustum(self.centre_cam, self.centre)

    def _on_main_end(self, *_):
        if self._render_saved is not None:
            self._main_renderer().SetActiveCamera(self._render_saved)
            self._render_saved = None

    def _on_input(self, *_):
        """Before Slicer's interactor style sees the event: centre eye active."""
        if not self._centre_ready():
            return
        ren = self._main_renderer()
        cur = ren.GetActiveCamera()
        if cur is self.centre_cam:
            return
        self._event_saved = cur
        ren.SetActiveCamera(self.centre_cam)
        if not self._restore_queued:
            import qt
            self._restore_queued = True
            qt.QTimer.singleShot(0, self._restore_slicer_camera)  # once the event is handled

    def _restore_slicer_camera(self):
        self._restore_queued = False
        saved, self._event_saved = self._event_saved, None
        if saved is None:
            return
        ren = self._main_renderer()
        if ren.GetActiveCamera() is self.centre_cam:
            ren.SetActiveCamera(saved)

    def pick_ray(self, x, y):
        """World ray (origin, unit direction) through VTK display pixel (x, y),
        bottom-left origin, from the camera picking uses. For tests."""
        ren = self._main_renderer()
        cam = self.centre_cam if self._centre_ready() else ren.GetActiveCamera()
        prev = ren.GetActiveCamera()
        ren.SetActiveCamera(cam)
        try:
            far = [0.0] * 4
            vtk.vtkInteractorObserver.ComputeDisplayToWorld(ren, float(x), float(y), 1.0, far)
            o = cam.GetPosition()
            v = [far[i] / far[3] - o[i] for i in range(3)]
            n = math.sqrt(_dot(v, v)) or 1.0
            return o, [c / n for c in v]
        finally:
            ren.SetActiveCamera(prev)

    def content_depth(self, cam):
        """Nearest/farthest visible content along the view direction (mm), or None."""
        ren = self._main_renderer()
        b = [0.0] * 6
        ren.ComputeVisiblePropBounds(b)
        if b[0] > b[1]:
            return None
        pos, dop = cam.GetPosition(), cam.GetDirectionOfProjection()
        ds = [sum((p[n] - pos[n]) * dop[n] for n in range(3))
              for p in ((b[i], b[j], b[k]) for i in (0, 1) for j in (2, 3) for k in (4, 5))]
        return min(ds), max(ds)

    def set_camera(self, cam, glass, content):
        """Slicer's camera -> the core (pose, framing, glass, depth range)."""
        dop = list(cam.GetDirectionOfProjection())
        up = list(cam.GetViewUp())
        right = [0.0] * 3
        vtk.vtkMath.Cross(dop, up, right)
        vtk.vtkMath.Normalize(right)
        vtk.vtkMath.Cross(right, dop, up)
        vtk.vtkMath.Normalize(up)
        q = _quat_from_axes(right, up, [-d for d in dop])
        pos = cam.GetPosition()
        c = _Camera()
        c.pose = _Pose(pos[0], pos[1], pos[2], *q)
        c.vertical_fov = math.radians(cam.GetViewAngle())
        c.glass_distance = glass
        if content:
            c.near_z, c.far_z = max(content[0], glass * 0.01), content[1]
        self.glass, self.content = glass, content
        self.host.dxrh_set_camera(ctypes.byref(c))

    def tick(self, slicer_cam):
        """Publish the target, render a new eye pair if the core has new eyes,
        and redraw the view (which draws the woven frame). True if rendered."""
        rect = self.rect_fn()
        if rect != self.target and rect[2] > 0 and rect[3] > 0:
            self.target = rect
            self.host.dxrh_set_target(ctypes.c_void_p(self.main_hwnd), *rect)
        eyes = (_Eye * 2)()
        serial = ctypes.c_uint32()
        if not self.host.dxrh_get_eyes(ctypes.byref(eyes), ctypes.byref(serial)):
            return False
        if serial.value == self.serial:
            return False
        self.serial = serial.value
        self.last_eyes = eyes
        self._render_pair(eyes, serial.value, slicer_cam)
        return True

    def render_size(self):
        """Pixels VTK renders the 3D view at; (0, 0) until Qt has given the
        render window its size (the view hasn't been painted yet)."""
        w, h = self.rw.GetActualSize()
        return int(w), int(h)

    def _render_pair(self, eyes, serial, slicer_cam):
        import numpy as np
        ren = self._main_renderer()
        w, h = self.render_size()
        if w <= 0 or h <= 0:
            self.view.forceRender()  # let Qt size the render window; eyes next tick
            self.serial = 0
            return
        imgs = []
        self._in_eyes = True
        try:
            for i in range(2):
                ec = self.eye_cams[i]
                want = eye_camera(ec, eyes[i], self.glass or slicer_cam.GetDistance())
                self.aspect_error = want / (w / h) - 1.0
                if hasattr(ec, "SetUseExplicitProjectionTransformMatrix"):
                    ec.SetUseExplicitProjectionTransformMatrix(False)  # clipping range from the plain frustum
                ren.SetActiveCamera(ec)
                ren.ResetCameraClippingRange()
                if set_exact_frustum(ec, eyes[i]):
                    self.aspect_error = 0.0
                self.rw.Render()
                arr = vtk.vtkUnsignedCharArray()
                self.rw.GetRGBACharPixelData(0, 0, w - 1, h - 1, 0, arr)
                from vtk.util.numpy_support import vtk_to_numpy
                img = vtk_to_numpy(arr).reshape(h, w, 4)[::-1]  # top row first
                imgs.append(np.ascontiguousarray(img))
        finally:
            ren.SetActiveCamera(slicer_cam)
            ren.ResetCameraClippingRange()
            self._in_eyes = False
        self.host.dxrh_submit_rgba8(imgs[0].ctypes.data, imgs[1].ctypes.data, w, h, w * 4, serial)
        self.last_pair = imgs
        self.pairs += 1
        # This pair is what the view shows from here on: pick through its centre eye.
        self.centre = centre_eye(eyes)
        eye_camera(self.centre_cam, self.centre, self.glass or slicer_cam.GetDistance())
        self.rw.Render()  # display pass (centre eye); EndEvent draws the woven frame
