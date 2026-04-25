from __future__ import annotations

import pytest
from mirai.core.config import ModelConfig
from mirai.core.plugins import LOCAL_IDENTITY
from mirai.core.tool import TOOL_REGISTRY
from mirai.core.tool_routing import (
    clear_tool_routing_traces,
    list_tool_routing_traces,
    record_tool_routing_usage,
    select_tool_schemas,
)


def _schema(name: str, description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "string", "description": f"Value for {description}"},
                },
                "required": ["value"],
            },
        },
    }


def _edge_registry(count: int, *, special_name: str = "edge_lab__set_kitchen_lights") -> dict:
    tools = {}
    for i in range(count):
        name = f"edge_lab__generic_tool_{i}"
        desc = f"Generic factory operation number {i}"
        tools[name] = {"schema": _schema(name, desc)}
    tools[special_name] = {
        "schema": _schema(
            special_name,
            "Turn on, turn off, dim, or brighten the kitchen lights in the lab.",
        )
    }
    return {"lab": tools}


@pytest.fixture(autouse=True)
def _restore_tool_registry(monkeypatch):
    original = dict(TOOL_REGISTRY)
    TOOL_REGISTRY.clear()
    TOOL_REGISTRY.update(
        {
            "remember_user_preference": {
                "schema": _schema("remember_user_preference", "Store an important user memory."),
                "callable": lambda value: value,
            },
            "read_file": {
                "schema": _schema("read_file", "Read a local file for context."),
                "callable": lambda value: value,
            },
        }
    )
    monkeypatch.setattr(
        "mirai.core.tool_routing.load_model_config",
        lambda: ModelConfig(edge_tools_enable_dynamic_routing=True, edge_tools_retrieval_limit=3),
    )
    clear_tool_routing_traces()
    yield
    TOOL_REGISTRY.clear()
    TOOL_REGISTRY.update(original)
    clear_tool_routing_traces()


def test_core_tools_are_always_loaded_and_edge_tools_are_ranked():
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="Please turn on the kitchen lights",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(25),
    )

    names = [tool["function"]["name"] for tool in decision.tools]
    assert "remember_user_preference" in names
    assert "read_file" in names
    assert "edge_lab__set_kitchen_lights" in names
    assert len(decision.selected_edge_tools) == 3
    assert decision.total_edge_tools == 26


def test_forced_edge_tool_is_kept_even_when_query_changes():
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="Do a generic factory operation",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(50),
        force_edge_tool_names={"edge_lab__set_kitchen_lights"},
    )

    selected = [entry.name for entry in decision.selected_edge_tools]
    assert "edge_lab__set_kitchen_lights" in selected
    assert len(selected) == 3


def test_chinese_queries_can_match_chinese_edge_descriptions():
    registry = _edge_registry(20, special_name="edge_home__open_curtain")
    registry["lab"]["edge_home__open_curtain"] = {
        "schema": _schema("edge_home__open_curtain", "打开客厅窗帘并调整遮光程度。")
    }

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="帮我打开客厅窗帘",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    selected = [entry.name for entry in decision.selected_edge_tools]
    assert "edge_home__open_curtain" in selected


def test_multilingual_queries_can_match_non_english_edge_descriptions():
    registry = _edge_registry(20, special_name="edge_home__open_blinds")
    registry["lab"]["edge_home__open_blinds"] = {
        "schema": _schema("edge_home__open_blinds", "Ouvrir les stores du salon et régler la lumière.")
    }
    registry["lab"]["edge_home__start_bath"] = {
        "schema": _schema("edge_home__start_bath", "お風呂を沸かして温度を調整します。")
    }

    french_decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="ouvre les stores du salon",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )
    japanese_decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="お風呂を沸かして",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    assert "edge_home__open_blinds" in [entry.name for entry in french_decision.selected_edge_tools]
    assert "edge_home__start_bath" in [entry.name for entry in japanese_decision.selected_edge_tools]


def test_embedding_routing_is_preferred_over_lexical_matching(monkeypatch):
    class FakeEmbedProvider:
        def embed(self, model: str, text: str) -> list[float]:  # noqa: ARG002
            if text == "semantic request target" or "opaque device alpha" in text:
                return [1.0, 0.0]
            return [0.0, 1.0]

    monkeypatch.setattr(
        "mirai.core.tool_routing.load_model_config",
        lambda: ModelConfig(
            embedding_model="fake-embedding",
            edge_tools_enable_dynamic_routing=True,
            edge_tools_retrieval_limit=1,
        ),
    )
    monkeypatch.setattr("mirai.core.tool_routing.get_embed_provider", lambda: FakeEmbedProvider())
    registry = {
        "lab": {
            "edge_lab__generic_match": {"schema": _schema("edge_lab__generic_match", "semantic request target")},
            "edge_lab__embedding_only": {"schema": _schema("edge_lab__embedding_only", "opaque device alpha")},
        }
    }

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="semantic request target",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    assert [entry.name for entry in decision.selected_edge_tools] == ["edge_lab__embedding_only"]


def test_meaningful_edge_name_prioritizes_tools_on_that_edge():
    registry = {
        "卧室": {
            "edge_bedroom__set_light": {
                "schema": _schema("edge_bedroom__set_light", "Set the brightness and power state for a light.")
            }
        },
        "厨房": {
            "edge_kitchen__set_light": {
                "schema": _schema("edge_kitchen__set_light", "Set the brightness and power state for a light.")
            }
        },
    }

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="把卧室的灯打开",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    assert [entry.name for entry in decision.selected_edge_tools[:1]] == ["edge_bedroom__set_light"]


def test_tool_description_still_works_when_edge_name_is_not_meaningful():
    registry = {
        "device-001": {
            "edge_device__make_coffee": {
                "schema": _schema("edge_device__make_coffee", "Start brewing coffee and choose cup size.")
            }
        },
        "device-002": {
            "edge_device__set_fan": {"schema": _schema("edge_device__set_fan", "Set fan speed and oscillation.")}
        },
    }

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="brew coffee",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    assert [entry.name for entry in decision.selected_edge_tools[:1]] == ["edge_device__make_coffee"]


def test_disabled_tools_are_not_loaded():
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="remember this and turn on kitchen lights",
        session_id="s1",
        disabled_tools={"remember_user_preference", "edge_lab__set_kitchen_lights"},
        edge_registry=_edge_registry(10),
    )

    names = [tool["function"]["name"] for tool in decision.tools]
    assert "remember_user_preference" not in names
    assert "edge_lab__set_kitchen_lights" not in names
    assert "read_file" in names


def test_dynamic_routing_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        "mirai.core.tool_routing.load_model_config",
        lambda: ModelConfig(edge_tools_enable_dynamic_routing=False, edge_tools_retrieval_limit=3),
    )

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="kitchen lights",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(12),
    )

    assert len(decision.selected_edge_tools) == 13


def test_zero_edge_limit_hides_unforced_edge_tools(monkeypatch):
    monkeypatch.setattr(
        "mirai.core.tool_routing.load_model_config",
        lambda: ModelConfig(edge_tools_enable_dynamic_routing=True, edge_tools_retrieval_limit=0),
    )

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="kitchen lights",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(12),
    )

    assert decision.selected_edge_tools == []
    assert len(decision.tools) == len(TOOL_REGISTRY)


def test_routing_and_usage_telemetry_are_recorded():
    select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="kitchen lights",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(10),
    )
    record_tool_routing_usage(session_id="s1", prompt_tokens=123, completion_tokens=45, model="test-model")

    traces = list_tool_routing_traces(session_id="s1", limit=10)
    assert any(rec.get("selected_edge_tools") for rec in traces)
    assert any(rec.get("type") == "usage" and rec.get("prompt_tokens") == 123 for rec in traces)


@pytest.mark.parametrize("count", [10, 50, 100, 500, 1000])
def test_edge_tool_routing_scales_to_large_registries(count):
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="Adjust the kitchen lights",
        session_id=f"scale-{count}",
        disabled_tools=set(),
        edge_registry=_edge_registry(count),
    )

    selected = [entry.name for entry in decision.selected_edge_tools]
    assert "edge_lab__set_kitchen_lights" in selected
    assert len(selected) <= 3
    assert len(decision.tools) <= len(TOOL_REGISTRY) + 3
