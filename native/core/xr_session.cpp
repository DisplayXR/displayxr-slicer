// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0

#include "xr_session.h"
#include "coupling.h"
#include "log.h"

#include <dxgi1_2.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

namespace dxr_host {

namespace {

const char *resultName(XrResult r)
{
	switch (r) {
	case XR_ERROR_RUNTIME_UNAVAILABLE: return "XR_ERROR_RUNTIME_UNAVAILABLE (no OpenXR runtime found)";
	case XR_ERROR_RUNTIME_FAILURE: return "XR_ERROR_RUNTIME_FAILURE";
	case XR_ERROR_EXTENSION_NOT_PRESENT: return "XR_ERROR_EXTENSION_NOT_PRESENT";
	case XR_ERROR_FORM_FACTOR_UNAVAILABLE: return "XR_ERROR_FORM_FACTOR_UNAVAILABLE (3D display not connected?)";
	case XR_ERROR_GRAPHICS_DEVICE_INVALID: return "XR_ERROR_GRAPHICS_DEVICE_INVALID (wrong GPU adapter)";
	case XR_ERROR_SESSION_LOST: return "XR_ERROR_SESSION_LOST";
	default: return nullptr;
	}
}

bool hasExtension(const std::vector<XrExtensionProperties> &exts, const char *name)
{
	for (const auto &e : exts) {
		if (std::strcmp(e.extensionName, name) == 0) {
			return true;
		}
	}
	return false;
}

} // namespace

Session3D::~Session3D() { stop(); }

bool Session3D::fail(const char *what, XrResult r)
{
	const char *n = resultName(r);
	char buf[256];
	if (n != nullptr) {
		std::snprintf(buf, sizeof(buf), "%s failed: %s", what, n);
	} else {
		std::snprintf(buf, sizeof(buf), "%s failed: XrResult %d", what, (int)r);
	}
	error_ = buf;
	logLine("ERROR %s", buf);
	return false;
}

bool Session3D::loadLoader(const std::wstring &path)
{
	if (loader_ == nullptr) {
		// Full path: never pick up whichever openxr_loader.dll another host-app
		// plug-in or the PATH put first.
		loader_ = LoadLibraryExW(path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
	}
	if (loader_ == nullptr) {
		error_ = "could not load openxr_loader.dll next to the plug-in";
		return false;
	}
	gipa_ = (PFN_xrGetInstanceProcAddr)GetProcAddress(loader_, "xrGetInstanceProcAddr");
	if (gipa_ == nullptr) {
		error_ = "openxr_loader.dll has no xrGetInstanceProcAddr";
		return false;
	}
	gipa_(XR_NULL_HANDLE, "xrEnumerateInstanceExtensionProperties",
	      (PFN_xrVoidFunction *)&xrEnumerateInstanceExtensionProperties_);
	gipa_(XR_NULL_HANDLE, "xrCreateInstance", (PFN_xrVoidFunction *)&xrCreateInstance_);
	return xrEnumerateInstanceExtensionProperties_ != nullptr && xrCreateInstance_ != nullptr;
}

bool Session3D::init(const std::wstring &loaderPath)
{
	stop();
	error_.clear();
	exiting_ = false;
	if (!loadLoader(loaderPath)) {
		logLine("ERROR %s", error_.c_str());
		return false;
	}

	uint32_t count = 0;
	XrResult r = xrEnumerateInstanceExtensionProperties_(nullptr, 0, &count, nullptr);
	if (XR_FAILED(r)) {
		return fail("xrEnumerateInstanceExtensionProperties", r);
	}
	std::vector<XrExtensionProperties> exts(count, {XR_TYPE_EXTENSION_PROPERTIES});
	xrEnumerateInstanceExtensionProperties_(nullptr, count, &count, exts.data());

	const char *required[] = {XR_KHR_D3D11_ENABLE_EXTENSION_NAME, XR_DXR_WIN32_WINDOW_BINDING_EXTENSION_NAME,
	                          XR_DXR_VIEW_RIG_EXTENSION_NAME, XR_DXR_DISPLAY_INFO_EXTENSION_NAME};
	for (const char *name : required) {
		if (!hasExtension(exts, name)) {
			error_ = std::string("the active OpenXR runtime is not DisplayXR (missing ") + name + ")";
			logLine("ERROR %s", error_.c_str());
			return false;
		}
	}

	XrInstanceCreateInfo ici{XR_TYPE_INSTANCE_CREATE_INFO};
	std::strncpy(ici.applicationInfo.applicationName, DXRH_APP_NAME, XR_MAX_APPLICATION_NAME_SIZE - 1);
	std::strncpy(ici.applicationInfo.engineName, DXRH_ENGINE_NAME, XR_MAX_ENGINE_NAME_SIZE - 1);
	ici.applicationInfo.applicationVersion = 17;
	ici.applicationInfo.apiVersion = XR_API_VERSION_1_0;
	ici.enabledExtensionCount = (uint32_t)(sizeof(required) / sizeof(required[0]));
	ici.enabledExtensionNames = required;
	r = xrCreateInstance_(&ici, &instance_);
	if (XR_FAILED(r)) {
		return fail("xrCreateInstance", r);
	}

#define DXR_RESOLVE(name) gipa_(instance_, #name, (PFN_xrVoidFunction *)&name##_);
	DXR_XR_FUNCS(DXR_RESOLVE)
#undef DXR_RESOLVE
	if (xrCreateSession_ == nullptr || xrLocateViews_ == nullptr || xrGetD3D11GraphicsRequirementsKHR_ == nullptr) {
		error_ = "OpenXR entry points missing";
		stop();
		return false;
	}

	XrSystemGetInfo sgi{XR_TYPE_SYSTEM_GET_INFO};
	sgi.formFactor = XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY;
	r = xrGetSystem_(instance_, &sgi, &system_);
	if (XR_FAILED(r)) {
		fail("xrGetSystem", r);
		stop();
		return false;
	}

	XrSystemProperties props{XR_TYPE_SYSTEM_PROPERTIES};
	XrDisplayInfoDXR info{(XrStructureType)XR_TYPE_DISPLAY_INFO_DXR};
	XrDisplayDesktopPositionDXR pos{(XrStructureType)XR_TYPE_DISPLAY_DESKTOP_POSITION_DXR};
	info.next = &pos;
	pos.next = &ttProps_;
	props.next = &info;
	if (XR_SUCCEEDED(xrGetSystemProperties_(instance_, system_, &props))) {
		displayW_ = info.displaySizeMeters.width;
		displayH_ = info.displaySizeMeters.height;
		viewerY_ = info.nominalViewerPositionInDisplaySpace.y;
		viewerZ_ = info.nominalViewerPositionInDisplaySpace.z > 0.05f ? info.nominalViewerPositionInDisplaySpace.z
		                                                               : coupling::kFallbackViewerDistanceM;
		viewScaleX_ = info.recommendedViewScaleX > 0 ? info.recommendedViewScaleX : 1.0f;
		viewScaleY_ = info.recommendedViewScaleY > 0 ? info.recommendedViewScaleY : 1.0f;
		displayPxW_ = info.displayPixelWidth;
		displayPxH_ = info.displayPixelHeight;
		desktopX_ = pos.left;
		desktopY_ = pos.top;
		logLine("texture target: supported %d, windowless phase %d", (int)ttProps_.supportsTextureTarget,
		        (int)ttProps_.windowlessPhase);
		logLine("display %.3fx%.3f m, %ux%u px at (%d,%d), viewer %.3f m, view scale %.3fx%.3f (%s)", displayW_,
		        displayH_, displayPxW_, displayPxH_, desktopX_, desktopY_, viewerZ_, viewScaleX_, viewScaleY_,
		        props.systemName);
	}

	// Required before xrCreateSession; names the GPU driving the panel.
	XrGraphicsRequirementsD3D11KHR req{XR_TYPE_GRAPHICS_REQUIREMENTS_D3D11_KHR};
	xrGetD3D11GraphicsRequirementsKHR_(instance_, system_, &req);
	adapter_ = req.adapterLuid;
	return true;
}

bool Session3D::createDevice()
{
	IDXGIFactory1 *factory = nullptr;
	if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1), reinterpret_cast<void **>(&factory)))) {
		error_ = "CreateDXGIFactory1 failed";
		return false;
	}
	IDXGIAdapter1 *adapter = nullptr;
	for (UINT i = 0; factory->EnumAdapters1(i, &adapter) != DXGI_ERROR_NOT_FOUND; i++) {
		DXGI_ADAPTER_DESC1 d{};
		adapter->GetDesc1(&d);
		if (d.AdapterLuid.LowPart == adapter_.LowPart && d.AdapterLuid.HighPart == adapter_.HighPart) {
			break;
		}
		adapter->Release();
		adapter = nullptr;
	}
	factory->Release();

	const D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
	HRESULT hr = D3D11CreateDevice(adapter, adapter ? D3D_DRIVER_TYPE_UNKNOWN : D3D_DRIVER_TYPE_HARDWARE, nullptr,
	                               D3D11_CREATE_DEVICE_BGRA_SUPPORT, levels, 2, D3D11_SDK_VERSION, &device_, nullptr,
	                               &context_);
	if (adapter != nullptr) {
		adapter->Release();
	}
	if (FAILED(hr)) {
		error_ = "D3D11CreateDevice failed on the panel's GPU";
		return false;
	}
	return true;
}

bool Session3D::createSession(HWND hwnd, HWND textureRef, XrRect2Di rect)
{
	if (instance_ == XR_NULL_HANDLE) {
		error_ = "not initialised";
		return false;
	}
	if (!createDevice()) {
		logLine("ERROR %s", error_.c_str());
		stop();
		return false;
	}

	XrGraphicsBindingD3D11KHR binding{XR_TYPE_GRAPHICS_BINDING_D3D11_KHR};
	binding.device = device_;
	XrWin32WindowBindingCreateInfoDXR win{(XrStructureType)XR_TYPE_WIN32_WINDOW_BINDING_CREATE_INFO_DXR};
	win.windowHandle = hwnd;
	binding.next = &win;
	XrWin32TextureTargetBindingDXR tt{(XrStructureType)XR_TYPE_WIN32_TEXTURE_TARGET_BINDING_DXR};
	if (textureRef != nullptr) {
		// The canvas the runtime weaves into: as big as the panel, so the target
		// rect can grow to full panel without a new session. BGRA8, legacy-shared
		// (KMT) so the host can open it on its own device (GL via WGL_NV_DX_interop2).
		sharedW_ = displayPxW_ > 0 ? displayPxW_ : 3840;
		sharedH_ = displayPxH_ > 0 ? displayPxH_ : 2160;
		D3D11_TEXTURE2D_DESC d{};
		d.Width = sharedW_;
		d.Height = sharedH_;
		d.MipLevels = 1;
		d.ArraySize = 1;
		d.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
		d.SampleDesc.Count = 1;
		d.Usage = D3D11_USAGE_DEFAULT;
		d.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
		d.MiscFlags = D3D11_RESOURCE_MISC_SHARED;
		IDXGIResource *res = nullptr;
		if (FAILED(device_->CreateTexture2D(&d, nullptr, &sharedTex_)) ||
		    FAILED(sharedTex_->QueryInterface(__uuidof(IDXGIResource), (void **)&res)) ||
		    FAILED(res->GetSharedHandle(&sharedHandle_))) {
			if (res != nullptr) {
				res->Release();
			}
			error_ = "could not create the shared texture";
			logLine("ERROR %s", error_.c_str());
			stop();
			return false;
		}
		res->Release();
		win.sharedTextureHandle = sharedHandle_;
		tt.referenceWindow = textureRef;
		tt.initialTargetRect = rect;
		win.next = &tt;
		setTarget(textureRef, rect);
	}
	XrSessionCreateInfo sci{XR_TYPE_SESSION_CREATE_INFO};
	sci.next = &binding;
	sci.systemId = system_;
	XrResult r = xrCreateSession_(instance_, &sci, &session_);
	if (XR_FAILED(r)) {
		fail("xrCreateSession", r);
		stop();
		return false;
	}

	XrReferenceSpaceCreateInfo rsci{XR_TYPE_REFERENCE_SPACE_CREATE_INFO};
	rsci.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_LOCAL;
	rsci.poseInReferenceSpace.orientation.w = 1.0f;
	xrCreateReferenceSpace_(session_, &rsci, &space_);

	uint32_t viewCount = 0;
	xrEnumerateViewConfigurationViews_(instance_, system_, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 0,
	                                   &viewCount, nullptr);
	std::vector<XrViewConfigurationView> views(viewCount, {XR_TYPE_VIEW_CONFIGURATION_VIEW});
	xrEnumerateViewConfigurationViews_(instance_, system_, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, viewCount,
	                                   &viewCount, views.data());
	if (viewCount < 2) {
		error_ = "runtime reports fewer than two views";
		stop();
		return false;
	}
	maxW_ = views[0].maxImageRectWidth;
	maxH_ = views[0].maxImageRectHeight;

	// sRGB-typed: the plug-in hands over display-referred (sRGB-encoded)
	// bytes, so a byte copy into an sRGB swapchain is the faithful hand-off.
	uint32_t fmtCount = 0;
	xrEnumerateSwapchainFormats_(session_, 0, &fmtCount, nullptr);
	std::vector<int64_t> fmts(fmtCount);
	xrEnumerateSwapchainFormats_(session_, fmtCount, &fmtCount, fmts.data());
	for (DXGI_FORMAT want : {DXGI_FORMAT_R8G8B8A8_UNORM_SRGB, DXGI_FORMAT_R8G8B8A8_UNORM}) {
		if (std::find(fmts.begin(), fmts.end(), (int64_t)want) != fmts.end()) {
			format_ = want;
			break;
		}
	}
	if (format_ == DXGI_FORMAT_UNKNOWN) {
		error_ = "runtime offers no RGBA8 swapchain format";
		stop();
		return false;
	}

	// One swapchain, side by side: left eye | right eye.
	XrSwapchainCreateInfo scci{XR_TYPE_SWAPCHAIN_CREATE_INFO};
	scci.usageFlags = XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT;
	scci.format = format_;
	scci.sampleCount = 1;
	scci.width = maxW_ * 2;
	scci.height = maxH_;
	scci.faceCount = 1;
	scci.arraySize = 1;
	scci.mipCount = 1;
	r = xrCreateSwapchain_(session_, &scci, &swapchain_);
	if (XR_FAILED(r)) {
		fail("xrCreateSwapchain", r);
		stop();
		return false;
	}
	uint32_t imgCount = 0;
	xrEnumerateSwapchainImages_(swapchain_, 0, &imgCount, nullptr);
	std::vector<XrSwapchainImageD3D11KHR> imgs(imgCount, {XR_TYPE_SWAPCHAIN_IMAGE_D3D11_KHR});
	xrEnumerateSwapchainImages_(swapchain_, imgCount, &imgCount, (XrSwapchainImageBaseHeader *)imgs.data());
	for (const auto &i : imgs) {
		images_.push_back(i.texture);
	}

	status_ = "3D starting";
	if (textureMode()) {
		logLine("texture target: reference %p, rect %d,%d %dx%d, shared %ux%u", textureRef, rect.offset.x,
		        rect.offset.y, rect.extent.width, rect.extent.height, sharedW_, sharedH_);
	}
	logLine("session created: window %p, swapchain %ux%u side by side, format %d", hwnd, maxW_ * 2, maxH_,
	        (int)format_);
	return true;
}

void Session3D::stop()
{
	if (session_ != XR_NULL_HANDLE) {
		if (running_) {
			// xrEndSession is only valid once the session is STOPPING: ask to
			// exit and let pollEvents() end it there (bounded wait), rather
			// than ending a running session (XR_ERROR_SESSION_NOT_STOPPING).
			xrRequestExitSession_(session_);
			for (int i = 0; i < 100 && running_; i++) {
				pollEvents();
				if (running_) {
					Sleep(10);
				}
			}
			if (running_) {
				logLine("session did not reach STOPPING in 1 s; ending it anyway");
				xrEndSession_(session_);
			}
		}
		if (swapchain_ != XR_NULL_HANDLE) {
			xrDestroySwapchain_(swapchain_);
		}
		if (space_ != XR_NULL_HANDLE) {
			xrDestroySpace_(space_);
		}
		xrDestroySession_(session_);
		logLine("session destroyed");
	}
	if (instance_ != XR_NULL_HANDLE) {
		xrDestroyInstance_(instance_);
	}
	if (sharedTex_ != nullptr) {
		sharedTex_->Release();
	}
	sharedTex_ = nullptr;
	sharedHandle_ = nullptr;
	sharedW_ = sharedH_ = 0;
	if (context_ != nullptr) {
		context_->Release();
	}
	if (device_ != nullptr) {
		device_->Release();
	}
	context_ = nullptr;
	device_ = nullptr;
	session_ = XR_NULL_HANDLE;
	swapchain_ = XR_NULL_HANDLE;
	space_ = XR_NULL_HANDLE;
	instance_ = XR_NULL_HANDLE;
	system_ = XR_NULL_SYSTEM_ID;
	images_.clear();
	running_ = false;
	frameBegun_ = false;
	frames_ = 0;
	status_ = "3D off";
	// The loader stays loaded: unloading it while the runtime has threads
	// winding down is a crash we gain nothing from avoiding.
}

void Session3D::pollEvents()
{
	XrEventDataBuffer ev{XR_TYPE_EVENT_DATA_BUFFER};
	while (instance_ != XR_NULL_HANDLE && xrPollEvent_(instance_, &ev) == XR_SUCCESS) {
		if (ev.type == XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED) {
			const auto &sc = *reinterpret_cast<const XrEventDataSessionStateChanged *>(&ev);
			switch (sc.state) {
			case XR_SESSION_STATE_READY: {
				XrSessionBeginInfo bi{XR_TYPE_SESSION_BEGIN_INFO};
				bi.primaryViewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
				XrResult r = xrBeginSession_(session_, &bi);
				running_ = XR_SUCCEEDED(r);
				status_ = running_ ? "3D active" : "3D failed to start";
				logLine("session READY -> begin: %d", (int)r);
				break;
			}
			case XR_SESSION_STATE_STOPPING:
				xrEndSession_(session_);
				running_ = false;
				status_ = "3D paused";
				logLine("session STOPPING");
				break;
			case XR_SESSION_STATE_EXITING:
			case XR_SESSION_STATE_LOSS_PENDING:
				running_ = false;
				exiting_ = true;
				status_ = "3D off";
				logLine("session EXITING/LOSS_PENDING");
				break;
			case XR_SESSION_STATE_FOCUSED: status_ = "3D active"; break;
			default: break;
			}
		} else if (ev.type == XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING) {
			running_ = false;
			exiting_ = true;
			status_ = "3D off";
		}
		ev = {XR_TYPE_EVENT_DATA_BUFFER};
	}
}

bool Session3D::beginFrame(const CameraInput &cam, int canvasW, int canvasH, EyeView eyes[2])
{
	pollEvents();
	if (!running_ || frameBegun_) {
		return false;
	}

	XrFrameWaitInfo wi{XR_TYPE_FRAME_WAIT_INFO};
	frame_ = {XR_TYPE_FRAME_STATE};
	if (textureMode()) {
		ttState_.next = nullptr;
		frame_.next = &ttState_; // what the runtime did with the last woven frame
	}
	if (XR_FAILED(xrWaitFrame_(session_, &wi, &frame_))) {
		return false;
	}
	XrFrameBeginInfo bi{XR_TYPE_FRAME_BEGIN_INFO};
	if (XR_FAILED(xrBeginFrame_(session_, &bi))) {
		return false;
	}
	frameBegun_ = true;

	renderW_ = std::clamp((int)std::lround(canvasW * viewScaleX_), 16, (int)maxW_);
	renderH_ = std::clamp((int)std::lround(canvasH * viewScaleY_), 16, (int)maxH_);

	// True-geometry camera rig: the window is a 1:1 portal, so the frustum's
	// vertical FOV is what the canvas subtends from the nominal viewer, and
	// one physical metre maps to (glass distance / viewer distance) world
	// units, which puts the chosen distance exactly on the glass.
	const float coi = std::max(cam.glassDistance, 1e-4f);
	float canvasHm = 0.0f;
	if (displayPxH_ > 0 && displayH_ > 0.0f) {
		canvasHm = displayH_ * (float)canvasH / (float)displayPxH_;
	}
	if (canvasHm <= 0.0f) {
		canvasHm = 0.2f;
	}

	XrCameraRigDXR rig{(XrStructureType)XR_TYPE_CAMERA_RIG_DXR};
	rig.pose = cam.pose;
	rig.ipdFactor = std::max(cam.ipdFactor, 0.0f);
	rig.parallaxFactor = 1.0f;
	rig.convergenceDiopters = 1.0f / coi;
	const float vfov = cam.verticalFov > 0.0f ? cam.verticalFov : 2.0f * std::atan(canvasHm * 0.5f / viewerZ_);
	rig.verticalFov = vfov;
	rig.metersToVirtual = 2.0f * coi * std::tan(vfov * 0.5f) / canvasHm;
	if (textureMode()) {
		rig.next = &ttFrame_; // frame the views to this frame's target
	}

	XrViewLocateInfo li{XR_TYPE_VIEW_LOCATE_INFO};
	li.next = &rig;
	li.viewConfigurationType = XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO;
	li.displayTime = frame_.predictedDisplayTime;
	li.space = space_;
	XrViewState vs{XR_TYPE_VIEW_STATE};
	XrView views[2] = {{XR_TYPE_VIEW}, {XR_TYPE_VIEW}};
	uint32_t n = 0;
	if (XR_SUCCEEDED(xrLocateViews_(session_, &li, &vs, 2, &n, views)) && n >= 2) {
		for (int i = 0; i < 2; i++) {
			eyes[i].pose = views[i].pose;
			eyes[i].fov = views[i].fov;
		}
	}
	return true;
}

void Session3D::endFrame(ID3D11Texture2D *left, ID3D11Texture2D *right, int w, int h, const EyeView views[2])
{
	if (!frameBegun_) {
		return;
	}
	frameBegun_ = false;
	frames_++;

	XrCompositionLayerProjectionView pv[2] = {{XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW},
	                                          {XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW}};
	XrCompositionLayerProjection layer{XR_TYPE_COMPOSITION_LAYER_PROJECTION};
	const XrCompositionLayerBaseHeader *layers[1] = {reinterpret_cast<const XrCompositionLayerBaseHeader *>(&layer)};
	XrFrameEndInfo ei{XR_TYPE_FRAME_END_INFO};
	ei.displayTime = frame_.predictedDisplayTime;
	ei.environmentBlendMode = XR_ENVIRONMENT_BLEND_MODE_OPAQUE;
	if (textureMode()) {
		ttFrame_.next = nullptr;
		ei.next = &ttFrame_; // authoritative target for this frame
	}

	w = std::min(w, (int)maxW_);
	h = std::min(h, (int)maxH_);
	if (frame_.shouldRender && left != nullptr && right != nullptr && w > 0 && h > 0) {
		uint32_t idx = 0;
		XrSwapchainImageAcquireInfo ai{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
		XrSwapchainImageWaitInfo wi{XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO};
		wi.timeout = XR_INFINITE_DURATION;
		if (XR_SUCCEEDED(xrAcquireSwapchainImage_(swapchain_, &ai, &idx)) &&
		    XR_SUCCEEDED(xrWaitSwapchainImage_(swapchain_, &wi))) {
			D3D11_BOX box{0, 0, 0, (UINT)w, (UINT)h, 1};
			ID3D11Texture2D *src[2] = {left, right};
			for (UINT eye = 0; eye < 2; eye++) {
				context_->CopySubresourceRegion(images_[idx], 0, eye * (UINT)w, 0, 0, src[eye], 0, &box);
			}
			// The runtime reads the image from its own thread; submit the copy first.
			context_->Flush();
			XrSwapchainImageReleaseInfo ri{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
			xrReleaseSwapchainImage_(swapchain_, &ri);

			for (uint32_t eye = 0; eye < 2; eye++) {
				pv[eye].pose = views[eye].pose;
				pv[eye].fov = views[eye].fov;
				pv[eye].subImage.swapchain = swapchain_;
				pv[eye].subImage.imageRect = {{(int32_t)eye * w, 0}, {w, h}};
				pv[eye].subImage.imageArrayIndex = 0;
			}
			layer.space = space_;
			layer.viewCount = 2;
			layer.views = pv;
			ei.layerCount = 1;
			ei.layers = layers;
		}
	}
	if (frames_ % 300 == 1) {
		logLine("frame %llu: %s, eye %dx%d (window wants %dx%d)", (unsigned long long)frames_,
		        ei.layerCount ? "3D layer" : "no layer", w, h, renderW_, renderH_);
		if (textureMode()) {
			// WINDOWLESS_PHASE 1, ANCHOR_FALLBACK 2, SEGMENTED 4, FLAT_SEGMENT 8, CLAMPED 16.
			logLine("  texture target: rect %d,%d %dx%d, state flags 0x%llx, woven at (%d,%d)",
			        ttFrame_.targetRect.offset.x, ttFrame_.targetRect.offset.y, ttFrame_.targetRect.extent.width,
			        ttFrame_.targetRect.extent.height, (unsigned long long)ttState_.flags,
			        ttState_.wovenScreenOrigin.x, ttState_.wovenScreenOrigin.y);
		}
	}
	XrResult r = xrEndFrame_(session_, &ei);
	if (XR_FAILED(r)) {
		static int logged = 0;
		if (logged++ < 3) {
			logLine("xrEndFrame failed: %d", (int)r);
		}
	}
}

} // namespace dxr_host
