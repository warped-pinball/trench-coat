import base64
import os
import time
from typing import Union

import serial
import serial.tools.list_ports

PICO_VID = 0x2E8A
PICO_PID = 0x0005


class Ray:
    def __init__(self, port: str):
        self.port = port
        self.ser = serial.Serial(port, 115200, timeout=0.1)
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

    def copy_file_to_board(self, local_path: str, remote_path: str, chunk_size: int = 2048):
        # Read and send the file in chunks
        print(f"\r{remote_path}: 0%", end="", flush=True)
        with open(local_path, "rb") as local_file:
            command = [
                "import os",
                "import binascii",
            ]
            if len(os.path.dirname(remote_path)) > 0:
                command += [
                    # ensure the directory exists
                    "try:",
                    f"    os.mkdir('/{os.path.dirname(remote_path)}')",
                    "except OSError:",
                    "    pass",
                    "",
                ]
            command += [
                # open the file for writing
                f"f = open('{remote_path}', 'wb')",
                # define a function to convert base64 to binary and write to file
                "def w(data):",
                "    f.write(binascii.a2b_base64(data))",
                "    f.flush()",
                "",
            ]

            self.send_command(command=command)

            buffer = local_file.read()
            total_size = len(buffer)
            transferred = 0

            # Process the file in chunks
            for i in range(0, len(buffer), chunk_size):
                chunk = buffer[i : i + chunk_size]
                # Convert to base64
                base64_str = base64.b64encode(chunk).decode("ascii")
                # Send command to decode base64 and write to file
                self.send_command(f"w('{base64_str}')")

                # Update progress on same line
                transferred += len(chunk)
                percent = (transferred / total_size) * 100
                print(f"\r{remote_path}: {percent:.1f}%", end="", flush=True)

            # Print newline after completion
            print()

        # Close the file on the board
        self.send_command("f.close()")

    def send_command(self, command: Union[str, list[str]]):
        """
        Send a command to the MicroPython board over the established serial connection and return its output.
        Supports multi-line commands. Command can be either a string or a list of strings.
        If a list is provided, it will be joined with newline and carriage return characters.
        """
        if isinstance(command, list):
            command = "\n\r".join(command)

        # Make sure the serial port is open
        if not self.ser.is_open:
            self.ser.open()

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
