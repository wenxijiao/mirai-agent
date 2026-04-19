package io.mirai;

/**
 * Functional interface for tool execution callbacks.
 */
@FunctionalInterface
public interface ToolHandler {
    String handle(ToolArguments args);
}
