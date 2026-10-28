// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0
//
// Depth math for the true-geometry rig (comfort budget: issue #2388). Pure
// functions, no OpenXR or the host app, so tests/test_rig.cpp can check them.
#pragma once

namespace dxr_host::rig {

struct Budget
{
	double displayWidthM; // panel width
	double front;         // allowed parallax in front of the glass, fraction of panel width
	double behind;        // behind
};

// Screen parallax of a point at view depth z for physical eye separation e
// and the glass at g, as a fraction of the panel width (positive = behind):
//   p(z) = (e / W) * (1 - g / z)
double parallax(double e, double W, double g, double z);

// The largest eye separation (m, at most `natural`) that keeps content in
// [zn, zf] inside the budget with the glass at g. zf <= 0 = unknown content:
// returns `natural`.
double comfortSeparation(const Budget &b, double g, double zn, double zf, double natural);

struct Result
{
	double separationM; // physical eye separation to use
	double ipdFactor;   // separationM / natural
	double frontPct;    // % of panel width in front of the glass, at zn
	double behindPct;   // behind, at zf
};

// strength scales the budgeted separation (1 = budget filled); it is clamped
// to [0, 1] unless allowAboveComfort.
Result solve(const Budget &b, double g, double zn, double zf, double natural, double strength, bool allowAboveComfort);

// Vertical FOV of a window that is a 1:1 portal on the panel, seen from the
// nominal viewer: 2 atan(h / 2 / d).
double portalVerticalFov(double windowHeightM, double viewerDistanceM);

} // namespace dxr_host::rig
