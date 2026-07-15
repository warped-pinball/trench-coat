import re

import pytest

from src.util import wait_for


class TestWaitFor:
    def test_returns_when_condition_met(self):
        calls = []

        def condition():
            calls.append(1)
            return len(calls) >= 2

        wait_for(condition, timeout=10)
        assert len(calls) == 2

    def test_raises_timeout(self):
        with pytest.raises(TimeoutError):
            wait_for(lambda: False, timeout=0.1)


class TestVersion:
    def test_version_is_semver(self):
        from src import __version__

        assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)

    def test_pyproject_has_no_hardcoded_version(self):
        """src/__init__.py is the single source of truth for the version;
        pyproject.toml must read it dynamically, never pin its own copy."""
        import os

        pyproject = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
        with open(pyproject) as f:
            text = f.read()
        assert 'version = {attr = "src.__version__"}' in text
        assert 'dynamic = ["version"]' in text
