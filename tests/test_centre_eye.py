"""Unit test for displayxr_viewport.centre_eye (no Slicer needed):
    python tests/test_centre_eye.py
Builds eye pairs from a known window on the glass (rotated rig, lateral and
depth eye offsets, coincident eyes) and checks the centre eye's frustum passes
through that window, and that with the eyes level with the glass it sees every
point where its two eye images average (what the viewer perceives)."""
import math, os, random, sys, types

sys.modules.setdefault("vtk", types.ModuleType("vtk"))  # the module imports vtk; centre_eye doesn't use it
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "DisplayXR"))
import displayxr_viewport as V


def quat_axis_angle(axis, ang):
    n = math.sqrt(sum(a * a for a in axis))
    s = math.sin(ang / 2) / n
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(ang / 2))


def to_world(q, origin, local):
    right, up, back = V._axes_from_quat(q)
    return [origin[i] + local[0] * right[i] + local[1] * up[i] + local[2] * back[i] for i in range(3)]


def make_eye(q, origin, local, window, zs):
    """Eye at `local` (rig frame) looking through window (l, r, b, t) on z = zs."""
    l, r, b, t = window
    d = local[2] - zs
    e = V._Eye()
    e.pose = V._Pose(*to_world(q, origin, local), *q)
    e.angle_left, e.angle_right = math.atan((l - local[0]) / d), math.atan((r - local[0]) / d)
    e.angle_up, e.angle_down = math.atan((t - local[1]) / d), math.atan((b - local[1]) / d)
    return e


def project(e, p):
    """Point p in eye e's normalised window coords (0..1, 0..1)."""
    q = e.pose
    right, up, back = V._axes_from_quat((q.qx, q.qy, q.qz, q.qw))
    d = [p[i] - (q.px, q.py, q.pz)[i] for i in range(3)]
    xc, yc, zc = V._dot(d, right), V._dot(d, up), -V._dot(d, back)
    tl, tr, tu, td = (math.tan(a) for a in (e.angle_left, e.angle_right, e.angle_up, e.angle_down))
    return (xc / zc - tl) / (tr - tl), (yc / zc - td) / (tu - td)


def check(case, q, origin, l0, l1, window, zs, level):
    eyes = (make_eye(q, origin, l0, window, zs), make_eye(q, origin, l1, window, zs))
    c = V.centre_eye(eyes)
    mid = [(l0[i] + l1[i]) / 2 for i in range(3)]
    want = make_eye(q, origin, mid, window, zs)
    err = max(abs(getattr(c, a) - getattr(want, a)) for a in ("angle_left", "angle_right", "angle_up", "angle_down"))
    pos = max(abs(getattr(c.pose, a) - getattr(want.pose, a)) for a in ("px", "py", "pz"))
    worst = 0.0
    if level:
        rnd = random.Random(7)
        for _ in range(200):
            p = to_world(q, origin, (rnd.uniform(-2, 2), rnd.uniform(-2, 2), zs * rnd.uniform(0.3, 5)))
            a, b, m = project(eyes[0], p), project(eyes[1], p), project(c, p)
            worst = max(worst, abs(m[0] - (a[0] + b[0]) / 2), abs(m[1] - (a[1] + b[1]) / 2))
    # _Eye holds float32 (as the C API does): allow its rounding, scaled to the case.
    scale = max(abs(x) for x in origin + tuple(l0) + tuple(l1) + (zs,))
    ok = err < 2e-5 and pos < 1e-6 * scale and worst < 2e-5
    print("%-4s %-34s frustum err %.1e  position err %.1e  vs eye average %.1e" % ("ok" if ok else "FAIL", case, err, pos, worst))
    return ok


q = quat_axis_angle((0.3, 1.0, -0.2), 0.7)
origin_m = (0.012, -0.34, 0.055)     # rig in metres
origin_mm = (12.0, -340.0, 55.0)      # Slicer RAS mm
W = (-0.17, 0.23, -0.10, 0.12)  # window on the glass, off-centre
cases = [
    ("level, lateral", (-0.03, 0.0, 0.0), (0.03, 0.0, 0.0), -0.6, True),
    ("level, lateral + vertical (tilt)", (-0.028, -0.01, 0.0), (0.028, 0.01, 0.0), -0.6, True),
    ("depth offset (head turned)", (-0.03, 0.0, 0.01), (0.03, 0.0, -0.012), -0.6, False),
    ("vertical only", (0.0, -0.02, 0.0), (0.0, 0.02, 0.0), -0.5, True),
    ("coincident (no viewer)", (0.01, 0.1, 0.0), (0.01, 0.1, 0.0), -0.6, True),
    ("scene scale (mm)", (-30.0, 0.0, 0.0), (30.0, 0.0, 0.0), -600.0, True),
    ("mm, tilt + depth offset", (-29.0, -6.0, 8.0), (29.0, 6.0, -8.0), -600.0, False),
]
all_ok = True
for name, a, b, zs, level in cases:
    w = W if abs(zs) < 10 else tuple(x * 1000 for x in W)
    all_ok &= check(name, q, origin_mm if abs(zs) >= 10 else origin_m, a, b, w, zs, level)
print("PASS" if all_ok else "FAIL")
sys.exit(0 if all_ok else 1)
