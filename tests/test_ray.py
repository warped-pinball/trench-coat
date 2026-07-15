import base64
import hashlib

import pytest

from src.ray import PICO_VID, Ray


def make_file(filename, contents=b"data", metadata=None):
    return {
        "filename": filename,
        "metadata": metadata or {},
        "base64_contents": base64.b64encode(contents).decode(),
    }


class TestGenerateTransferScript:
    def test_generated_script_is_valid_python(self):
        """Every block the generator yields must be syntactically valid Python.

        This is the contract with the board: blocks are sent with
        ignore_response=True, so a SyntaxError would fail silently.
        """
        files = [
            make_file("main.py"),
            make_file("lib/util.py", b"x" * 20000),  # forces chunked w() calls
            make_file("setup.py", metadata={"execute": True}),
        ]
        blocks = list(Ray.generate_transfer_script(files, progress=False))
        assert blocks
        compile("\n".join(blocks), "<transfer-script>", "exec")
        for block in blocks:
            compile(block, "<transfer-block>", "exec")

    def test_hash_check_lines_match_contents(self):
        contents = b"hello board"
        expected = hashlib.sha256(contents).hexdigest()
        blocks = list(Ray.generate_transfer_script([make_file("main.py", contents)], progress=False))
        script = "\n".join(blocks)
        assert f"hash_check('/main.py', '{expected}')" in script

    def test_leading_slash_and_mkdir(self):
        blocks = list(Ray.generate_transfer_script([make_file("lib/deep/mod.py")], progress=False))
        script = "\n".join(blocks)
        assert "f = open('/lib/deep/mod.py', 'wb')" in script
        assert "mdir('/lib/deep')" in script

    def test_execute_flag(self):
        blocks = list(Ray.generate_transfer_script([make_file("run_me.py", metadata={"execute": True})], progress=False))
        assert "execute_file('/run_me.py')" in "\n".join(blocks)

    def test_missing_filename_raises(self):
        with pytest.raises(ValueError):
            list(Ray.generate_transfer_script([make_file("")], progress=False))


class TestGetFilesToUpdate:
    def _board_with_index(self, monkeypatch, index):
        board = Ray.__new__(Ray)  # no serial port needed
        monkeypatch.setattr(board, "sha256_index", lambda: index, raising=False)
        return board

    def test_new_file_is_required(self, monkeypatch):
        board = self._board_with_index(monkeypatch, {})
        files = [make_file("main.py")]
        assert board.get_files_to_update(files) == ["/main.py"]

    def test_matching_file_is_skipped(self, monkeypatch):
        contents = b"same"
        digest = hashlib.sha256(contents).hexdigest()
        board = self._board_with_index(monkeypatch, {"/main.py": digest})
        assert board.get_files_to_update([make_file("main.py", contents)]) == []

    def test_changed_file_is_required(self, monkeypatch):
        board = self._board_with_index(monkeypatch, {"/main.py": "0" * 64})
        assert board.get_files_to_update([make_file("main.py", b"new contents")]) == ["/main.py"]


class FakeSerial:
    """Minimal stand-in for serial.Serial: records writes, replays queued reads."""

    def __init__(self, responses=b""):
        self.is_open = True
        self.written = b""
        self._pending = responses

    @property
    def in_waiting(self):
        return len(self._pending)

    def read(self, n):
        data, self._pending = self._pending[:n], self._pending[n:]
        return data

    def write(self, data):
        self.written += data

    def flushInput(self):
        self._pending = b""

    def flushOutput(self):
        pass


class TestSendCommandWaitForCompletion:
    def _board_with_serial(self, ser):
        board = Ray.__new__(Ray)
        board.port = "FAKE"
        board.ser = ser
        return board

    def test_drains_response_until_prompt(self):
        # Raw REPL response: OK, stdout, EOT, stderr, EOT, prompt.
        ser = FakeSerial(b"OK[]\x04\x04>")
        board = self._board_with_serial(ser)
        result = board.send_command("print('x')", ignore_response=True, wait_for_completion=True, read_timeout=1)
        assert result is None
        assert ser.in_waiting == 0  # everything drained

    def test_times_out_when_command_never_finishes(self):
        ser = FakeSerial(b"OK")  # no completion trailer ever arrives
        board = self._board_with_serial(ser)
        with pytest.raises(TimeoutError):
            board.send_command("while True: pass", ignore_response=True, wait_for_completion=True, read_timeout=0.2)

    def test_ignore_response_without_wait_returns_immediately(self):
        ser = FakeSerial()
        board = self._board_with_serial(ser)
        assert board.send_command("import machine", ignore_response=True) is None
        assert ser.written.endswith(b"\x04")


class FakePortInfo:
    def __init__(self, vid=None, hwid=""):
        self.vid = vid
        self.hwid = hwid


class TestPortIsBoard:
    def test_matches_pico_vid(self):
        assert Ray._port_is_board(FakePortInfo(vid=PICO_VID))

    def test_rejects_other_vid(self):
        assert not Ray._port_is_board(FakePortInfo(vid=0x1234, hwid="USB VID:PID=1234:5678"))

    def test_windows_hwid_fallback(self):
        # Windows sometimes leaves vid=None but the hwid string carries it.
        assert Ray._port_is_board(FakePortInfo(vid=None, hwid="USB VID:PID=2E8A:0005 SER=1234"))
        assert Ray._port_is_board(FakePortInfo(vid=None, hwid=r"USB\VID_2E8A&PID_0005\1234"))

    def test_none_hwid(self):
        assert not Ray._port_is_board(FakePortInfo(vid=None, hwid=None))
