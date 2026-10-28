// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0
//
// OpenXR session for the host app 3D window: our own D3D11 device on the GPU
// driving the panel, bound to our own window with XR_DXR_win32_window_binding
// (windowed, concurrent weaving), eyes from XR_DXR_view_rig's camera rig.
// Lives on the 3D window's thread; nothing here is thread-safe.
#pragma once

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>

#define XR_USE_PLATFORM_WIN32
#define XR_USE_GRAPHICS_API_D3D11
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <openxr/XR_DXR_display_info.h>
#include <openxr/XR_DXR_view_rig.h>
#include <openxr/XR_DXR_win32_window_binding.h>

#include <string>
#include <vector>

namespace dxr_host {

// the host app camera, in scene units, Y up, looking down -Z.
struct CameraInput
{
	XrPosef pose;
	float glassDistance; // scene units in front of the camera that land on the glass
	float ipdFactor;     // on the natural eye separation (from the depth budget)
	float verticalFov;   // radians; 0 = canvas-true from the nominal viewer
};

struct EyeView
{
	XrPosef pose; // world
	XrFovf fov;   // tangent angles (radians)
};

class Session3D
{
public:
	~Session3D();

	// Step 1: instance, system and display info (no window yet). The window
	// is then created where desktopLeft()/desktopTop() say the panel is.
	bool init(const std::wstring &loaderPath);
	// Step 2: device on the panel's GPU and a session bound to `hwnd`.
	// Texture mode (textureRef != null, XR_DXR_win32_window_binding v9): the
	// runtime weaves into a shared texture we own instead of presenting into
	// `hwnd`; `hwnd` is only the fallback anchor. The host draws the texture
	// at `rect` (device px in textureRef's client area).
	bool createSession(HWND hwnd, HWND textureRef = nullptr, XrRect2Di rect = {});
	// Texture mode: where the host draws the woven texture this frame.
	void setTarget(HWND ref, XrRect2Di rect) { ttFrame_.referenceWindow = ref, ttFrame_.targetRect = rect; }
	bool textureMode() const { return sharedTex_ != nullptr; }
	bool supportsTextureTarget() const { return ttProps_.supportsTextureTarget == XR_TRUE; }
	HANDLE sharedHandle() const { return sharedHandle_; }
	int sharedWidth() const { return (int)sharedW_; }
	int sharedHeight() const { return (int)sharedH_; }
	// XrWin32TextureTargetStateDXR flags of the most recently woven frame.
	uint64_t textureState() const { return ttState_.flags; }
	void stop();

	bool isStarted() const { return session_ != XR_NULL_HANDLE; }
	bool isRunning() const { return running_; }
	bool exitRequested() const { return exiting_; }
	const std::string &lastError() const { return error_; }
	const std::string &status() const { return status_; }
	ID3D11Device *device() const { return device_; }
	ID3D11DeviceContext *context() const { return context_; }

	// Per frame: returns true when a frame was begun; then always endFrame().
	bool beginFrame(const CameraInput &cam, int canvasW, int canvasH, EyeView eyes[2]);
	// Copies the eye textures (RGBA8 sRGB bytes, at least renderWidth x
	// renderHeight) into the swapchain and submits them with `views`, the eyes
	// they were rendered from. Null textures end the frame with no layer.
	void endFrame(ID3D11Texture2D *left, ID3D11Texture2D *right, int w, int h, const EyeView views[2]);

	float displayWidthM() const { return displayW_; }
	float displayHeightM() const { return displayH_; }
	int displayPixelWidth() const { return (int)displayPxW_; }
	int displayPixelHeight() const { return (int)displayPxH_; }
	int desktopLeft() const { return desktopX_; }
	int desktopTop() const { return desktopY_; }
	float viewerDistanceM() const { return viewerZ_; }
	float viewerHeightM() const { return viewerY_; } // nominal viewer above the glass centre
	int renderWidth() const { return renderW_; }
	int renderHeight() const { return renderH_; }

private:
	bool fail(const char *what, XrResult r);
	bool loadLoader(const std::wstring &path);
	bool createDevice();
	void pollEvents();

	HMODULE loader_ = nullptr;
	PFN_xrGetInstanceProcAddr gipa_ = nullptr;
	XrInstance instance_ = XR_NULL_HANDLE;
	XrSystemId system_ = XR_NULL_SYSTEM_ID;
	XrSession session_ = XR_NULL_HANDLE;
	XrSpace space_ = XR_NULL_HANDLE;
	XrSwapchain swapchain_ = XR_NULL_HANDLE;
	std::vector<ID3D11Texture2D *> images_;
	ID3D11Device *device_ = nullptr;
	ID3D11DeviceContext *context_ = nullptr;
	LUID adapter_{};
	DXGI_FORMAT format_ = DXGI_FORMAT_UNKNOWN;
	uint32_t maxW_ = 0, maxH_ = 0;
	int renderW_ = 0, renderH_ = 0;
	bool running_ = false;
	bool exiting_ = false;
	bool frameBegun_ = false;
	uint64_t frames_ = 0;
	XrFrameState frame_{XR_TYPE_FRAME_STATE};

	float displayW_ = 0, displayH_ = 0, viewerZ_ = 0.6f, viewerY_ = 0.0f;
	float viewScaleX_ = 1, viewScaleY_ = 1;
	uint32_t displayPxW_ = 0, displayPxH_ = 0;
	int desktopX_ = 0, desktopY_ = 0;

	std::string error_, status_ = "3D off";

	// Texture target (v9).
	XrSystemWin32TextureTargetPropertiesDXR ttProps_{(XrStructureType)XR_TYPE_SYSTEM_WIN32_TEXTURE_TARGET_PROPERTIES_DXR};
	XrWin32TextureTargetFrameDXR ttFrame_{(XrStructureType)XR_TYPE_WIN32_TEXTURE_TARGET_FRAME_DXR};
	XrWin32TextureTargetStateDXR ttState_{(XrStructureType)XR_TYPE_WIN32_TEXTURE_TARGET_STATE_DXR};
	ID3D11Texture2D *sharedTex_ = nullptr;
	HANDLE sharedHandle_ = nullptr;
	UINT sharedW_ = 0, sharedH_ = 0;

	// Entry points, all resolved through gipa_.
#define DXR_XR_FUNCS(X)                                                                                \
	X(xrEnumerateInstanceExtensionProperties) X(xrCreateInstance) X(xrDestroyInstance)                 \
	X(xrGetSystem) X(xrGetSystemProperties) X(xrCreateSession) X(xrDestroySession)                     \
	X(xrBeginSession) X(xrEndSession) X(xrRequestExitSession) X(xrPollEvent)                           \
	X(xrCreateReferenceSpace) X(xrDestroySpace) X(xrEnumerateViewConfigurationViews)                   \
	X(xrEnumerateSwapchainFormats) X(xrCreateSwapchain) X(xrDestroySwapchain)                          \
	X(xrEnumerateSwapchainImages) X(xrAcquireSwapchainImage) X(xrWaitSwapchainImage)                   \
	X(xrReleaseSwapchainImage) X(xrWaitFrame) X(xrBeginFrame) X(xrEndFrame) X(xrLocateViews)            \
	X(xrGetD3D11GraphicsRequirementsKHR)
#define DXR_DECLARE(name) PFN_##name name##_ = nullptr;
	DXR_XR_FUNCS(DXR_DECLARE)
#undef DXR_DECLARE
};

} // namespace dxr_host
