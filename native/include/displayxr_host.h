// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0
//
// C API of displayxr_host.dll: one 3D window per host-app session, driven by
// the host app plug-in (which submits the eye images) and by the
// Python side (ctypes: start/stop, camera, depth, eyes for the stereo rig).
// Both load the same DLL in the host app's process, so they share one state.
//
// Units: poses and distances are in host scene units, Y up, camera looking
// down -Z. Angles in radians. Images are RGBA8, sRGB-encoded, top row first.
#pragma once

#include <stdint.h>

#ifdef DXRH_BUILD
#define DXRH_API __declspec(dllexport)
#else
#define DXRH_API __declspec(dllimport)
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct dxrh_pose
{
	float px, py, pz;     // position
	float qx, qy, qz, qw; // orientation
} dxrh_pose;

// The host app camera the user looks through.
typedef struct dxrh_camera
{
	dxrh_pose pose;
	float vertical_fov;   // full vertical angle the app camera frames (0 = canvas-true from the viewer)
	float glass_distance; // scene units in front of the camera that land on the glass (0 = keep last)
	float near_z, far_z;  // visible content depth range along the view (0, 0 = keep the last measured)
} dxrh_camera;

// One eye as the stereo rig must render it.
typedef struct dxrh_eye
{
	dxrh_pose pose;                                // world (scene units)
	float angle_left, angle_right, angle_up, angle_down; // tangent angles, OpenXR XrFovf
} dxrh_eye;

typedef struct dxrh_depth_info
{
	float strength;       // 1 = the whole comfort budget for what's in view
	float glass;          // scene units
	float front_pct;      // parallax in front of the glass, % of panel width
	float behind_pct;     // behind
	float ipd_factor;     // on the runtime's natural eye separation
} dxrh_depth_info;

// Opens the 3D window on the panel and starts the OpenXR session on its own
// thread. Returns 0 on success; on failure dxrh_status() has the reason.
DXRH_API int dxrh_start(void);
DXRH_API void dxrh_stop(void);

// Texture mode (the standard target, XR_DXR_win32_window_binding v9, runtime
// v2.55+): no 3D window. The runtime weaves into a shared D3D11 texture that
// the host draws itself, pixel-exact, at a rect of its own window:
// `reference_window` (top-level, this process) and x, y, width, height in
// device pixels of its client area. Returns 0 on success.
DXRH_API int dxrh_start_in_viewport(void *reference_window, int x, int y, int width, int height);
// Where the host draws it now (call when the viewport moves or resizes).
DXRH_API void dxrh_set_target(void *reference_window, int x, int y, int width, int height);
// The last target set (also before start). Returns 0 when none was set.
DXRH_API int dxrh_get_target(void **reference_window, int *x, int *y, int *width, int *height);
// The woven texture: a legacy (KMT) shared handle to a BGRA8 texture as big
// as the panel; the frame occupies (0, 0, target width, target height).
// state_flags = XrWin32TextureTargetStateDXR flags of the last woven frame
// (1 windowless phase, 2 anchor fallback, 4 segmented, 8 flat segment,
// 16 clamped). Returns 0 when not running in texture mode.
DXRH_API int dxrh_texture_info(void **shared_handle, int *width, int *height, uint64_t *state_flags);
// Window mode only: full panel and back (the 3D window's F11).
DXRH_API void dxrh_toggle_fullscreen(void);
DXRH_API int dxrh_is_running(void);
// "3D active", "3D paused", "3D off" or an error. Returns the length.
DXRH_API int dxrh_status(char *buf, int size);

DXRH_API void dxrh_set_camera(const dxrh_camera *cam);
// Depth range of what the camera sees (scene units along the view), measured
// by the plug-in from the rendered depth. far <= 0 = unknown: natural IPD.
DXRH_API void dxrh_set_content_depth(float near_z, float far_z);
// strength in [0, 2]; above 1 only with allow_above_comfort (the plug-in's
// own explicit opt-in). The shared slider (DXR_HostedDepthRel) is clamped to 1.
DXRH_API void dxrh_set_depth(float strength, int allow_above_comfort);
DXRH_API void dxrh_get_depth(dxrh_depth_info *out);

// Latest eyes from xrLocateViews. `serial` identifies them; pass it back with
// the images rendered from them. Returns 0 until the session has located views.
DXRH_API int dxrh_get_eyes(dxrh_eye eyes[2], uint32_t *serial);
// Per-eye pixel size the window wants (aspect = the window's).
DXRH_API int dxrh_render_size(int *width, int *height);
// The 3D window's client size in physical panel pixels (for depth framing).
DXRH_API int dxrh_window_size(int *width, int *height);

// Hands one stereo pair to the 3D window; copied, so the caller may free.
DXRH_API int dxrh_submit_rgba8(const uint8_t *left, const uint8_t *right, int width, int height, int stride,
                               uint32_t serial);

// Same, from two image files (PNG/TIFF/JPEG/BMP via WIC; 8-bit sRGB).
// For hosts that can't run a native plug-in (a Python-only path): Python
// renders the eyes to files and hands them over. Returns 0 on success.
DXRH_API int dxrh_submit_files(const wchar_t *left, const wchar_t *right, uint32_t serial);

// Input in the 3D window, so the user can navigate there with the host
// app's own controls (the adapter replays it into the app's viewer).
typedef enum dxrh_input_type
{
	DXRH_INPUT_PRESS = 0,   // mouse button down
	DXRH_INPUT_RELEASE = 1, // mouse button up
	DXRH_INPUT_MOVE = 2,    // mouse moved (consecutive moves are merged)
	DXRH_INPUT_WHEEL = 3,   // wheel; `wheel` in notches * 120 (WHEEL_DELTA), + = away from the user
	DXRH_INPUT_DOUBLE = 4,  // double click
	DXRH_INPUT_KEY = 5,     // key down; `key` = Windows virtual-key code
} dxrh_input_type;

#define DXRH_MOD_SHIFT 1
#define DXRH_MOD_CTRL 2
#define DXRH_MOD_ALT 4

typedef struct dxrh_input
{
	int type;     // dxrh_input_type
	int button;   // 1 left, 2 middle, 3 right (0 for move/wheel/key)
	int modifiers; // DXRH_MOD_*
	float x, y;   // 0..1 over the 3D window's client area, top-left origin
	int wheel;
	int key;
} dxrh_input;

// Takes up to `max` queued events (oldest first). Returns how many.
DXRH_API int dxrh_poll_input(dxrh_input *events, int max);

// First connected XInput gamepad, sticks in [-1, 1] with the dead zone
// removed, triggers in [0, 1]. Returns 0 when no pad is connected.
typedef struct dxrh_gamepad
{
	float lx, ly, rx, ry; // + = right / up
	float lt, rt;
	unsigned buttons;     // XINPUT_GAMEPAD_* bits
} dxrh_gamepad;
DXRH_API int dxrh_get_gamepad(dxrh_gamepad *out);

#ifdef __cplusplus
}
#endif
