using System.Text.Json;
using System.Text.Json.Nodes;

namespace Mirai;

/// <summary>
/// Builds the JSON tool schema sent during WebSocket registration.
/// </summary>
internal static class SchemaBuilder
{
    public static JsonObject Build(RegisterOptions opts)
    {
        var properties = new JsonObject();
        var required = new JsonArray();

        foreach (var p in opts.Parameters)
        {
            var prop = new JsonObject
            {
                ["type"] = p.Type,
                ["description"] = p.Description,
            };
            properties[p.Name] = prop;
            if (p.Required)
                required.Add(p.Name);
        }

        var parameters = new JsonObject
        {
            ["type"] = "object",
            ["properties"] = properties,
            ["required"] = required,
        };

        var function_ = new JsonObject
        {
            ["name"] = opts.Name,
            ["description"] = opts.Description,
            ["parameters"] = parameters,
        };

        var schema = new JsonObject
        {
            ["type"] = "function",
            ["function"] = function_,
        };

        if (opts.Timeout.HasValue)
            schema["timeout"] = opts.Timeout.Value;

        if (opts.RequireConfirmation)
            schema["require_confirmation"] = true;

        return schema;
    }
}
