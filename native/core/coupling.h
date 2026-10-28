// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0
//
// Everything the host core depends on that is NOT a published contract of
// DisplayXR or the host app. Each entry is "not a contract": it can change
// under us with an app or runtime update, so keep them here and nowhere else.
#pragma once

// Host app identity, set per adapter by build.bat (/D...). The core itself is
// app-neutral: the seed of a shared host library (Discussion #2423).
#ifndef DXRH_APP_NAME
#define DXRH_APP_NAME "Autodesk MotionBuilder"
#endif
#ifndef DXRH_ENGINE_NAME
#define DXRH_ENGINE_NAME "displayxr-motionbuilder"
#endif
#ifndef DXRH_WINDOW_CLASS
#define DXRH_WINDOW_CLASS L"DisplayXR_MotionBuilder_3D"
#endif
#ifndef DXRH_WINDOW_TITLE
#define DXRH_WINDOW_TITLE L"MotionBuilder 3D - DisplayXR"
#endif
#ifndef DXRH_LOG_NAME
#define DXRH_LOG_NAME "displayxr-motionbuilder.log"
#endif

namespace dxr_host::coupling {

// DisplayXR: picks the runtime manifest for this process only (Khronos
// loader; ignored in elevated processes). Never touch ActiveRuntime.
inline constexpr const char *kRuntimeJsonEnv = "XR_RUNTIME_JSON";

// DisplayXR shared depth slider (runtime #2350 convention, tools/
// DisplayXR-DepthSlider.ps1): window properties on our 3D window. Relative
// pair: strength*1000 | focus_mm << 16, strength relative to our nominal
// (1.0 = comfort budget filled). Not a contract.
inline constexpr const wchar_t *kHostedDepthRelProp = L"DXR_HostedDepthRel";
inline constexpr const wchar_t *kHostedDepthRelNowProp = L"DXR_HostedDepthRelNow";

// DisplayXR: nominal viewer distance used when the runtime reports none (m).
inline constexpr float kFallbackViewerDistanceM = 0.6f;

// DisplayXR: panel width used when the runtime reports none (m).
inline constexpr double kFallbackDisplayWidthM = 0.344;

// DisplayXR: comfort budget, as a fraction of panel width in front of and
// behind the glass (calibrated with the user on the Leia panel, 2026-10-23).
// XR_DXR_display_info does not publish a budget yet (requested as
// layout.comfort {front_frac, behind_frac}); swap these for it when it does.
inline constexpr double kComfortFront = 0.0014;
inline constexpr double kComfortBehind = 0.0042;

// Natural eye separation the runtime's ipdFactor scales (m).
inline constexpr double kNaturalIpdM = 0.063;

// Our 3D window's class and title (scripts and tests find it by these).
inline constexpr const wchar_t *kWindowClass = DXRH_WINDOW_CLASS;
inline constexpr const wchar_t *kWindowTitle = DXRH_WINDOW_TITLE;

} // namespace dxr_host::coupling
