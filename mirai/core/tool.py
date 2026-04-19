import inspect
import types
import typing
from typing import Any, Callable, Dict, get_args, get_origin

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}

_STR_TYPE_MAP: Dict[str, Dict[str, Any]] = {
    "str": {"type": "string"},
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "bool": {"type": "boolean"},
    "list": {"type": "array", "items": {"type": "string"}},
    "tuple": {"type": "array", "items": {"type": "string"}},
    "set": {"type": "array", "items": {"type": "string"}},
    "dict": {"type": "object", "additionalProperties": {"type": "string"}},
}


def _annotation_to_schema(annotation: Any) -> Dict[str, Any]:
    if annotation == inspect.Parameter.empty:
        return {"type": "string"}

    if isinstance(annotation, str):
        return _STR_TYPE_MAP.get(annotation, {"type": "string"})

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is not None:
        if origin in (list, tuple, set):
            item_schema = _annotation_to_schema(args[0]) if args else {"type": "string"}
            return {"type": "array", "items": item_schema}

        if origin is dict:
            value_schema = _annotation_to_schema(args[1]) if len(args) > 1 else {"type": "string"}
            return {"type": "object", "additionalProperties": value_schema}

        if origin in (types.UnionType, getattr(__import__("typing"), "Union")):
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                return _annotation_to_schema(non_none_args[0])
            return {"type": "string"}

    if annotation == str:
        return {"type": "string"}
    if annotation == int:
        return {"type": "integer"}
    if annotation == float:
        return {"type": "number"}
    if annotation == bool:
        return {"type": "boolean"}
    if annotation in (list, tuple, set):
        return {"type": "array", "items": {"type": "string"}}
    if annotation == dict:
        return {"type": "object", "additionalProperties": {"type": "string"}}

    return {"type": "string"}


def _resolve_type_hints(func: Callable) -> Dict[str, Any]:
    """Get resolved type hints, handling ``from __future__ import annotations``."""
    try:
        return typing.get_type_hints(func)
    except Exception:
        return {}


def _build_tool_schema(
    func: Callable,
    description: str | None = None,
    *,
    name: str | None = None,
    params: Dict[str, str] | None = None,
    returns: str | None = None,
) -> Dict[str, Any]:
    """Build an OpenAI-style function schema from *func* and its annotations."""
    tool_name = name or func.__name__
    doc = description or inspect.getdoc(func) or "No description provided."
    full_description = doc.strip()
    if returns:
        full_description += f"\nReturns: {returns}"

    sig = inspect.signature(func)
    hints = _resolve_type_hints(func)
    properties = {}
    required_params = []

    for param_name, param in sig.parameters.items():
        if param.default == inspect.Parameter.empty:
            required_params.append(param_name)

        annotation = hints.get(param_name, param.annotation)
        if annotation == inspect.Parameter.empty:
            print(
                f"[Mirai Tool Warning] Parameter '{param_name}' in tool '{tool_name}' has no type annotation. Defaulting to string."
            )

        param_schema = _annotation_to_schema(annotation)
        if params and param_name in params:
            param_schema["description"] = params[param_name]
        else:
            param_schema["description"] = f"Parameter: {param_name}"
        properties[param_name] = param_schema

    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": full_description,
            "parameters": {"type": "object", "properties": properties, "required": required_params},
        },
    }


def register_tool(
    func: Callable,
    description: str | None = None,
    *,
    name: str | None = None,
    params: Dict[str, str] | None = None,
    returns: str | None = None,
) -> None:
    """Register a plain function as a Mirai tool (non-decorator API).

    This mirrors the edge-side ``MiraiAgent.register()`` pattern::

        from mirai.core.tool import register_tool
        register_tool(my_func, "What this tool does")

    Args:
        func: The callable to register.
        description: What the tool does (shown to the LLM).
        name: Override the tool name (defaults to ``func.__name__``).
        params: Mapping of parameter name → human-readable description.
        returns: Description of the return value (appended to description).
    """
    schema = _build_tool_schema(func, description, name=name, params=params, returns=returns)
    tool_name = schema["function"]["name"]
    TOOL_REGISTRY[tool_name] = {"schema": schema, "callable": func}


async def execute_registered_tool(tool_name: str, arguments: Dict[str, Any]):
    if tool_name not in TOOL_REGISTRY:
        raise KeyError(f"Tool '{tool_name}' is not registered.")

    func = TOOL_REGISTRY[tool_name]["callable"]
    result = func(**arguments)
    if inspect.isawaitable(result):
        result = await result
    return result
