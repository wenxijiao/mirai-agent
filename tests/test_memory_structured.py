"""Structured memory, tool observations, and ContextBuilder behavior."""

from __future__ import annotations

import tempfile

from mirai.core.memories.memory import Memory


def test_message_write_extracts_long_term_preference():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_pref", storage_dir=td, max_recent=20)
        m.add_message("user", "Please remember that from now on you should answer in concise English.")

        memories = m.list_long_term_memories(kind="preference", session_id="s_pref")
        assert len(memories) == 1
        assert "concise English" in memories[0]["content"]
        assert memories[0]["source_message_ids"]


def test_tool_turn_writes_observation_and_context_retrieves_it():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_tool_obs", storage_dir=td, max_recent=20)
        m.persist_openai_messages(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": {"path": "README.md"}},
                        }
                    ],
                },
                {"role": "tool", "name": "read_file", "content": "README says Mirai is local-first."},
            ]
        )

        observations = m.list_tool_observations(session_id="s_tool_obs")
        assert len(observations) == 1
        assert observations[0]["tool_name"] == "read_file"
        assert "local-first" in observations[0]["result_summary"]

        ctx = m.get_context(query="What did the read_file tool return?")
        structured = [msg for msg in ctx if msg["role"] == "system" and "Structured memory" in msg["content"]]
        assert structured
        assert "read_file" in structured[0]["content"]


def test_session_summary_is_included_before_recent_messages():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_summary", storage_dir=td, max_recent=20)
        m.update_session_summary("The user is refactoring the Mirai memory subsystem.")
        m.add_message("user", "What should we do next?")

        ctx = m.get_context(query="continue")
        contents = [msg["content"] for msg in ctx if msg["role"] == "system"]
        assert any("Current session summary" in content for content in contents)
        assert any("refactoring the Mirai memory" in content for content in contents)


def test_hybrid_structured_retrieval_falls_back_to_keyword():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_hybrid", storage_dir=td, max_recent=20)
        m.create_long_term_memory(
            kind="fact", content="This project stores memory in LanceDB.", session_id="s_hybrid"
        )

        ctx = m.get_context(query="How is LanceDB memory stored?")
        structured = [msg for msg in ctx if msg["role"] == "system" and "Structured memory" in msg["content"]]
        assert structured
        assert "LanceDB" in structured[0]["content"]
