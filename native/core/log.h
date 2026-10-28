// Copyright 2026, The DisplayXR Project
// SPDX-License-Identifier: Apache-2.0
//
// Plain file log: %LOCALAPPDATA%\DisplayXR\<DXRH_LOG_NAME> (displayxr-motionbuilder.log). Recurring
// diagnostics must be throttled by the caller; never log per frame.
#pragma once

#include <cstdio>

namespace dxr_host {

void logOpen();
void logLine(const char *fmt, ...);

} // namespace dxr_host
