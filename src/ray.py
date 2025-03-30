import base64
import time

import serial
import serial.tools.list_ports

PICO_VID = 0x2E8A
PICO_PID = 0x0005


def find_boards(vid: int = 0x2E8A, pid: int = 0x0005) -> list:
    """
    Find all connected boards with a specific VID and PID.
    Returns a list of serial port names.
    """
    boards = []
    for port in serial.tools.list_ports.comports():
        if port.vid is not None and port.pid is not None:
            if (port.vid == vid) and (port.pid == pid):
                boards.append(port.device)
    return boards


def copy_file_to_board(port: str, baud: int, local_path: str, remote_path: str, chunk_size: int = 1024):
    # Read and send the file in chunks
    with open(local_path, "rb") as local_file:
        # Make sure binascii module is available on the board
        send_command(
            port,
            baud,
            "\n\r".join(
                [
                    "import os",
                    "import binascii",
                    # open the file for writing
                    f"f = open('{remote_path}', 'wb')",
                    # define a function to convert base64 to binary and write to file
                    "def w(data):",
                    "    f.write(binascii.a2b_base64(data))" "",
                ]
            ),
        )

        buffer = local_file.read()
        total_size = len(buffer)
        transferred = 0

        # Process the file in chunks
        for i in range(0, len(buffer), chunk_size):
            chunk = buffer[i : i + chunk_size]
            # Convert to base64
            base64_str = base64.b64encode(chunk).decode("ascii")
            # Send command to decode base64 and write to file
            send_command(port, baud, f"w('{base64_str}')")

            # Update progress on same line
            transferred += len(chunk)
            percent = (transferred / total_size) * 100
            print(f"\r{remote_path}: {percent:.1f}%", end="", flush=True)

        # Print newline after completion
        print()

    # Close the file on the board
    send_command(port, baud, "f.close()")


def send_command(port: str, baud: int, command: str, timeout: float = 1) -> str:
    """
    Send a command to a MicroPython board over serial and return its output.
    Supports multi-line commands.
    """
    try:
        # Open serial connection
        with serial.Serial(port, baud, timeout=timeout) as ser:
            # Interrupt any running program
            ser.write(b"\r\x03\x03")  # Send Ctrl+C twice
            time.sleep(0.1)

            # Clear any pending input
            ser.read(ser.in_waiting or 1)

            # Send the line followed by Enter
            ser.write(f"{command}\r\n".encode("utf-8"))
            time.sleep(0.1)

            # Read the response after each line
            return ser.read(ser.in_waiting or 1).decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"Error during communication: {e}")
        return None


def enter_bootloader_mode(port: str, baud: int = 115200):
    try:
        # Open serial connection
        with serial.Serial(port, baud, timeout=1) as ser:
            # Stop any running program
            ser.write(b"\r\x03\x03")  # Ctrl+C twice
            time.sleep(0.1)

            # Clear input buffer
            ser.read(ser.in_waiting or 1)

            # Send the machine.bootloader() command
            command = "import machine; machine.bootloader()\r\n"
            ser.write(command.encode("utf-8"))
    except Exception as e:
        raise Exception(f"Failed to enter bootloader mode: {e}")


def wipe_board(port: str, baud: int = 115200):
    send_command(
        port,
        baud,
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
