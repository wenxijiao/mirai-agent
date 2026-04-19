using System;
using System.Threading;

/// <summary>
/// Standalone entry: add a small <c>.csproj</c> that references <c>mirai_sdk</c>, then <c>dotnet run</c>.
/// Remove this file when you integrate <see cref="MiraiSetup.InitMirai"/> into your own app.
/// </summary>
internal static class MiraiEdgeProgram
{
    private static void Main()
    {
        MiraiSetup.InitMirai();
        Console.Error.WriteLine("Mirai edge running. Press Ctrl+C to exit.");
        Thread.Sleep(Timeout.Infinite);
    }
}
