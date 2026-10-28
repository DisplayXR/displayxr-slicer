// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0
//
// Checks the depth math against the comfort budget. Build and run with
// build.bat test.

#include "../core/rig.h"

#include <cmath>
#include <cstdio>

using namespace dxr_host::rig;

static int g_failed = 0;

static void check(bool ok, const char *what)
{
	std::printf("%s  %s\n", ok ? "ok  " : "FAIL", what);
	g_failed += ok ? 0 : 1;
}

static bool near(double a, double b, double tol = 1e-9) { return std::fabs(a - b) <= tol; }

int main()
{
	const Budget b{0.344, 0.0014, 0.0042};
	const double nat = 0.063;

	// Unknown content keeps the natural separation.
	check(near(comfortSeparation(b, 10.0, 0.0, 0.0, nat), nat), "unknown content -> natural IPD");

	// Content exactly on the glass has no parallax: natural separation.
	check(near(comfortSeparation(b, 10.0, 10.0, 10.0, nat), nat), "flat content on glass -> natural IPD");

	// Deep content: the budget is filled exactly at both ends it limits.
	const double g = 10.0, zn = 8.0, zf = 20.0;
	Result r = solve(b, g, zn, zf, nat, 1.0, false);
	const double pn = -parallax(r.separationM, b.displayWidthM, g, zn);
	const double pf = parallax(r.separationM, b.displayWidthM, g, zf);
	check(pn <= b.front + 1e-12 && pf <= b.behind + 1e-12, "within budget at near and far");
	check(near(pn, b.front, 1e-12) || near(pf, b.behind, 1e-12), "budget filled at the limiting end");
	check(near(r.frontPct, 100.0 * pn, 1e-9) && near(r.behindPct, 100.0 * pf, 1e-9), "reported percentages");

	// Strength scales linearly and clamps at 1 without the opt-in.
	Result half = solve(b, g, zn, zf, nat, 0.5, false);
	check(near(half.separationM, 0.5 * r.separationM, 1e-12), "50 % strength halves separation");
	Result over = solve(b, g, zn, zf, nat, 1.8, false);
	check(near(over.separationM, r.separationM, 1e-12), "180 % clamped to 100 % without opt-in");
	Result opt = solve(b, g, zn, zf, nat, 1.8, true);
	check(near(opt.separationM, 1.8 * r.separationM, 1e-12), "180 % allowed with explicit opt-in");

	// Scale invariance: same scene in other units gives the same separation.
	Result cm = solve(b, g * 100, zn * 100, zf * 100, nat, 1.0, false);
	check(near(cm.separationM, r.separationM, 1e-12), "unit independent");

	// 1:1 portal: a 0.2 m tall window at 0.6 m.
	check(near(portalVerticalFov(0.2, 0.6), 2.0 * std::atan(0.1 / 0.6)), "portal vertical FOV");

	std::printf(g_failed ? "%d FAILED\n" : "all passed\n", g_failed);
	return g_failed ? 1 : 0;
}
