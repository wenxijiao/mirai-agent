#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

/**
 * Tool parameter descriptor.
 */
struct FMiraiToolParam
{
    FString Name;
    FString Type;         // "string", "integer", "number", "boolean", "array", "object"
    FString Description;
    bool bRequired = true;
};

/**
 * Type-safe wrapper for tool arguments received from the server.
 */
class FMiraiToolArguments
{
public:
    explicit FMiraiToolArguments(TSharedPtr<FJsonObject> InRaw) : Raw(MoveTemp(InRaw)) {}

    FString GetString(const FString& Key, const FString& Default = TEXT("")) const;
    int32 GetInt(const FString& Key, int32 Default = 0) const;
    double GetNumber(const FString& Key, double Default = 0.0) const;
    bool GetBool(const FString& Key, bool Default = false) const;
    TSharedPtr<FJsonObject> GetRawJson() const { return Raw; }

private:
    TSharedPtr<FJsonObject> Raw;
};

DECLARE_DELEGATE_RetVal_OneParam(FString, FMiraiToolHandler, const FMiraiToolArguments&);

/**
 * Tool registration options.
 */
struct FMiraiRegisterOptions
{
    FString Name;
    FString Description;
    TArray<FMiraiToolParam> Parameters;
    FMiraiToolHandler Handler;
    int32 Timeout = 0;
    bool bRequireConfirmation = false;
    bool bAlwaysInclude = false;
    bool bAllowProactive = false;
    bool bProactiveContext = false;
    TSharedPtr<FJsonObject> ProactiveContextArgs;
    FString ProactiveContextDescription;
};

/**
 * Embeddable Mirai edge client for Unreal Engine 5.
 *
 * Usage:
 * @code
 * FMiraiAgent Agent(TEXT("mirai-lan_..."), TEXT("My UE5 Game"));
 *
 * FMiraiRegisterOptions Opts;
 * Opts.Name = TEXT("jump");
 * Opts.Description = TEXT("Make the character jump");
 * Opts.Handler.BindLambda([](const FMiraiToolArguments& Args) -> FString {
 *     return TEXT("Jumped!");
 * });
 * Agent.RegisterTool(MoveTemp(Opts));
 *
 * Agent.RunInBackground();
 * @endcode
 *
 * Call Stop() or let the destructor handle cleanup.
 */
class MIRAISDK_API FMiraiAgent
{
public:
    FMiraiAgent(
        const FString& ConnectionCode = TEXT(""),
        const FString& EdgeName = TEXT(""),
        const FString& EnvPath = TEXT("")
    );

    ~FMiraiAgent();

    FMiraiAgent(const FMiraiAgent&) = delete;
    FMiraiAgent& operator=(const FMiraiAgent&) = delete;

    void RegisterTool(FMiraiRegisterOptions Opts);

    void RunInBackground();

    void Stop();

    bool IsRunning() const { return bRunning; }

private:
    struct FRegisteredTool
    {
        TSharedPtr<FJsonObject> Schema;
        FMiraiToolHandler Handler;
        bool bRequireConfirmation;
    };

    FString ConnectionCode;
    FString EdgeName;
    FString PolicyBaseDir;

    TMap<FString, FRegisteredTool> Tools;
    bool bRunning = false;
    bool bStopRequested = false;

    class IWebSocket* WebSocket = nullptr;
    FTimerHandle ReconnectTimerHandle;
    int32 ReconnectDelay = 3;

    // Confirmation policy
    FString ConfirmationPolicyPath() const;
    TSharedPtr<FJsonObject> LoadConfirmationPolicy() const;
    void SaveConfirmationPolicy(TSharedPtr<FJsonObject> Data) const;

    // Internal
    void ConnectToServer();
    void OnConnected();
    void OnMessage(const FString& Message);
    void OnClosed(int32 StatusCode, const FString& Reason, bool bWasClean);
    void OnError(const FString& Error);
    void HandleToolCall(TSharedPtr<FJsonObject> Msg);
    void ScheduleReconnect();

    TSharedPtr<FJsonObject> BuildToolSchema(const FMiraiRegisterOptions& Opts) const;

    // .env parser
    static void LoadEnvFile(const FString& Path);
};
