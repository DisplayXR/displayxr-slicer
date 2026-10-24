"""Disparity of yellow spheres in a projection atlas: centroid per blob, L vs R."""
import sys
import numpy as np
from PIL import Image
from scipy import ndimage
im = np.asarray(Image.open(sys.argv[1]).convert("RGB"), dtype=np.int16)
H, W, _ = im.shape; w = W // 2
def blobs(v):
    r, g, b = v[..., 0], v[..., 1], v[..., 2]
    mask = (r > 120) & (g > 90) & (b < 0.6 * g) & (r - b > 60)
    mask = ndimage.binary_closing(mask, iterations=4)
    lab, n = ndimage.label(mask)
    out = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        if len(xs) > 200:
            out.append((xs.mean(), ys.mean(), len(xs), xs.min(), xs.max()))
    return sorted(out)
Lb, Rb = blobs(im[:, :w]), blobs(im[:, w:])
print("L", len(Lb), "R", len(Rb))
for l in Lb:
    r = min(Rb, key=lambda r: abs(r[1] - l[1]) + abs(r[0] - l[0]))
    # use blob extents' centre (robust to shading)
    lc, rc = (l[3] + l[4]) / 2, (r[3] + r[4]) / 2
    cd = r[0] - l[0]
    print(f"x {l[0]:7.1f} y {l[1]:6.1f} n {l[2]:6d}  extents {rc - lc:+6.2f} px  centroid {cd:+6.2f} px = {100 * cd / w:+.4f} %")
