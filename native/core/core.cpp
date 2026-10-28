// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0
//
// The 3D window: its own thread, its own top-level window on the panel, the
// OpenXR frame loop, and the C API (include/displayxr_host.h) that the host app's
// plug-in and Python use to feed it. The host app renders at its own pace; the
// window keeps weaving the latest pair at display rate, each submitted with
// the eyes it was rendered from.

#include "../../include/displayxr_host.h"
#include "coupling.h"
#include "log.h"
#include "rig.h"
#include "xr_session.h"

#include <wincodec.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstring>
#include <future>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace dxr_host {

namespace {

constexpr int kEyeRing = 64;

struct Shared
{
	std::mutex mutex;
	dxrh_camera cam{{0, 0, 0, 0, 0, 0, 1}, 0.0f, 1.0f, 0.0f, 0.0f};
	float strength = 1.0f;
	bool allowAbove = false;
	dxrh_depth_info depth{};
	EyeView eyes[kEyeRing][2]{};
	uint32_t serial = 0; // of the newest eyes; 0 = none yet
	int renderW = 0, renderH = 0;
	int windowW = 0, windowH = 0;
	std::string status = "3D off";

	std::vector<dxrh_input> input; // 3D window -> adapter

	// Texture mode: the host's window and the rect it draws the woven texture at.
	bool textureMode = false;
	HWND targetRef = nullptr;
	RECT target{};
	HANDLE sharedHandle = nullptr;
	int sharedW = 0, sharedH = 0;
	uint64_t textureState = 0;

	std::vector<uint8_t> pending[2];
	int pendingW = 0, pendingH = 0;
	uint32_t pendingSerial = 0;
	bool fresh = false;
};

Shared g;
std::thread g_thread;
std::atomic<bool> g_quit{false};
std::atomic<bool> g_running{false};
std::atomic<HWND> g_hwnd{nullptr};

std::wstring moduleDir()
{
	HMODULE self = nullptr;
	GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
	                   reinterpret_cast<LPCWSTR>(&moduleDir), &self);
	wchar_t path[MAX_PATH] = {};
	GetModuleFileNameW(self, path, MAX_PATH);
	std::wstring dir(path);
	return dir.substr(0, dir.find_last_of(L"\\/") + 1);
}

void setStatus(const std::string &s)
{
	std::lock_guard<std::mutex> lock(g.mutex);
	g.status = s;
}

// F11: borderless over the whole monitor the window is on, and back.
void toggleFullscreen(HWND hwnd)
{
	static WINDOWPLACEMENT saved{sizeof(WINDOWPLACEMENT)};
	const LONG style = GetWindowLongW(hwnd, GWL_STYLE);
	if (style & WS_OVERLAPPEDWINDOW) {
		MONITORINFO mi{sizeof(mi)};
		GetWindowPlacement(hwnd, &saved);
		GetMonitorInfoW(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &mi);
		SetWindowLongW(hwnd, GWL_STYLE, style & ~WS_OVERLAPPEDWINDOW);
		SetWindowPos(hwnd, HWND_TOP, mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right - mi.rcMonitor.left,
		             mi.rcMonitor.bottom - mi.rcMonitor.top, SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
	} else {
		SetWindowLongW(hwnd, GWL_STYLE, style | WS_OVERLAPPEDWINDOW);
		SetWindowPlacement(hwnd, &saved);
		SetWindowPos(hwnd, nullptr, 0, 0, 0, 0,
		             SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED);
	}
}

int modifiers()
{
	return ((GetKeyState(VK_SHIFT) & 0x8000) ? DXRH_MOD_SHIFT : 0) |
	       ((GetKeyState(VK_CONTROL) & 0x8000) ? DXRH_MOD_CTRL : 0) |
	       ((GetKeyState(VK_MENU) & 0x8000) ? DXRH_MOD_ALT : 0);
}

// Queues one input event for the adapter; client pixels -> 0..1.
void pushInput(HWND hwnd, int type, int button, int x, int y, int wheel = 0, int key = 0)
{
	RECT rc{};
	GetClientRect(hwnd, &rc);
	const float w = (float)std::max<LONG>(1, rc.right), h = (float)std::max<LONG>(1, rc.bottom);
	dxrh_input e{type, button, modifiers(), x / w, y / h, wheel, key};
	std::lock_guard<std::mutex> lock(g.mutex);
	if (type == DXRH_INPUT_MOVE && !g.input.empty() && g.input.back().type == DXRH_INPUT_MOVE) {
		g.input.back() = e;
	} else if (g.input.size() < 1024) {
		g.input.push_back(e);
	}
}

LRESULT CALLBACK wndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
	const int mx = (short)LOWORD(lp), my = (short)HIWORD(lp);
	switch (msg) {
	case WM_LBUTTONDOWN:
	case WM_MBUTTONDOWN:
	case WM_RBUTTONDOWN:
		SetCapture(hwnd);
		pushInput(hwnd, DXRH_INPUT_PRESS, msg == WM_LBUTTONDOWN ? 1 : msg == WM_MBUTTONDOWN ? 2 : 3, mx, my);
		return 0;
	case WM_LBUTTONUP:
	case WM_MBUTTONUP:
	case WM_RBUTTONUP:
		pushInput(hwnd, DXRH_INPUT_RELEASE, msg == WM_LBUTTONUP ? 1 : msg == WM_MBUTTONUP ? 2 : 3, mx, my);
		if ((wp & (MK_LBUTTON | MK_MBUTTON | MK_RBUTTON)) == 0) {
			ReleaseCapture();
		}
		return 0;
	case WM_LBUTTONDBLCLK:
	case WM_MBUTTONDBLCLK:
	case WM_RBUTTONDBLCLK:
		pushInput(hwnd, DXRH_INPUT_DOUBLE, msg == WM_LBUTTONDBLCLK ? 1 : msg == WM_MBUTTONDBLCLK ? 2 : 3, mx, my);
		return 0;
	case WM_MOUSEMOVE: pushInput(hwnd, DXRH_INPUT_MOVE, 0, mx, my); return 0;
	case WM_MOUSEWHEEL: {
		POINT p{mx, my}; // screen coordinates for wheel messages
		ScreenToClient(hwnd, &p);
		pushInput(hwnd, DXRH_INPUT_WHEEL, 0, p.x, p.y, GET_WHEEL_DELTA_WPARAM(wp));
		return 0;
	}
	case WM_SYSKEYDOWN:
		// Alt is a navigation modifier (Maya-style keymaps): don't open the window menu.
		if (wp == VK_MENU) {
			return 0;
		}
		break;
	case WM_SYSCOMMAND:
		if ((wp & 0xFFF0) == SC_KEYMENU) {
			return 0;
		}
		break;
	default: break;
	}
	switch (msg) {
	case WM_KEYDOWN:
		if (wp == VK_F11) {
			toggleFullscreen(hwnd);
			return 0;
		}
		if (wp != VK_ESCAPE && wp != VK_SHIFT && wp != VK_CONTROL && wp != VK_MENU) {
			pushInput(hwnd, DXRH_INPUT_KEY, 0, 0, 0, 0, (int)wp);
		}
		if (wp == VK_ESCAPE) {
			// Esc leaves full screen only; closing the window stops 3D.
			if (!(GetWindowLongW(hwnd, GWL_STYLE) & WS_OVERLAPPEDWINDOW)) {
				toggleFullscreen(hwnd);
			}
			return 0;
		}
		break;
	case WM_CLOSE: g_quit = true; return 0;
	case WM_ERASEBKGND: return 1; // the runtime presents into us
	default: break;
	}
	return DefWindowProcW(hwnd, msg, wp, lp);
}

HWND createWindow(const Session3D &s)
{
	WNDCLASSEXW wc{sizeof(wc)};
	wc.style = CS_DBLCLKS;
	wc.lpfnWndProc = wndProc;
	wc.hInstance = GetModuleHandleW(nullptr);
	wc.hCursor = LoadCursorW(nullptr, MAKEINTRESOURCEW(32512)); // IDC_ARROW
	wc.lpszClassName = coupling::kWindowClass;
	RegisterClassExW(&wc); // fails harmlessly when already registered

	// Open on the panel (the weave is only right there), centred, 60 % of it.
	const int pw = s.displayPixelWidth() > 0 ? s.displayPixelWidth() : 1920;
	const int ph = s.displayPixelHeight() > 0 ? s.displayPixelHeight() : 1080;
	const int w = pw * 6 / 10, h = ph * 6 / 10;
	const int x = s.desktopLeft() + (pw - w) / 2, y = s.desktopTop() + (ph - h) / 2;
	HWND hwnd = CreateWindowExW(0, coupling::kWindowClass, coupling::kWindowTitle, WS_OVERLAPPEDWINDOW, x, y, w, h,
	                            nullptr, nullptr, wc.hInstance, nullptr);
	if (hwnd != nullptr) {
		ShowWindow(hwnd, SW_SHOWNOACTIVATE);
	}
	return hwnd;
}

// App framing without breaking true geometry (DisplayXR issue #2422). Passing
// the app camera's vertical FOV to the rig scales the nominal viewer's
// vertical offset (0.1 m above the glass) by the scene scale, so with a 40 deg
// framing in a small window the eyes sat 2.5 m above the camera and looked
// ~36 deg down (MotionBuilder, 2026-10-26). Instead keep the rig canvas-true
// (the offset stays at its real angle) and move it back along the view axis
// until the window frames, at the glass, the height the app camera frames
// there. Depth inputs move with it. Then turn the rig up about the glass point
// by the nominal viewer's angle above the glass centre, so the line from that
// viewer through the window centre is the app camera's view axis: otherwise
// the view aims that angle (~9.5 deg) below the app's (Mia cut off at the top).
void applyAppFraming(dxrh_camera &c, const Session3D &s, int canvasPx)
{
	if (c.vertical_fov <= 0.0f || s.displayPixelHeight() <= 0 || s.displayHeightM() <= 0.0f || canvasPx <= 0 ||
	    c.glass_distance <= 0.0f) {
		return;
	}
	const double canvasHm = (double)s.displayHeightM() * canvasPx / s.displayPixelHeight();
	const double frameH = 2.0 * c.glass_distance * std::tan(c.vertical_fov * 0.5);
	const double glass = s.viewerDistanceM() * frameH / canvasHm;
	const double d = glass - c.glass_distance;
	// The camera's back axis (+Z of its orientation).
	const double x = c.pose.qx, y = c.pose.qy, z = c.pose.qz, w = c.pose.qw;
	const double bx = 2 * (x * z + w * y), by = 2 * (y * z - w * x), bz = 1 - 2 * (x * x + y * y);
	c.pose.px += (float)(bx * d);
	c.pose.py += (float)(by * d);
	c.pose.pz += (float)(bz * d);

	// Pitch up by the viewer's angle, about the glass point on the view axis.
	const double tilt = std::atan2((double)s.viewerHeightM(), (double)s.viewerDistanceM());
	if (std::fabs(tilt) > 1e-6) {
		const double px = c.pose.px - bx * glass, py = c.pose.py - by * glass, pz = c.pose.pz - bz * glass;
		const double hs = std::sin(tilt * 0.5), hc = std::cos(tilt * 0.5); // about local +X (right)
		const double nx = w * hs + x * hc, ny = y * hc + z * hs, nz = z * hc - y * hs, nw = w * hc - x * hs;
		const double b2x = 2 * (nx * nz + nw * ny), b2y = 2 * (ny * nz - nw * nx), b2z = 1 - 2 * (nx * nx + ny * ny);
		c.pose.qx = (float)nx, c.pose.qy = (float)ny, c.pose.qz = (float)nz, c.pose.qw = (float)nw;
		c.pose.px = (float)(px + b2x * glass);
		c.pose.py = (float)(py + b2y * glass);
		c.pose.pz = (float)(pz + b2z * glass);
	}
	c.glass_distance = (float)glass;
	if (c.far_z > 0.0f) {
		c.near_z = (float)std::max(c.near_z + d, glass * 0.01);
		c.far_z = (float)(c.far_z + d);
	}
	c.vertical_fov = 0.0f; // canvas-true from the nominal viewer
}

// Shared depth slider: DXR_HostedDepthRel on our window = strength*1000 |
// focus_mm<<16, relative to our nominal (1.0 = comfort budget filled). The
// slider never goes above comfort; we publish what's in effect in ...Now.
// Focus: the glass follows the host app camera's focal distance, so the slider's
// focus field is not used yet and is published as 0 (auto).
void applyHostedDepth(HWND hwnd)
{
	static uint64_t lastSeen = 0;
	const uint64_t v = (uint64_t)(uintptr_t)GetPropW(hwnd, coupling::kHostedDepthRelProp);
	std::lock_guard<std::mutex> lock(g.mutex);
	if (v != 0 && v != lastSeen) {
		g.strength = std::clamp((float)(v & 0xFFFF) / 1000.0f, 0.0f, 1.0f);
	}
	lastSeen = v;
	const uint64_t now = (uint64_t)std::lround(std::min(g.strength, 1.0f) * 1000.0f);
	SetPropW(hwnd, coupling::kHostedDepthRelNowProp, (HANDLE)(uintptr_t)now);
}

struct EyeTextures
{
	ID3D11Texture2D *tex[2] = {nullptr, nullptr};
	int w = 0, h = 0;

	void release()
	{
		for (auto *&t : tex) {
			if (t != nullptr) {
				t->Release();
			}
			t = nullptr;
		}
		w = h = 0;
	}

	bool ensure(ID3D11Device *dev, int width, int height)
	{
		if (width == w && height == h && tex[0] && tex[1]) {
			return true;
		}
		release();
		D3D11_TEXTURE2D_DESC d{};
		d.Width = (UINT)width;
		d.Height = (UINT)height;
		d.MipLevels = 1;
		d.ArraySize = 1;
		d.Format = DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
		d.SampleDesc.Count = 1;
		d.Usage = D3D11_USAGE_DEFAULT;
		for (auto *&t : tex) {
			if (FAILED(dev->CreateTexture2D(&d, nullptr, &t))) {
				release();
				return false;
			}
		}
		w = width;
		h = height;
		return true;
	}
};

void threadMain(std::promise<std::string> *started)
{
	logOpen();
	// Physical pixels whatever the host app's own DPI mode: the window must land on
	// the panel exactly, and canvas size feeds the rig.
	SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
	Session3D s;
	if (!s.init(moduleDir() + L"openxr_loader.dll")) {
		started->set_value(s.lastError());
		return;
	}
	bool textureMode;
	HWND ref;
	RECT tr;
	{
		std::lock_guard<std::mutex> lock(g.mutex);
		textureMode = g.textureMode;
		ref = g.targetRef;
		tr = g.target;
	}
	if (textureMode && !s.supportsTextureTarget()) {
		started->set_value("this runtime has no texture target (needs v2.55 or later)");
		return;
	}
	// Texture mode: no window of ours; the host's window is the fallback anchor.
	HWND hwnd = textureMode ? ref : createWindow(s);
	if (hwnd == nullptr) {
		started->set_value("could not create the 3D window");
		return;
	}
	const XrRect2Di rect0{{tr.left, tr.top}, {tr.right - tr.left, tr.bottom - tr.top}};
	if (!s.createSession(hwnd, textureMode ? ref : nullptr, rect0)) {
		if (!textureMode) {
			DestroyWindow(hwnd);
		}
		started->set_value(s.lastError());
		return;
	}
	{
		std::lock_guard<std::mutex> lock(g.mutex);
		g.sharedHandle = s.sharedHandle();
		g.sharedW = s.sharedWidth();
		g.sharedH = s.sharedHeight();
	}
	g_hwnd = hwnd;
	g_running = true;
	started->set_value("");

	EyeTextures eyesTex;
	EyeView submitted[2]{};
	bool haveImage = false;
	uint64_t frame = 0;

	while (!g_quit && !s.exitRequested()) {
		MSG msg;
		while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
			TranslateMessage(&msg);
			DispatchMessageW(&msg);
		}
		if (frame++ % 10 == 0) {
			applyHostedDepth(hwnd);
		}

		RECT rc{};
		if (textureMode) {
			std::lock_guard<std::mutex> lock(g.mutex);
			rc = g.target;
			s.setTarget(g.targetRef, {{rc.left, rc.top}, {rc.right - rc.left, rc.bottom - rc.top}});
			g.textureState = s.textureState();
		} else {
			GetClientRect(hwnd, &rc);
		}
		const int cw = std::max(1L, rc.right - rc.left), ch = std::max(1L, rc.bottom - rc.top);

		// Camera input: the host app's camera plus the depth budget for what's in view.
		CameraInput cam{};
		{
			std::lock_guard<std::mutex> lock(g.mutex);
			dxrh_camera c = g.cam;
			applyAppFraming(c, s, ch);
			cam.pose.position = {c.pose.px, c.pose.py, c.pose.pz};
			cam.pose.orientation = {c.pose.qx, c.pose.qy, c.pose.qz, c.pose.qw};
			cam.glassDistance = c.glass_distance;
			cam.verticalFov = c.vertical_fov;
			const double W = s.displayWidthM() > 0 ? s.displayWidthM() : coupling::kFallbackDisplayWidthM;
			const rig::Budget b{W, coupling::kComfortFront, coupling::kComfortBehind};
			const rig::Result r = rig::solve(b, c.glass_distance, c.near_z, c.far_z, coupling::kNaturalIpdM,
			                                 g.strength, g.allowAbove);
			cam.ipdFactor = (float)r.ipdFactor;
			g.depth = {g.strength, c.glass_distance, (float)r.frontPct, (float)r.behindPct, (float)r.ipdFactor};
		}

		EyeView eyes[2]{};
		if (!s.beginFrame(cam, cw, ch, eyes)) {
			setStatus(s.status());
			std::this_thread::sleep_for(std::chrono::milliseconds(5));
			continue;
		}

		{
			std::lock_guard<std::mutex> lock(g.mutex);
			g.serial++;
			std::memcpy(g.eyes[g.serial % kEyeRing], eyes, sizeof(eyes));
			g.renderW = s.renderWidth();
			g.renderH = s.renderHeight();
			g.windowW = cw;
			g.windowH = ch;
			g.status = s.status();
			if (g.fresh && eyesTex.ensure(s.device(), g.pendingW, g.pendingH)) {
				for (int i = 0; i < 2; i++) {
					s.context()->UpdateSubresource(eyesTex.tex[i], 0, nullptr, g.pending[i].data(),
					                               (UINT)g.pendingW * 4, 0);
				}
				// Eyes this pair was rendered from; if they fell out of the ring,
				// the newest are the best guess.
				const bool known = g.pendingSerial != 0 && g.serial - g.pendingSerial < kEyeRing;
				std::memcpy(submitted, g.eyes[(known ? g.pendingSerial : g.serial) % kEyeRing], sizeof(submitted));
				haveImage = true;
				g.fresh = false;
			}
		}
		s.endFrame(haveImage ? eyesTex.tex[0] : nullptr, haveImage ? eyesTex.tex[1] : nullptr, eyesTex.w, eyesTex.h,
		           submitted);
		if (!haveImage) {
			// xrWaitFrame doesn't pace a session that submits no layers.
			std::this_thread::sleep_for(std::chrono::milliseconds(16));
		} else if (textureMode) {
			// Nor a texture-target session (the host presents): ~1200 frames/s
			// measured on v2.55.0. Pace to the display ourselves (runtime #2386).
			static auto last = std::chrono::steady_clock::now();
			const auto next = last + std::chrono::microseconds(16667);
			std::this_thread::sleep_until(next);
			last = std::max(next, std::chrono::steady_clock::now() - std::chrono::milliseconds(2));
		}
	}

	g_running = false;
	g_hwnd = nullptr;
	eyesTex.release();
	s.stop();
	RemovePropW(hwnd, coupling::kHostedDepthRelNowProp);
	{
		std::lock_guard<std::mutex> lock(g.mutex);
		g.sharedHandle = nullptr;
		g.sharedW = g.sharedH = 0;
		g.textureState = 0;
	}
	if (!textureMode) {
		DestroyWindow(hwnd); // never the host's window
	}
	setStatus("3D off");
	logLine(textureMode ? "texture target session ended" : "3D window closed");
}

// Decodes an image file to tightly packed RGBA8 (top row first).
bool loadImage(const wchar_t *path, std::vector<uint8_t> &out, int &w, int &h)
{
	const HRESULT co = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
	bool ok = false;
	IWICImagingFactory *factory = nullptr;
	IWICBitmapDecoder *decoder = nullptr;
	IWICBitmapFrameDecode *frame = nullptr;
	IWICFormatConverter *conv = nullptr;
	if (SUCCEEDED(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER,
	                               IID_PPV_ARGS(&factory))) &&
	    SUCCEEDED(factory->CreateDecoderFromFilename(path, nullptr, GENERIC_READ, WICDecodeMetadataCacheOnDemand,
	                                                 &decoder)) &&
	    SUCCEEDED(decoder->GetFrame(0, &frame)) && SUCCEEDED(factory->CreateFormatConverter(&conv)) &&
	    SUCCEEDED(conv->Initialize(frame, GUID_WICPixelFormat32bppRGBA, WICBitmapDitherTypeNone, nullptr, 0.0,
	                               WICBitmapPaletteTypeCustom))) {
		UINT uw = 0, uh = 0;
		conv->GetSize(&uw, &uh);
		w = (int)uw;
		h = (int)uh;
		out.resize((size_t)uw * uh * 4);
		ok = uw > 0 && uh > 0 && SUCCEEDED(conv->CopyPixels(nullptr, uw * 4, (UINT)out.size(), out.data()));
	}
	for (IUnknown *u : {(IUnknown *)conv, (IUnknown *)frame, (IUnknown *)decoder, (IUnknown *)factory}) {
		if (u != nullptr) {
			u->Release();
		}
	}
	if (SUCCEEDED(co)) {
		CoUninitialize();
	}
	return ok;
}

dxrh_pose toPose(const XrPosef &p)
{
	return {p.position.x, p.position.y, p.position.z, p.orientation.x, p.orientation.y, p.orientation.z,
	        p.orientation.w};
}

} // namespace
} // namespace dxr_host

using namespace dxr_host;

extern "C" {

namespace {
int startThread(bool textureMode, HWND ref, RECT target)
{
	if (g_running) {
		return 0;
	}
	{
		std::lock_guard<std::mutex> lock(g.mutex);
		g.textureMode = textureMode;
		g.targetRef = ref;
		g.target = target;
	}
	if (g_thread.joinable()) {
		g_thread.join();
	}
	g_quit = false;
	{
		std::lock_guard<std::mutex> lock(g.mutex);
		g.serial = 0;
		g.fresh = false;
		g.status = "3D starting";
	}
	std::promise<std::string> started;
	auto result = started.get_future();
	g_thread = std::thread(threadMain, &started);
	const std::string err = result.get();
	if (!err.empty()) {
		g_thread.join();
		setStatus(err);
		return -1;
	}
	return 0;
}

} // namespace

DXRH_API int dxrh_start(void) { return startThread(false, nullptr, {}); }

DXRH_API int dxrh_start_in_viewport(void *reference_window, int x, int y, int width, int height)
{
	if (reference_window == nullptr || width <= 0 || height <= 0) {
		setStatus("no viewport to draw the 3D in");
		return -1;
	}
	return startThread(true, (HWND)reference_window, {x, y, x + width, y + height});
}

DXRH_API void dxrh_set_target(void *reference_window, int x, int y, int width, int height)
{
	if (reference_window == nullptr || width <= 0 || height <= 0) {
		return;
	}
	std::lock_guard<std::mutex> lock(g.mutex);
	g.targetRef = (HWND)reference_window;
	g.target = {x, y, x + width, y + height};
}

DXRH_API int dxrh_get_target(void **reference_window, int *x, int *y, int *width, int *height)
{
	std::lock_guard<std::mutex> lock(g.mutex);
	if (g.targetRef == nullptr) {
		return 0;
	}
	*reference_window = g.targetRef;
	*x = g.target.left, *y = g.target.top;
	*width = g.target.right - g.target.left, *height = g.target.bottom - g.target.top;
	return 1;
}

DXRH_API int dxrh_texture_info(void **shared_handle, int *width, int *height, uint64_t *state_flags)
{
	std::lock_guard<std::mutex> lock(g.mutex);
	if (!g_running || !g.textureMode || g.sharedHandle == nullptr) {
		return 0;
	}
	if (shared_handle != nullptr) {
		*shared_handle = g.sharedHandle;
	}
	if (width != nullptr) {
		*width = g.sharedW;
	}
	if (height != nullptr) {
		*height = g.sharedH;
	}
	if (state_flags != nullptr) {
		*state_flags = g.textureState;
	}
	return 1;
}

DXRH_API void dxrh_toggle_fullscreen(void)
{
	HWND h = g_hwnd;
	if (h != nullptr && !g.textureMode) {
		PostMessageW(h, WM_KEYDOWN, VK_F11, 0);
	}
}

DXRH_API void dxrh_stop(void)
{
	g_quit = true;
	if (g_thread.joinable()) {
		g_thread.join();
	}
}

DXRH_API int dxrh_is_running(void) { return g_running ? 1 : 0; }

DXRH_API int dxrh_status(char *buf, int size)
{
	std::lock_guard<std::mutex> lock(g.mutex);
	if (buf != nullptr && size > 0) {
		std::strncpy(buf, g.status.c_str(), (size_t)size - 1);
		buf[size - 1] = '\0';
	}
	return (int)g.status.size();
}

DXRH_API void dxrh_set_camera(const dxrh_camera *cam)
{
	if (cam == nullptr) {
		return;
	}
	std::lock_guard<std::mutex> lock(g.mutex);
	const dxrh_camera last = g.cam;
	g.cam = *cam;
	if (cam->glass_distance <= 0.0f) {
		g.cam.glass_distance = last.glass_distance;
	}
	if (cam->far_z <= 0.0f) {
		g.cam.near_z = last.near_z;
		g.cam.far_z = last.far_z;
	}
}

DXRH_API void dxrh_set_content_depth(float near_z, float far_z)
{
	std::lock_guard<std::mutex> lock(g.mutex);
	g.cam.near_z = near_z;
	g.cam.far_z = far_z;
}

DXRH_API void dxrh_set_depth(float strength, int allow_above_comfort)
{
	std::lock_guard<std::mutex> lock(g.mutex);
	g.allowAbove = allow_above_comfort != 0;
	g.strength = std::clamp(strength, 0.0f, g.allowAbove ? 2.0f : 1.0f);
}

DXRH_API void dxrh_get_depth(dxrh_depth_info *out)
{
	if (out != nullptr) {
		std::lock_guard<std::mutex> lock(g.mutex);
		*out = g.depth;
	}
}

DXRH_API int dxrh_get_eyes(dxrh_eye eyes[2], uint32_t *serial)
{
	std::lock_guard<std::mutex> lock(g.mutex);
	if (g.serial == 0 || eyes == nullptr) {
		return 0;
	}
	const EyeView *e = g.eyes[g.serial % kEyeRing];
	for (int i = 0; i < 2; i++) {
		eyes[i].pose = toPose(e[i].pose);
		eyes[i].angle_left = e[i].fov.angleLeft;
		eyes[i].angle_right = e[i].fov.angleRight;
		eyes[i].angle_up = e[i].fov.angleUp;
		eyes[i].angle_down = e[i].fov.angleDown;
	}
	if (serial != nullptr) {
		*serial = g.serial;
	}
	return 1;
}

DXRH_API int dxrh_render_size(int *width, int *height)
{
	std::lock_guard<std::mutex> lock(g.mutex);
	if (width != nullptr) {
		*width = g.renderW;
	}
	if (height != nullptr) {
		*height = g.renderH;
	}
	return g.renderW > 0 ? 1 : 0;
}

DXRH_API int dxrh_window_size(int *width, int *height)
{
	std::lock_guard<std::mutex> lock(g.mutex);
	if (width != nullptr) {
		*width = g.windowW;
	}
	if (height != nullptr) {
		*height = g.windowH;
	}
	return g.windowW > 0 ? 1 : 0;
}

DXRH_API int dxrh_submit_rgba8(const uint8_t *left, const uint8_t *right, int width, int height, int stride,
                               uint32_t serial)
{
	if (left == nullptr || right == nullptr || width <= 0 || height <= 0 || stride < width * 4) {
		return -1;
	}
	std::lock_guard<std::mutex> lock(g.mutex);
	const uint8_t *src[2] = {left, right};
	for (int i = 0; i < 2; i++) {
		g.pending[i].resize((size_t)width * height * 4);
		for (int y = 0; y < height; y++) {
			std::memcpy(g.pending[i].data() + (size_t)y * width * 4, src[i] + (size_t)y * stride, (size_t)width * 4);
		}
	}
	g.pendingW = width;
	g.pendingH = height;
	g.pendingSerial = serial;
	g.fresh = true;
	return 0;
}

DXRH_API int dxrh_submit_files(const wchar_t *left, const wchar_t *right, uint32_t serial)
{
	std::vector<uint8_t> img[2];
	int w[2] = {0, 0}, h[2] = {0, 0};
	if (left == nullptr || right == nullptr || !loadImage(left, img[0], w[0], h[0]) ||
	    !loadImage(right, img[1], w[1], h[1]) || w[0] != w[1] || h[0] != h[1]) {
		return -1;
	}
	return dxrh_submit_rgba8(img[0].data(), img[1].data(), w[0], h[0], w[0] * 4, serial);
}

DXRH_API int dxrh_poll_input(dxrh_input *events, int max)
{
	if (events == nullptr || max <= 0) {
		return 0;
	}
	std::lock_guard<std::mutex> lock(g.mutex);
	const int n = std::min<int>(max, (int)g.input.size());
	std::copy(g.input.begin(), g.input.begin() + n, events);
	g.input.erase(g.input.begin(), g.input.begin() + n);
	return n;
}

DXRH_API int dxrh_get_gamepad(dxrh_gamepad *out)
{
	// XInput, loaded on first use (xinput1_4 ships with Windows 8+).
	struct Pad
	{
		WORD buttons;
		BYTE lt, rt;
		SHORT lx, ly, rx, ry;
	};
	struct State
	{
		DWORD packet;
		Pad pad;
	};
	using GetState = DWORD(WINAPI *)(DWORD, State *);
	static GetState getState = [] {
		HMODULE m = LoadLibraryW(L"xinput1_4.dll");
		return m != nullptr ? (GetState)GetProcAddress(m, "XInputGetState") : nullptr;
	}();
	if (out == nullptr || getState == nullptr) {
		return 0;
	}
	auto stick = [](SHORT v, float dead) {
		const float f = std::clamp(v / 32767.0f, -1.0f, 1.0f);
		return std::fabs(f) < dead ? 0.0f : (f - std::copysign(dead, f)) / (1.0f - dead);
	};
	for (DWORD i = 0; i < 4; i++) {
		State st{};
		if (getState(i, &st) == 0) { // ERROR_SUCCESS
			out->lx = stick(st.pad.lx, 0.24f), out->ly = stick(st.pad.ly, 0.24f);
			out->rx = stick(st.pad.rx, 0.27f), out->ry = stick(st.pad.ry, 0.27f);
			out->lt = st.pad.lt > 30 ? (st.pad.lt - 30) / 225.0f : 0.0f;
			out->rt = st.pad.rt > 30 ? (st.pad.rt - 30) / 225.0f : 0.0f;
			out->buttons = st.pad.buttons;
			return 1;
		}
	}
	return 0;
}

} // extern "C"
