"""/health reports which layers are actually installed.

A version in a source file describes the working copy. This describes the
artefact that is running, which is the question worth being able to answer
about a deployment — previously it could only be answered by SSHing in.
"""

from __future__ import annotations

from importlib.metadata import version

from yumi.core.features.health.router import installed_versions


def test_reports_the_installed_agent_version():
    installed_versions.cache_clear()
    assert installed_versions()["yumi-agent"] == version("yumi-agent")


def test_omits_layers_that_are_not_installed():
    # yumi-enterprise and yumi-nexus are not installed in this environment, and
    # a missing layer must be absent rather than an error or a null.
    installed_versions.cache_clear()
    reported = installed_versions()
    assert "yumi-agent" in reported
    assert all(isinstance(v, str) and v for v in reported.values())
