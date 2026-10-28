// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0
//
// Texture mode for 3D Slicer (the in-viewport target, Discussion #2352):
// draw the woven texture the runtime produced into Slicer's own 3D view,
// pixel-exact, in VTK's GL context. Called from Python (ctypes) in the last
// vtkRenderer's EndEvent, before VTK copies its render framebuffer out
// (drawing later lands in Qt's buffer and never reaches the screen).
//
// The texture is the host core's D3D11 shared texture; GL reads it through
// WGL_NV_DX_interop2. VTK runs a core-profile context, so the copy is a
// glBlitFramebuffer from a read FBO (no fixed-function quad), flipped
// because the woven frame is top row first. Slicer's menus, markups and
// mouse stay its own: no window covers the app.

#include "include/displayxr_host.h"

#include <windows.h>
#include <d3d11.h>
#include <GL/gl.h>

#include <cstdarg>
#include <cstdio>
#include <cstring>

namespace {

using PfnOpenDevice = HANDLE(WINAPI *)(void *dxDevice);
using PfnCloseDevice = BOOL(WINAPI *)(HANDLE hDevice);
using PfnRegister = HANDLE(WINAPI *)(HANDLE hDevice, void *dxObject, GLuint name, GLenum type, GLenum access);
using PfnUnregister = BOOL(WINAPI *)(HANDLE hDevice, HANDLE hObject);
using PfnLock = BOOL(WINAPI *)(HANDLE hDevice, GLint count, HANDLE *hObjects);
using PfnGenFramebuffers = void(APIENTRY *)(GLsizei, GLuint *);
using PfnDeleteFramebuffers = void(APIENTRY *)(GLsizei, const GLuint *);
using PfnBindFramebuffer = void(APIENTRY *)(GLenum, GLuint);
using PfnFramebufferTexture2D = void(APIENTRY *)(GLenum, GLenum, GLenum, GLuint, GLint);
using PfnBlitFramebuffer = void(APIENTRY *)(GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLint, GLbitfield, GLenum);
using PfnCheckFramebufferStatus = GLenum(APIENTRY *)(GLenum);
using PfnGetFramebufferParameteriv = void(APIENTRY *)(GLenum, GLenum, GLint *);

constexpr GLenum kAccessReadOnly = 0x0000; // WGL_ACCESS_READ_ONLY_NV
constexpr GLenum kReadFramebuffer = 0x8CA8, kDrawFramebuffer = 0x8CA9;
constexpr GLenum kReadFramebufferBinding = 0x8CAA, kDrawFramebufferBinding = 0x8CA6;
constexpr GLenum kColorAttachment0 = 0x8CE0, kFramebufferComplete = 0x8CD5;
constexpr GLenum kFramebufferSrgb = 0x8DB9, kSamples = 0x80A9;

struct State
{
	bool loaded = false;
	PfnOpenDevice open = nullptr;
	PfnCloseDevice close = nullptr;
	PfnRegister reg = nullptr;
	PfnUnregister unreg = nullptr;
	PfnLock lock = nullptr, unlock = nullptr;
	PfnGenFramebuffers genF = nullptr;
	PfnDeleteFramebuffers delF = nullptr;
	PfnBindFramebuffer bindF = nullptr;
	PfnFramebufferTexture2D texF = nullptr;
	PfnBlitFramebuffer blit = nullptr;
	PfnCheckFramebufferStatus checkF = nullptr;
	PfnGetFramebufferParameteriv fbParam = nullptr;

	ID3D11Device *dev = nullptr;
	ID3D11Texture2D *tex = nullptr;
	HANDLE glDev = nullptr, glObj = nullptr;
	GLuint glTex = 0, readFbo = 0;
	void *handle = nullptr; // shared handle the objects above were made for
	bool failed = false;
	int drawn = 0, mismatched = 0;
	char info[512] = "";
} s;

void note(const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	std::vsnprintf(s.info, sizeof(s.info), fmt, ap);
	va_end(ap);
}

bool load()
{
	if (s.loaded) {
		return s.open && s.reg && s.lock && s.unlock && s.genF && s.bindF && s.texF && s.blit;
	}
	s.loaded = true;
	s.open = (PfnOpenDevice)wglGetProcAddress("wglDXOpenDeviceNV");
	s.close = (PfnCloseDevice)wglGetProcAddress("wglDXCloseDeviceNV");
	s.reg = (PfnRegister)wglGetProcAddress("wglDXRegisterObjectNV");
	s.unreg = (PfnUnregister)wglGetProcAddress("wglDXUnregisterObjectNV");
	s.lock = (PfnLock)wglGetProcAddress("wglDXLockObjectsNV");
	s.unlock = (PfnLock)wglGetProcAddress("wglDXUnlockObjectsNV");
	s.genF = (PfnGenFramebuffers)wglGetProcAddress("glGenFramebuffers");
	s.delF = (PfnDeleteFramebuffers)wglGetProcAddress("glDeleteFramebuffers");
	s.bindF = (PfnBindFramebuffer)wglGetProcAddress("glBindFramebuffer");
	s.texF = (PfnFramebufferTexture2D)wglGetProcAddress("glFramebufferTexture2D");
	s.blit = (PfnBlitFramebuffer)wglGetProcAddress("glBlitFramebuffer");
	s.checkF = (PfnCheckFramebufferStatus)wglGetProcAddress("glCheckFramebufferStatus");
	s.fbParam = (PfnGetFramebufferParameteriv)wglGetProcAddress("glGetFramebufferParameteriv");
	if (!(s.open && s.reg && s.lock && s.unlock)) {
		note("WGL_NV_DX_interop2 not available in VTK's GL context");
		return false;
	}
	if (!(s.genF && s.bindF && s.texF && s.blit)) {
		note("framebuffer blit not available in VTK's GL context");
		return false;
	}
	return true;
}

void closeShared()
{
	if (s.glObj != nullptr) {
		s.unreg(s.glDev, s.glObj);
		s.glObj = nullptr;
	}
	if (s.readFbo != 0) {
		s.delF(1, &s.readFbo);
		s.readFbo = 0;
	}
	if (s.glTex != 0) {
		glDeleteTextures(1, &s.glTex);
		s.glTex = 0;
	}
	if (s.tex != nullptr) {
		s.tex->Release();
		s.tex = nullptr;
	}
	s.handle = nullptr;
	s.failed = false;
}

bool openShared(void *handle)
{
	if (s.dev == nullptr) {
		const D3D_FEATURE_LEVEL fl = D3D_FEATURE_LEVEL_11_0;
		if (FAILED(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, &fl, 1, D3D11_SDK_VERSION, &s.dev,
		                             nullptr, nullptr))) {
			note("D3D11CreateDevice failed");
			return false;
		}
		s.glDev = s.open(s.dev);
		if (s.glDev == nullptr) {
			note("wglDXOpenDeviceNV failed (GL and D3D on different GPUs?)");
			return false;
		}
	}
	if (FAILED(s.dev->OpenSharedResource((HANDLE)handle, __uuidof(ID3D11Texture2D), (void **)&s.tex))) {
		note("OpenSharedResource failed (core on another GPU?)");
		return false;
	}
	glGenTextures(1, &s.glTex);
	s.glObj = s.reg(s.glDev, s.tex, s.glTex, GL_TEXTURE_2D, kAccessReadOnly);
	if (s.glObj == nullptr) {
		note("wglDXRegisterObjectNV failed");
		return false;
	}
	s.genF(1, &s.readFbo);
	s.handle = handle;
	return true;
}

} // namespace

extern "C" {

// Draws the woven frame over the current viewport of the bound draw
// framebuffer. Returns 1 when drawn, 0 when 3D isn't in texture mode,
// negative when skipped (see dxs_info).
__declspec(dllexport) int dxs_present(void)
{
	void *handle = nullptr;
	int sw = 0, sh = 0;
	uint64_t flags = 0;
	if (!dxrh_texture_info(&handle, &sw, &sh, &flags)) {
		if (s.glObj != nullptr) {
			closeShared(); // 3D stopped: release on VTK's context
		}
		return 0;
	}
	if (!load()) {
		return -1;
	}
	if (handle != s.handle) {
		closeShared();
		if (!openShared(handle)) {
			s.failed = true;
		}
	}
	if (s.failed || s.glObj == nullptr) {
		return -1;
	}
	void *ref = nullptr;
	int tx = 0, ty = 0, tw = 0, th = 0;
	dxrh_get_target(&ref, &tx, &ty, &tw, &th);
	GLint vp[4] = {};
	glGetIntegerv(GL_VIEWPORT, vp);
	// The weave is phased for the published rect: drawing it at another size
	// would put it out of phase, so skip until the view and the target agree.
	if (tw != vp[2] || th != vp[3] || tw > sw || th > sh) {
		if (s.mismatched++ % 120 == 0) {
			note("view is %dx%d but the target is %dx%d (texture %dx%d): not drawing", vp[2], vp[3], tw, th, sw, sh);
		}
		return -2;
	}
	GLint drawFbo = 0, readFbo = 0, samples = 0;
	glGetIntegerv(kDrawFramebufferBinding, &drawFbo);
	glGetIntegerv(kReadFramebufferBinding, &readFbo);
	glGetIntegerv(kSamples, &samples);
	if (samples > 0) {
		note("draw framebuffer %d is multisampled (%d): not drawing", drawFbo, samples);
		return -3;
	}
	if (!s.lock(s.glDev, 1, &s.glObj)) {
		note("wglDXLockObjectsNV failed");
		return -4;
	}
	const GLboolean scissor = glIsEnabled(GL_SCISSOR_TEST), srgb = glIsEnabled(kFramebufferSrgb);
	glDisable(GL_SCISSOR_TEST);
	glDisable(kFramebufferSrgb);
	s.bindF(kReadFramebuffer, s.readFbo);
	s.texF(kReadFramebuffer, kColorAttachment0, GL_TEXTURE_2D, s.glTex, 0);
	const GLenum status = s.checkF != nullptr ? s.checkF(kReadFramebuffer) : kFramebufferComplete;
	if (status == kFramebufferComplete) {
		// Woven frame = (0, 0, tw, th) of the texture, top row first: flip it
		// onto the viewport, one texel per pixel.
		s.blit(0, 0, tw, th, vp[0], vp[1] + th, vp[0] + tw, vp[1], GL_COLOR_BUFFER_BIT, GL_NEAREST);
		s.drawn++;
	} else {
		note("read framebuffer incomplete (0x%x)", status);
	}
	s.texF(kReadFramebuffer, kColorAttachment0, GL_TEXTURE_2D, 0, 0);
	s.bindF(kReadFramebuffer, (GLuint)readFbo);
	s.bindF(kDrawFramebuffer, (GLuint)drawFbo);
	if (scissor) {
		glEnable(GL_SCISSOR_TEST);
	}
	if (srgb) {
		glEnable(kFramebufferSrgb);
	}
	s.unlock(s.glDev, 1, &s.glObj);
	if (s.drawn <= 3) {
		note("drawn %d: viewport %d,%d %dx%d, draw fbo %d, texture %dx%d, state flags 0x%llx", s.drawn, vp[0], vp[1],
		     vp[2], vp[3], drawFbo, sw, sh, (unsigned long long)flags);
	}
	return status == kFramebufferComplete ? 1 : -5;
}

// Releases the GL objects; call with VTK's context current (after Stop 3D).
__declspec(dllexport) void dxs_release(void) { closeShared(); }

// Frames drawn so far.
__declspec(dllexport) int dxs_drawn(void) { return s.drawn; }

// Last diagnostic line (why a frame wasn't drawn, or the first frames' state).
__declspec(dllexport) int dxs_info(char *buf, int size)
{
	if (buf != nullptr && size > 0) {
		std::snprintf(buf, (size_t)size, "%s", s.info);
	}
	return (int)std::strlen(s.info);
}

} // extern "C"
