// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0

#include "rig.h"

#include <algorithm>
#include <cmath>

namespace dxr_host::rig {

double parallax(double e, double W, double g, double z) { return (e / W) * (1.0 - g / z); }

double comfortSeparation(const Budget &b, double g, double zn, double zf, double natural)
{
	double e = natural;
	if (zf <= 0.0 || g <= 0.0) {
		return e;
	}
	zn = std::max(zn, 1e-6);
	if (zn < g) {
		e = std::min(e, b.front * b.displayWidthM / (g / zn - 1.0));
	}
	if (zf > g) {
		e = std::min(e, b.behind * b.displayWidthM / (1.0 - g / zf));
	}
	return e;
}

Result solve(const Budget &b, double g, double zn, double zf, double natural, double strength, bool allowAboveComfort)
{
	strength = std::clamp(strength, 0.0, allowAboveComfort ? 2.0 : 1.0);
	Result r{};
	r.separationM = comfortSeparation(b, g, zn, zf, natural) * strength;
	r.ipdFactor = natural > 0.0 ? r.separationM / natural : 0.0;
	const double W = b.displayWidthM;
	r.frontPct = (zf > 0.0 && zn > 0.0 && zn < g) ? -100.0 * parallax(r.separationM, W, g, zn) : 0.0;
	r.behindPct = (zf > g) ? 100.0 * parallax(r.separationM, W, g, zf) : 0.0;
	return r;
}

double portalVerticalFov(double windowHeightM, double viewerDistanceM)
{
	return 2.0 * std::atan(windowHeightM * 0.5 / std::max(viewerDistanceM, 0.05));
}

} // namespace dxr_host::rig
