import os
import time
from typing import Union

import serial
import serial.tools.list_ports

PICO_VID = 0x2E8A
PICO_PID = 0x0005
COMMAND_CHUNK_SIZE = 5000


class Ray:
    _instances = set()

    def __init__(self, port: str):
        # Track this instance
        Ray._instances.add(self)

        self.port = port
        self.open()

    def __del__(self):
        # Clean up when the instance is garbage-collected
        self.close()

    def close(self):
        """Properly close the serial connection"""
        if hasattr(self, "ser") and self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass  # Already closed or error closing
        # Remove from tracked instances
        if self in Ray._instances:
            Ray._instances.remove(self)

    @classmethod
    def close_all(cls):
        """Close all Ray instances"""
        for ray in list(cls._instances):
            ray.close()

    def open(self):
        """Open the serial connection"""
        if not hasattr(self, "ser") or not self.ser or not self.ser.is_open:
            self.ser = serial.Serial(self.port, 115200, timeout=0.5)
            self.ser.flushInput()
            self.ser.flushOutput()

    @classmethod
    def find_board_ports(cls) -> list[str]:
        board_ports = []
        for port_info in serial.tools.list_ports.comports():
            if port_info.vid == PICO_VID and port_info.pid == PICO_PID:
                board_ports.append(port_info.device)
        return board_ports

    def ctrl_c(self):
        """
        Send Ctrl+C to the MicroPython board to interrupt any running code.
        """
        try:
            # Sometimes sending it twice helps ensure we fully interrupt
            self.ser.write(b"\x03\x03")  # Ctrl+C
            time.sleep(0.5)  # Give time for the interrupt to process
            # Clear any pending output
            while self.ser.in_waiting:
                self.ser.read(self.ser.in_waiting)
                time.sleep(0.01)
        except Exception:
            # we expect this might throw if the board disconnects
            pass

    def _enter_raw_repl(self):
        """
        Enter raw REPL mode by sending Ctrl-A, then wait for '>' prompt.
        Returns True if raw REPL was successfully entered.
        """
        # In case any code was running, interrupt it first
        self.ctrl_c()

        # Send Ctrl-A to enter raw REPL
        self.ser.write(b"\x01")  # Ctrl-A
        time.sleep(0.1)

        # Read until we get a '>' or timeout
        tstart = time.time()
        raw_response = b""
        while (time.time() - tstart) < 2:
            if self.ser.in_waiting:
                raw_response += self.ser.read(self.ser.in_waiting)
                if b">" in raw_response:
                    return True
            time.sleep(0.01)

        return False

    def _exit_raw_repl(self):
        """
        Exit raw REPL mode by sending Ctrl-B to return to friendly REPL.
        """
        self.ser.write(b"\x02")  # Ctrl-B
        time.sleep(0.1)

    def send_command_raw(self, script: str) -> str:
        """
        Send a script to the MicroPython board in *raw REPL mode*,
        capture and return stdout (combined into one string),
        or raise an exception if there's error output.

        For multi-line scripts, ensure the script is properly
        spaced / indented as needed. We'll send it as-is in raw mode.
        """
        # Make sure the serial port is open
        if not hasattr(self, "ser") or not self.ser or not self.ser.is_open:
            self.open()

        # 1) Enter raw REPL
        if not self._enter_raw_repl():
            raise RuntimeError("Unable to enter raw REPL")

        # 2) Send the script
        # Ensure it ends with a newline so it executes
        if not script.endswith("\n"):
            script += "\n"
        self.ser.write(script.encode("utf-8"))

        # 3) Send Ctrl-D to indicate we're done and want to execute
        self.ser.write(b"\x04")
        time.sleep(0.1)

        # 4) Read the output from the board until we get a Ctrl-D (0x04)
        #    This is the normal output
        normal_output = self._read_until_marker(marker=b"\x04", timeout=2.0)

        # 5) Next, read until another Ctrl-D (or until timeout) for error text
        #    If there's no error, this might be empty or just come immediately
        error_output = self._read_until_marker(marker=b"\x04", timeout=2.0)

        # 6) (Optional) exit raw REPL so we can return to normal usage
        self._exit_raw_repl()

        # Remove trailing \x04 if any
        if normal_output.endswith(b"\x04"):
            normal_output = normal_output[:-1]
        if error_output.endswith(b"\x04"):
            error_output = error_output[:-1]

        # Convert from bytes to str
        normal_str = normal_output.decode("utf-8", errors="replace")
        error_str = error_output.decode("utf-8", errors="replace")

        # If there's anything in error_str, that typically means an exception
        # was thrown. You can handle it how you like; we'll just raise here.
        if error_str.strip():
            raise RuntimeError(f"Error from board:\n{error_str.strip()}")

        return normal_str.strip()

    def _read_until_marker(self, marker: bytes, timeout: float) -> bytes:
        """
        Read from self.ser until we find 'marker' or until 'timeout' has passed.
        Return all bytes read (including the marker).
        """
        tstart = time.time()
        buf = b""
        while (time.time() - tstart) < timeout:
            if self.ser.in_waiting > 0:
                chunk = self.ser.read(self.ser.in_waiting)
                buf += chunk
                if marker in buf:
                    return buf
            else:
                time.sleep(0.01)
        return buf

    def send_command(self, command: Union[str, list[str]]) -> str:
        """
        Wrapper for send_command_raw using raw REPL.
        Accepts either a string or list of strings for multi-line commands.
        Joins list with newlines if needed. Returns the board's stdout as string.
        Raises RuntimeError if there's an error on the board side.
        """
        if isinstance(command, list):
            command = "\n".join(command)
        return self.send_command_raw(command)

    def write_update_to_board(self, update_files: list[dict[str, str]]):
        """
        Example of how we might combine the raw REPL method with chunked upload.
        Note that if you're sending large base64 data, you might prefer
        a different chunking approach or partial reads/writes.
        """

        def generate_transfer_script(files: list[dict[str, str]]):
            setup_lines = [
                "import os",
                "import binascii",
                "f = None",
                "def w(data):",
                "    global f",
                "    f.write(binascii.a2b_base64(data))",
                "    f.flush()",
                "",
                "def mdir(path):",
                "    try:",
                "        os.mkdir(path)",
                "    except OSError:",
                "        pass",
                "",
            ]
            yield "\n".join(setup_lines)

            for i, file_info in enumerate(files):
                # Print progress
                print(f"Uploading file {i + 1} of {len(files)}: {file_info['filename']}" + " " * 20, end="\r")

                filename = file_info["filename"]
                file_metadata = file_info["metadata"]
                file_contents = file_info["base64_contents"]

                if not filename:
                    raise ValueError(f"Missing filename in {file_info}")

                # For consistency, we always use a leading slash
                if not filename.startswith("/"):
                    filename = "/" + filename

                dir_path = os.path.dirname(filename)
                if dir_path not in ["", "/"]:
                    yield f"mdir('{dir_path}')"

                yield f"f = open('{filename}', 'wb')"

                # Process base64 data in chunks
                chunk_size = COMMAND_CHUNK_SIZE - 20
                for i in range(0, len(file_contents), chunk_size):
                    chunk = file_contents[i : i + chunk_size]
                    yield f"w('{chunk}')"

                yield "f.close()"

                # For demonstration if we want to auto-execute
                if file_metadata.get("execute", False):
                    yield f"import {os.path.splitext(os.path.basename(filename))[0]}"

        # Generate the script lines in a generator
        script_lines = generate_transfer_script(update_files)
        current_block = []
        current_len = 0

        # We'll keep sending them in smaller blocks, each executed in raw mode
        for i, line in enumerate(script_lines):
            if current_len + len(line) > COMMAND_CHUNK_SIZE:
                # send the block
                block_script = "\n".join(current_block)
                self.send_command(block_script)
                current_block = [line]
                current_len = len(line)
            else:
                current_block.append(line)
                current_len += len(line)

        # Send any remainder
        if current_block:
            block_script = "\n".join(current_block)
            self.send_command(block_script)

    def enter_bootloader_mode(self):
        """
        Reset the board into the UF2 bootloader (might need physically to reset on some boards).
        """
        try:
            self.ctrl_c()
            self.send_command_raw("import machine\nmachine.bootloader()")
        except Exception:
            pass  # the board will disconnect, so an error is expected

    def wipe_board(self):
        """
        Remove all files and directories on the board's filesystem.
        """
        script = [
            "import os",
            "def remove(path):",
            "    try:",
            "        os.remove(path)",
            "    except OSError:",
            "        for entry in os.listdir(path):",
            "            remove(path + '/' + entry)",
            "        os.rmdir(path)",
            "",
            "for entry in os.listdir('/'):",
            "    remove('/' + entry)",
        ]
        self.send_command(script)

    def restart_board(self):
        """
        Soft reset the board. This causes a reboot, so the serial connection might
        disconnect or the REPL might get re-initialized.
        """
        try:
            self.ctrl_c()
            self.send_command_raw("import machine\nmachine.reset()")
        except Exception:
            pass

    def sha256_index(self) -> dict[str, str]:
        """
        Get the SHA256 of every file on the board as a dict.
        We run code that collects file : digest in JSON, then parse locally.
        """
        script_lines = [
            "import os",
            "import hashlib",
            "import json",
            "import binascii",
            "",
            "files = {}",
            "for entry in os.listdir('/'):",
            "    path = '/' + entry",
            "    try:",
            "        # Skip directories",
            "        if os.stat(path)[0] & 0x4000:",
            "            continue",
            "        sha256 = hashlib.sha256()",
            "        with open(path, 'rb') as f:",
            "            while True:",
            "                chunk = f.read(1024)",
            "                if not chunk:",
            "                    break",
            "                sha256.update(chunk)",
            "        files[path] = binascii.hexlify(sha256.digest()).decode('utf-8')",
            "    except Exception as e:",
            "        files[path] = f'Error: {str(e)}'",
            "",
            "print(json.dumps(files))",
        ]
        output = self.send_command(script_lines)

        # remove anything before first { or after last }
        start = output.find("{")
        end = output.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("Board returned invalid JSON for file hashes")

        output = output[start : end + 1]

        try:
            import json

            return json.loads(output)
        except json.JSONDecodeError as e:
            raise ValueError(f"Board returned invalid JSON for file hashes: {output}") from e


# TODO make sure we can gaurentee if we are in raw repl or not since restart_board doesn't work if the board is in a raw repl mode
