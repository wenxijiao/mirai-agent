namespace Mirai;

/// <summary>
/// Builder-style configuration for registering a tool with <see cref="MiraiAgent"/>.
/// </summary>
public sealed class RegisterOptions
{
    public string? Name { get; private set; }
    public string? Description { get; private set; }
    public List<ToolParameter> Parameters { get; private set; } = new();
    public int? Timeout { get; private set; }
    public bool RequireConfirmation { get; private set; }
    public bool AlwaysInclude { get; private set; }
    public ToolHandler? Handler { get; private set; }

    public RegisterOptions SetName(string name) { Name = name; return this; }
    public RegisterOptions SetDescription(string desc) { Description = desc; return this; }
    public RegisterOptions SetParameters(params ToolParameter[] pars) { Parameters = new List<ToolParameter>(pars); return this; }
    public RegisterOptions SetTimeout(int seconds) { Timeout = seconds; return this; }
    public RegisterOptions SetRequireConfirmation(bool v) { RequireConfirmation = v; return this; }
    public RegisterOptions SetAlwaysInclude(bool v) { AlwaysInclude = v; return this; }
    public RegisterOptions SetHandler(ToolHandler h) { Handler = h; return this; }
}
