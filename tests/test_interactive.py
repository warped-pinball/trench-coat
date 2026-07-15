import hashlib
import json

import pytest

import src.interactive as interactive
from src.interactive import (
    _identify_with_retry,
    _parse_release_versions,
    read_last_significant_line,
    validate_update_file,
)


class FakeRay:
    """Stand-in for Ray whose identify() fails a set number of times."""

    identity = {"processor": "rp2350", "board": "Pico 2 W", "system": "wpc"}
    failures_left = 0

    def __init__(self, port):
        self.port = port

    def identify(self):
        if FakeRay.failures_left > 0:
            FakeRay.failures_left -= 1
            raise TimeoutError("board still booting")
        return dict(FakeRay.identity)

    def close(self):
        pass


class TestIdentifyWithRetry:
    def test_keeps_retrying_while_board_boots(self, monkeypatch):
        # A freshly plugged-in board doesn't answer until its firmware has
        # finished booting; the retry loop must outlast many failed attempts.
        monkeypatch.setattr(interactive, "Ray", FakeRay)
        monkeypatch.setattr(interactive.time, "sleep", lambda s: None)
        FakeRay.failures_left = 10
        waits = []
        info = _identify_with_retry("COM7", timeout=60, on_wait=lambda: waits.append(1))
        assert info == FakeRay.identity
        assert waits == [1]  # on_wait fires once, after the first failure

    def test_gives_up_after_deadline(self, monkeypatch):
        monkeypatch.setattr(interactive, "Ray", FakeRay)
        monkeypatch.setattr(interactive.time, "sleep", lambda s: None)
        FakeRay.failures_left = 10**9
        clock = iter(range(10**9))
        monkeypatch.setattr(interactive.time, "monotonic", lambda: next(clock))
        assert _identify_with_retry("COM7", timeout=45) is None


class TestParseReleaseVersions:
    def test_parses_versions_block(self):
        body = "## Versions\n\n**Vector**: `1.11.10`\n**WPC**: `1.7.5`\n**Sys11**: `2.0.1`\n"
        assert _parse_release_versions(body) == {"Vector": "1.11.10", "WPC": "1.7.5", "Sys11": "2.0.1"}

    def test_empty_or_missing_body(self):
        assert _parse_release_versions("") == {}
        assert _parse_release_versions(None) == {}
        assert _parse_release_versions("no versions here") == {}


class TestReadLastSignificantLine:
    def test_skips_trailing_blank_lines(self, tmp_path):
        path = tmp_path / "f.txt"
        path.write_text("first\nlast\n\n\n")
        assert read_last_significant_line(str(path)) == b"last"

    def test_empty_file_raises(self, tmp_path):
        path = tmp_path / "f.txt"
        path.write_text("\n\n")
        with pytest.raises(ValueError):
            read_last_significant_line(str(path))


def write_update_file(tmp_path, content, sha256_hex, signature_b64="QUJD"):
    path = tmp_path / "update.json"
    sig_line = json.dumps({"sha256": sha256_hex, "signature": signature_b64})
    path.write_text(content + "\n" + sig_line + "\n")
    return str(path)


class TestValidateUpdateFile:
    CONTENT = json.dumps({"update_file_format": "1.0"}) + "\nmain.py{}aGVsbG8="

    def test_hash_mismatch_fails(self, tmp_path):
        path = write_update_file(tmp_path, self.CONTENT, "00" * 32)
        assert validate_update_file(path) is False

    def test_bad_signature_fails(self, tmp_path):
        digest = hashlib.sha256(self.CONTENT.encode()).hexdigest()
        path = write_update_file(tmp_path, self.CONTENT, digest)
        assert validate_update_file(path) is False

    def test_valid_hash_and_signature_passes(self, tmp_path, monkeypatch):
        # We don't hold the private key, so stub out the RSA check and
        # verify the hash-integrity path end to end.
        digest = hashlib.sha256(self.CONTENT.encode()).hexdigest()
        path = write_update_file(tmp_path, self.CONTENT, digest)
        monkeypatch.setattr(interactive.rsa, "verify", lambda *a, **k: "SHA-256")
        assert validate_update_file(path) is True
