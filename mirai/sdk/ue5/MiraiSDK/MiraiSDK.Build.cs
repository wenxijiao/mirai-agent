using UnrealBuildTool;

public class MiraiSDK : ModuleRules
{
    public MiraiSDK(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Json",
            "JsonUtilities",
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "WebSockets",
            "HTTP",
        });
    }
}
