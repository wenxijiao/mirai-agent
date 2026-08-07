"""/health reports which layers are actually installed.

A version in a source file describes the working copy. This describes the
artefact that is running, which is the question worth being able to answer
about a deployment — previously it could only be answered by SSHing in.

The packages above this one are discovered through the plugin entry-point
group, never named. An earlier version of this listed them literally and
test_l1_content_boundaries caught it, which is the boundary doing its job.
"""

from __future__ import annotations

from importlib.metadata import version

from yumi.core.features.health.router import installed_versions


def test_reports_its_own_version():
    installed_versions.cache_clear()
    assert installed_versions()["yumi-agent"] == version("yumi-agent")


def test_every_reported_version_is_a_non_empty_string():
    installed_versions.cache_clear()
    reported = installed_versions()
    assert reported
    assert all(isinstance(name, str) and name for name in reported)
    assert all(isinstance(v, str) and v for v in reported.values())


def test_discovers_registered_layers_without_naming_them(monkeypatch):
    """A package registering a yumi.plugins entry point is reported by name."""

    class _Dist:
        name = "yumi-something-above"
        version = "9.9.9"

    class _EntryPoint:
        dist = _Dist()

    monkeypatch.setattr(
        "yumi.core.features.health.router._iter_entry_points",
        lambda: (_EntryPoint(),),
    )
    installed_versions.cache_clear()
    reported = installed_versions()
    assert reported["yumi-something-above"] == "9.9.9"
    installed_versions.cache_clear()
