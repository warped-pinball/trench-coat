import serial, time
import serial.tools.list_ports

PICO_VID = 0x2E8A
PICO_PID = 0x0005

def find_boards(vid: int = 0x2E8A, pid: int =0x0005) -> list:
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

def copy_file_to_board(port: str, baud: int, local_path: str, remote_path: str) -> bool:
    """
    Copy a local text file to the MicroPython board's filesystem.
    Returns True if successful, False if an error occurred.
    """
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        print(f"Failed to open port {port}: {e}")
        return False

    try:
        # Open file on MicroPython for writing
        cmd = f"f = open('{remote_path}', 'w')"
        ser.write((cmd + '\r\n').encode('utf-8'))
        time.sleep(0.1)
        ser.read(ser.in_waiting or 1)  # flush echo

        # Read local file and send its contents
        with open(local_path, 'r') as f:
            for line in f:
                # Ensure each line is properly terminated with newline in the file
                # Escape single quotes in the line to not break the string syntax
                safe_line = line.rstrip("\n").replace("'", "\\'")
                cmd = f"f.write('{safe_line}\\n')"
                ser.write((cmd + '\r\n').encode('utf-8'))
                time.sleep(0.05)
                ser.read(ser.in_waiting or 1)  # flush echo for each line

        # Close the file on the device
        ser.write(b"f.close()\r\n")
        time.sleep(0.1)
        ser.read(ser.in_waiting or 1)
    except Exception as e:
        print(f"Error during file transfer: {e}")
        return False
    finally:
        ser.close()
    return True

def send_command(port: str, baud: int, command: str, timeout: float = 1) -> str:
    """
    Send a command to a MicroPython board over serial and return its output.
    Handles REPL interaction more robustly.
    """
    try:
        # Open serial connection
        with serial.Serial(port, baud, timeout=timeout) as ser:
            # Interrupt any running program
            ser.write(b"\r\x03\x03")  # Send Ctrl+C twice
            time.sleep(0.1)
            
            # Clear any pending input
            ser.read(ser.in_waiting or 1)
            
            # Send the command followed by Enter
            ser.write(f"{command}\r\n".encode('utf-8'))
            time.sleep(0.1)
            
            # Read the response (which includes command echo)
            output = ser.read(ser.in_waiting or 1).decode('utf-8', errors='ignore')
            
            return output
    except Exception as e:
        print(f"Error during communication: {e}")
        return None

def enter_bootloader_mode(port: str, baud: int = 115200) -> bool:
    """
    Put a MicroPython board into bootloader mode.
    Returns True if the command was sent successfully.
    """
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
            ser.write(command.encode('utf-8'))
            
            # The device will disconnect immediately, so we can't expect a response
            # Just a short delay to ensure the command is sent
            time.sleep(0.5)
            
            return True
    except Exception as e:
        print(f"Error entering bootloader mode: {e}")
        return False