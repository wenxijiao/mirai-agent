#pragma once

#include "MiraiAgent.h"

/**
 * Mirai Edge — UE5 tool registration
 *
 * Call InitMirai() early in your game lifecycle (e.g. from GameInstance::Init
 * or a custom subsystem).
 *
 * Setup:
 * 1. Copy MiraiSDK/ module into your project's Source/ directory
 * 2. Add "MiraiSDK" to your .Build.cs PublicDependencyModuleNames
 * 3. Regenerate project files
 */

// ── Connection (edit here, or set in .env) ──

static const TCHAR* MiraiConnectionCode = TEXT("mirai-lan_...");  // from `mirai --server`
static const TCHAR* MiraiEdgeName = TEXT("My UE5 Game");

FMiraiAgent* InitMirai();
