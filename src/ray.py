import base64
import os
import time
from typing import Union

import serial
import serial.tools.list_ports

PICO_VID = 0x2E8A
PICO_PID = 0x0005
COMMAND_CHUNK_SIZE = 2048


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
            self.ser = serial.Serial(self.port, 115200, timeout=0.1)
            self.ser.flushInput()
            self.ser.flushOutput()

    @classmethod
    def find_boards(cls) -> list:
        boards = []
        for port in serial.tools.list_ports.comports():
            if port.vid is not None and port.pid is not None:
                if port.vid == PICO_VID and port.pid == PICO_PID:
                    boards.append(Ray(port.device))
        return boards

    def copy_files_to_board(self, path_map: dict[str, str]):
        def generate_transfer_script(path_map: dict[str, str]):
            yield "\n\r".join(
                [
                    "import os",
                    "import binascii",
                    "f = None",
                    "def w(data):",
                    "    global f",
                    "    f.write(binascii.a2b_base64(data))",
                    "    f.flush()",
                    "",
                ]
            )

            for local_path, remote_path in path_map.items():
                # For consistency, we always use a leading slash
                if remote_path[0] != "/":
                    remote_path = "/" + remote_path

                if "/" in remote_path[1:]:
                    yield "\n\r".join(
                        [
                            # ensure the directory exists
                            "try:",
                            f"    os.mkdir('/{os.path.dirname(remote_path)}')",
                            "except OSError:",
                            "    pass",
                            "",
                        ]
                    )

                # open the file for writing
                yield f"f = open('{remote_path}', 'wb')"

                with open(local_path, "rb") as local_file:
                    buffer = local_file.read()
                    total_size = len(buffer)
                    transferred = 0

                    # Process the file in chunks
                    for i in range(0, len(buffer), COMMAND_CHUNK_SIZE):
                        chunk = buffer[i : i + COMMAND_CHUNK_SIZE]
                        # Convert to base64 (this also ensures we are slightly under the chunk size limit)
                        base64_str = base64.b64encode(chunk).decode("ascii")
                        # Send command to decode base64 and write to file
                        yield f"w('{base64_str}')"

                        # Update progress on same line
                        transferred += len(chunk)
                        percent = (transferred / total_size) * 100
                        print(f"\r{remote_path}: {percent:.1f}%", end="", flush=True)

                    # Print newline after completion
                    print()

                yield "f.close()"
                # TODO execute the file if needed

        # Generate the transfer script
        transfer_script = generate_transfer_script(path_map)

        # Send Ctrl+C to interrupt any running code
        self.ctrl_c()

        # Send the script to the board in chunks
        next_script = []
        next_script_len = 0
        while next_line := next(transfer_script, None) or next_script:
            if next_line is None:
                self.send_command(next_script)
                next_script = []
                next_script_len = 0
                break

            if next_script_len + len(next_line) > COMMAND_CHUNK_SIZE:
                self.send_command(next_script)
                next_script = [next_line]
                next_script_len = len(next_line)
                next_line = None
            else:
                next_script.append(next_line)
                next_script_len += len(next_line)

    def send_command(self, command: Union[str, list[str]]):
        """
        Send a command to the MicroPython board over the established serial connection and return its output.
        Supports multi-line commands. Command can be either a string or a list of strings.
        If a list is provided, it will be joined with newline and carriage return characters.
        """
        if isinstance(command, list):
            command = "\n\r".join(command)

        # Make sure the serial port is open
        if not hasattr(self, "ser") or not self.ser or not self.ser.is_open:
            self.open()

        # Clear any pending input
        self.ser.read(self.ser.in_waiting or 1)

        # Send the command followed by Enter
        self.ser.write(f"{command}\r\n".encode("utf-8"))
        time.sleep(0.1)

        # return the response
        return self.ser.read(self.ser.in_waiting or 1).decode("utf-8", errors="ignore")

    def ctrl_c(self):
        """
        Send Ctrl+C to the MicroPython board to interrupt any running code.
        """
        try:
            self.ser.write(b"\x03\x03")  # Ctrl+C
            time.sleep(0.5)  # Give time for the interrupt to process
        except Exception:
            # we expect this throw an exception when the board disconnects
            pass

    def enter_bootloader_mode(self):
        try:
            self.ctrl_c()
            self.send_command("import machine; machine.bootloader()")
        except Exception:
            # we expect this throw an exception when the board disconnects
            pass

    def wipe_board(self):
        self.send_command(
            "\n\r".join(
                [
                    "import os",
                    "def remove(path):",
                    "    try:",
                    "        os.remove(path)",
                    "    except OSError:",
                    "        for entry in os.listdir(path):",
                    "            remove('/'.join((path, entry)))",
                    "        os.rmdir(path)",
                    "",
                    "for entry in os.listdir('/'):",
                    "    remove('/' + entry)",
                ]
            ),
        )

    def restart_board(self):
        try:
            self.ctrl_c()
            self.send_command("import machine; machine.reset()")
        except Exception:
            # we excpect this to fail once the board disconnects
            pass
