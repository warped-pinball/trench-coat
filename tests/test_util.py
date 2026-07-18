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
