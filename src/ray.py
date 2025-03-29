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


def copy_file_to_board(port: str, baud: int, local_path: str, remote_path: str, chunk_size: int = 1024) -> bool:
    """
    Copy a local text file to the MicroPython board's filesystem, breaking content into
    small chunks to avoid memory issues.

    Args:
        port: Serial port of the board
        baud: Baud rate
        local_path: Path to local file to copy
        remote_path: Path on the board's filesystem
        chunk_size: Size of chunks to write (default 2048 bytes)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Open the file on the board
        send_command(port, baud, f"f = open('{remote_path}', 'wb')")

        # Read and send the file in chunks
        with open(local_path, "rb") as local_file:
            buffer = local_file.read()
            total_size = len(buffer)
            transferred = 0

            # Process the file in chunks
            for i in range(0, len(buffer), chunk_size):
                chunk = buffer[i : i + chunk_size]
                # Escape special characters
                hex_str = "".join(f"\\x{byte:02x}" for byte in chunk)
                send_command(port, baud, f"f.write(bytes('{hex_str}', 'latin1'))")

                # Update progress on same line
                transferred += len(chunk)
                percent = (transferred / total_size) * 100
                print(f"\rTransferring: {percent:.1f}% complete", end="", flush=True)

            # Print newline after completion
            print()

        # Close the file on the board
        send_command(port, baud, "f.close()")
        return True

    except Exception as e:
        print(f"\nError during file transfer: {e}")
        return False


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
