package io.mirai;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Builder-style configuration for registering a tool with MiraiAgent.
 */
public class RegisterOptions {
    private String name;
    private String description;
    private List<ToolParameter> parameters = new ArrayList<>();
    private Integer timeout;
    private boolean requireConfirmation;
    private ToolHandler handler;

    public RegisterOptions name(String name) { this.name = name; return this; }
    public RegisterOptions description(String desc) { this.description = desc; return this; }
    public RegisterOptions parameters(ToolParameter... params) { this.parameters = Arrays.asList(params); return this; }
    public RegisterOptions parameters(List<ToolParameter> params) { this.parameters = params; return this; }
    public RegisterOptions timeout(int seconds) { this.timeout = seconds; return this; }
    public RegisterOptions requireConfirmation(boolean v) { this.requireConfirmation = v; return this; }
    public RegisterOptions handler(ToolHandler h) { this.handler = h; return this; }

    public String getName() { return name; }
    public String getDescription() { return description; }
    public List<ToolParameter> getParameters() { return parameters; }
    public Integer getTimeout() { return timeout; }
    public boolean isRequireConfirmation() { return requireConfirmation; }
    public ToolHandler getHandler() { return handler; }
}
