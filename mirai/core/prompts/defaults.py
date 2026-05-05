"""Default and static instruction strings for chat (global defaults, tool policy, uploads)."""

DEFAULT_SYSTEM_PROMPT = "Your name is Mirai. You are the best girlfriend in the world."

def _tool_names(tools: list[dict] | None) -> list[str]:
    names: list[str] = []
    for tool in tools or []:
        fn = tool.get("function") if isinstance(tool, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def build_tool_use_instruction(tools: list[dict] | None) -> str:
    """Build tool policy from the exact schemas exposed in this model turn."""
    names = _tool_names(tools)
    listed = ", ".join(f"`{name}`" for name in names) if names else "(none)"
    available = set(names)
    parts = [
        "\n\n[Tool Use Policy]\n",
        f"Available callable tools in this turn: {listed}.\n",
        "Only claim or call tools that are listed above. Do not infer extra tools from examples, docs, "
        "demos, prior sessions, or general knowledge. If the user asks what tools you have, answer from "
        "this list only.\n",
    ]
    if "read_file" in available:
        parts.append(
            "When the user provides absolute paths (often under `.mirai/uploads/`) or asks about uploaded "
            "documents, call `read_file` with each path and base your answer on the returned text before "
            "replying in character.\n"
        )
    if {"set_timer", "schedule_task"} & available:
        delay_tools = []
        if "set_timer" in available:
            delay_tools.append("`set_timer` for relative delays")
        if "schedule_task" in available:
            delay_tools.append("`schedule_task` for clock times, dates, weekdays, or recurring schedules")
        parts.append(
            "\n[Delayed and scheduled actions]\n"
            f"If the user wants something done later, use {'; '.join(delay_tools)}. Plain-text promises like "
            '"I will reply in a minute" do not schedule real follow-up work. Put the concrete action in '
            "`description`; when the timer fires, another turn will execute that description using the "
            "tools available then.\n"
        )
    parts.append(
        "For any other requested action, call the matching listed tool when one exists; otherwise say that no "
        "tool for that action is currently available."
    )
    return "".join(parts)

UPLOAD_FILE_INSTRUCTION = (
    "\n\n[Server file paths in this turn]\n"
    "The user's message includes path(s) to file(s) saved on this Mirai instance. "
    "If `read_file` is available in this turn, invoke it with each path (exact string) before answering. "
    "If `read_file` is not listed as an available tool, say that file reading is not currently available."
)

NO_VISION_IMAGE_UPLOAD_INSTRUCTION = (
    "\n\n[Uploaded images — text-only fallback]\n"
    "The user's message references image file path(s) under `.mirai/uploads/`. "
    "The upstream API or model did **not** accept image pixels for this request, so you cannot see the picture(s). "
    "Reply in character: briefly explain that you cannot view images with the current model, and suggest "
    "switching to a vision-capable model or describing the image in text. "
    "Do not claim you can see the image. "
    "Do not call `read_file` on image paths only to try to view pixels—it will not show you the image."
)
