// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0

#include "log.h"
#include "coupling.h"

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>

#include <cstdarg>
#include <ctime>
#include <mutex>
#include <string>

namespace dxr_host {

namespace {
std::mutex g_mutex;
FILE *g_file = nullptr;
} // namespace

void logOpen()
{
	std::lock_guard<std::mutex> lock(g_mutex);
	if (g_file != nullptr) {
		return;
	}
	char base[MAX_PATH] = {};
	if (GetEnvironmentVariableA("LOCALAPPDATA", base, MAX_PATH) == 0) {
		return;
	}
	std::string dir = std::string(base) + "\\DisplayXR";
	CreateDirectoryA(dir.c_str(), nullptr);
	g_file = std::fopen((dir + "\\" DXRH_LOG_NAME).c_str(), "w");
}

void logLine(const char *fmt, ...)
{
	std::lock_guard<std::mutex> lock(g_mutex);
	if (g_file == nullptr) {
		return;
	}
	std::time_t t = std::time(nullptr);
	std::tm tm{};
	localtime_s(&tm, &t);
	std::fprintf(g_file, "%02d:%02d:%02d ", tm.tm_hour, tm.tm_min, tm.tm_sec);
	va_list ap;
	va_start(ap, fmt);
	std::vfprintf(g_file, fmt, ap);
	va_end(ap);
	std::fputc('\n', g_file);
	std::fflush(g_file);
}

} // namespace dxr_host
