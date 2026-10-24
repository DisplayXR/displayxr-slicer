"""Measure horizontal parallax in a DisplayXR projection atlas (L|R side by side).
Block matching on luminance; prints percentiles of disparity as % of view width.
Positive = uncrossed (behind the screen), negative = crossed (in front)."""
import sys
import numpy as np
from PIL import Image

im = np.asarray(Image.open(sys.argv[1]).convert("L"), dtype=np.float32)
H, W = im.shape
w = W // 2
L, R = im[:, :w], im[:, w:]
B, S = 48, int(sys.argv[2]) if len(sys.argv) > 2 else 40   # block size, search +-px
ds = []
for y in range(B, H - B, B // 2):
    for x in range(S + B, w - S - B, B // 2):
        blk = L[y:y + B, x:x + B]
        if blk.std() < 12:          # skip flat background
            continue
        best, bd = None, 1e18
        for d in range(-S, S + 1):
            c = R[y:y + B, x + d:x + d + B]
            e = np.abs(c - blk).mean()
            if e < bd:
                bd, best = e, d
        # sub-pixel parabola
        if -S < best < S:
            e0 = np.abs(R[y:y+B, x+best-1:x+best-1+B] - blk).mean()
            e2 = np.abs(R[y:y+B, x+best+1:x+best+1+B] - blk).mean()
            den = e0 - 2 * bd + e2
            sub = 0.5 * (e0 - e2) / den if den > 1e-6 else 0
        else:
            sub = 0
        if bd < 0.5 * blk.std():
            ds.append(best + sub)
ds = np.array(ds)
pc = lambda q: np.percentile(ds, q) / w * 100
print(f"views {w}x{H}, blocks {len(ds)}")
print("disparity px  p1 %.2f  p5 %.2f  p50 %.2f  p95 %.2f  p99 %.2f" % tuple(np.percentile(ds, q) for q in (1, 5, 50, 95, 99)))
print("as %% width   p1 %.3f  p5 %.3f  p50 %.3f  p95 %.3f  p99 %.3f" % tuple(pc(q) for q in (1, 5, 50, 95, 99)))
