"""Edge workspace scaffolding (``mirai --edge``) helpers."""

import os
import tempfile

import mirai.cli as cli
import pytest
from mirai.edge.client import init_workspace


def test_parse_edge_langs_none():
    assert cli._parse_edge_langs(None) is None


def test_parse_edge_langs_single():
    assert cli._parse_edge_langs(["python"]) == ["python"]


def test_parse_edge_langs_repeatable_dedupes():
    assert cli._parse_edge_langs(["rust", "python", "rust"]) == ["rust", "python"]


def test_parse_edge_langs_comma_separated():
    assert cli._parse_edge_langs(["rust,python"]) == ["rust", "python"]


def test_parse_edge_langs_mixed():
    assert cli._parse_edge_langs(["rust,go", "python"]) == ["rust", "go", "python"]


def test_init_workspace_multi_lang_creates_both_trees():
    with tempfile.TemporaryDirectory() as tmp:
        init_workspace(tmp, lang=["python", "rust"])
        assert os.path.isfile(os.path.join(tmp, "mirai_tools", "python", "mirai_setup.py"))
        assert os.path.isfile(os.path.join(tmp, "mirai_tools", "rust", "Cargo.toml"))


def test_init_workspace_rejects_unknown_lang():
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError, match="Unsupported language"):
            init_workspace(tmp, lang=["python", "not-a-lang"])
