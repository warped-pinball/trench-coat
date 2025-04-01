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
            self.ser = serial.Serial(self.port, 115200, timeout=0.2)
            self.ser.flushInput()
            self.ser.flushOutput()

    @classmethod
    def find_board_ports(cls) -> list[str]:
        board_ports = []
        for port_info in serial.tools.list_ports.comports():
            if port_info.vid == PICO_VID and port_info.pid == PICO_PID:
                board_ports.append(port_info.device)
        return board_ports

    def write_update_to_board(self, update_files: list[dict[str, str]]):
        def generate_transfer_script(update_files: list[dict[str, str]]):
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

            for file_info in update_files:
                filename = file_info["filename"]
                file_metadata = file_info["metadata"]
                file_contents = file_info["base64_contents"]

                if filename is None or filename == "":
                    print(**file_info)

                # For consistency, we always use a leading slash
                if filename[0] != "/":
                    filename = "/" + filename

                if "/" in filename[1:]:
                    yield "\n\r".join(
                        [
                            # ensure the directory exists
                            "try:",
                            f"    os.mkdir('/{os.path.dirname(filename)}')",
                            "except OSError:",
                            "    pass",
                            "",
                        ]
                    )

                # open the file for writing
                yield f"f = open('{filename}', 'wb')"

                # Process the already base64-encoded file in chunks
                chunk_size = COMMAND_CHUNK_SIZE - 20  # Ensure it's under the limit
                for i in range(0, len(file_contents), chunk_size):
                    percent = (i / len(file_contents)) * 100
                    print(f"\r{filename}: {percent:.1f}%", end="", flush=True)
                    chunk = file_contents[i : i + chunk_size]
                    # Send command to write the base64 data to file
                    yield f"w('{chunk}')"

                print(f"\r{filename}: 100.0%")

                yield "f.close()"

                # TODO execute the file if needed
                if file_metadata.get("execute", False):
                    print(f"File would be executed on board: {filename}")

        # Generate the transfer script
        transfer_script = generate_transfer_script(update_files)

        # Send Ctrl+C to interrupt any running code
        self.ctrl_c()

        # Send the script to the board in chunks
        next_script = []
        next_script_len = 0
        while next_line := next(transfer_script, None):
            if next_script_len + len(next_line) > COMMAND_CHUNK_SIZE:
                self.send_command(next_script)
                next_script = [next_line]
                next_script_len = len(next_line)
                next_line = None
            else:
                next_script.append(next_line)
                next_script_len += len(next_line)

        # Send any remaining lines
        if next_script is not None:
            self.send_command(next_script)

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
