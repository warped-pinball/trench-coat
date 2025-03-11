#!/usr/bin/env python3

import sys
import os
import time
import subprocess
import serial.tools.list_ports



# Known USB vendor/product ID for the Pico (RP2040 MicroPython)
PICO_VID = 0x2E8A
PICO_PID = 0x0005


def resource_path(relative_path: str) -> str:
    """
    Returns the absolute path to a resource that may be bundled by PyInstaller.
    If running in a PyInstaller one-file bundle, sys._MEIPASS points to the
    temp extraction folder. Otherwise, we use the directory of this script.
    """
    if hasattr(sys, "_MEIPASS"):
        # Running in PyInstaller one-file bundle
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        # Running directly from source
        return os.path.join(os.path.dirname(__file__), relative_path)


def find_pico_ports():
    """
    Returns a list of serial.tools.list_ports_common.ListPortInfo objects
    matching the known VID/PID for a MicroPython-enabled RP2040 board.
    """
    pico_ports = []
    for port in serial.tools.list_ports.comports():
        if port.vid is not None and port.pid is not None:
            if (port.vid == PICO_VID) and (port.pid == PICO_PID):
                pico_ports.append(port)
    return pico_ports


def pick_pico_port():
    """
    Detects Pico boards on USB (running MicroPython). Returns a chosen port (str),
    or None if none found/selected.
    """
    ports = find_pico_ports()
    if not ports:
        print("No Pico W running MicroPython found.")
        print("If the board is in BOOTSEL mode (mass storage), we can skip direct detection.")
        print("Press Enter to continue or Ctrl+C to abort.")
        input()
        return None
    elif len(ports) == 1:
        print(f"Detected one Pico W on port: {ports[0].device}")
        return ports[0].device
    else:
        print("Multiple Pico or RP2040 devices found:")
        for i, p in enumerate(ports, start=1):
            print(f"{i}. {p.device} - {p.description}")
        choice_str = input(f"Select a device [1-{len(ports)}]: ").strip()
        try:
            choice = int(choice_str)
            if 1 <= choice <= len(ports):
                return ports[choice - 1].device
        except ValueError:
            pass
        print("Invalid selection. Defaulting to first device.")
        return ports[0].device


def enter_bootloader(port):
    """
    Uses mpremote to instruct the Pico to reboot into UF2 bootloader mode.
    Returns True if successful, False otherwise.
    """
    print("Rebooting device into bootloader mode via mpremote...")
    try:
        result = subprocess.run(
            ["mpremote", "connect", port, "bootloader"],
            capture_output=True, text=True
        )
    except FileNotFoundError:
        print("Error: 'mpremote' command not found. Is it installed/bundled?")
        return False
    if result.returncode != 0:
        print("Error: mpremote failed to enter bootloader.")
        print("mpremote output:\n", result.stdout or result.stderr)
        return False
    return True


def find_rpi_rp2_drive_windows():
    """
    On Windows, scans A: through Z: to find the drive that contains INFO_UF2.TXT,
    which indicates the RPI-RP2 bootloader volume.
    Returns the drive letter with a trailing slash (e.g. 'E:\\'), or None if not found.
    """
    import string
    for drive in string.ascii_uppercase:
        drive_path = f"{drive}:\\INFO_UF2.TXT"
        if os.path.exists(drive_path):
            return f"{drive}:\\"
    return None


def find_rpi_rp2_drive_linux_macos():
    """
    On Linux/macOS, scans /Volumes and /media to find the drive that contains INFO_UF2.TXT,
    which indicates the RPI-RP2 bootloader volume.
    Returns the drive path (e.g. '/Volumes/RPI-RP2'), or None if not found.
    """
    for drive_dir in ['/Volumes', '/media']:
        if not os.path.isdir(drive_dir):
            continue
        for root, dirs, files in os.walk(drive_dir):
            if "INFO_UF2.TXT" in files:
                return root
    return None


def copy_uf2_to_bootloader(firmware_path):
    """
    Attempt to copy the .uf2 file to the RPI-RP2 drive (if found).
    If not found, print instructions for manual copy.
    """
    # Try to find the Pico bootloader drive
    pico_drive = None
    print("Looking for Pico in bootloader mode...")

    try:
        if os.name == 'nt':  # Windows
            print("Waiting a few seconds for the BOOTSEL drive to appear...")
            time.sleep(2)
            pico_drive = find_rpi_rp2_drive_windows()
        else:  # Linux/macOS
            pico_drive = find_rpi_rp2_drive_linux_macos()

        if pico_drive:
            print(f"Found Pico's bootloader drive at {pico_drive}")
            print(f"Copying {firmware_path} to {pico_drive} ...")
            import shutil
            try:
                shutil.copy(firmware_path, pico_drive)
                print("Copy complete. The board should reboot into MicroPython shortly.")
                return True
            except Exception as e:
                print(f"Error copying file: {e}")
                print("You may need to copy the file manually.")
        else:
            print("Unable to auto-detect the RPI-RP2 drive.")
    except Exception as e:
        print(f"Error during drive detection: {e}")

    # If we get here, automatic flashing failed
    print("\nManual flashing instructions:")
    print("1. Look for a drive named 'RPI-RP2' in your file explorer")
    print("2. Copy the UF2 file to this drive")
    print("3. The Pico should automatically reboot once the file is copied")
    print("\nPress Enter once done, or Ctrl+C to abort.")
    input()
    return True


# ---------------------
# NEW: Bundled UF2 logic
# ---------------------

def list_bundled_uf2():
    """
    Returns a list of .uf2 files that were bundled into the PyInstaller executable,
    located under uf2/ in the build. If none are found, returns [].
    """
    uf2_dir = resource_path("uf2")  # The embedded folder
    if not os.path.isdir(uf2_dir):
        return []
    files = [f for f in os.listdir(uf2_dir) if f.lower().endswith(".uf2")]
    return [os.path.join(uf2_dir, f) for f in files]


def pick_bundled_uf2():
    """
    Interactively let the user choose from the embedded UF2 files in uf2/.
    Returns the chosen file path, or None if user cancels or none found.
    """
    uf2_files = list_bundled_uf2()
    if not uf2_files:
        print("No bundled .uf2 files found in the embedded 'uf2' folder.")
        return None

    print("\nAvailable bundled .uf2 files:")
    for i, file_path in enumerate(uf2_files, start=1):
        filename = os.path.basename(file_path)
        print(f"  {i}. {filename}")

    choice = input(f"Select a file [1-{len(uf2_files)} or blank to skip]: ").strip()
    if not choice:
        return None

    try:
        idx = int(choice)
        if 1 <= idx <= len(uf2_files):
            return uf2_files[idx - 1]
    except ValueError:
        pass

    print("Invalid input, skipping.\n")
    return None


def main():
    print("=== Raspberry Pi Pico W MicroPython Flasher ===")
    print("This tool helps you flash a MicroPython .uf2 file onto a Pico W.\n")

    # Step 1: Detect Pico device (if running MicroPython).
    port = pick_pico_port()

    # Step 2: Let user pick from bundled .uf2 or specify their own
    print("\nWould you like to use one of the bundled UF2 files?")
    use_bundled = input("Enter 'y' to select from bundled, or 'n' for custom path [y/n]: ").strip().lower()

    if use_bundled == 'y':
        firmware_path = pick_bundled_uf2()
        if firmware_path:
            print(f"Selected bundled firmware: {os.path.basename(firmware_path)}")
        else:
            print("No bundled firmware selected, falling back to manual path.\n")
            firmware_path = None
    else:
        firmware_path = None

    # If user didn't pick or canceled, prompt for custom path
    if not firmware_path:
        print("Enter path to the MicroPython .uf2 firmware file.")
        custom_path = input("(default: ./micropython.uf2): ").strip()
        if not custom_path:
            custom_path = "./micropython.uf2"
        if not os.path.isfile(custom_path):
            print(f"Firmware file '{custom_path}' does not exist. Exiting.")
            sys.exit(1)
        firmware_path = custom_path

    # Step 3: Confirm with the user
    print(f"\nReady to flash '{firmware_path}' onto the Pico W.")
    confirm = input("Proceed? (y/n): ").lower().strip()
    if confirm != 'y':
        print("Aborted.")
        sys.exit(0)

    # Step 4: If we have a detected MicroPython device, try mpremote bootloader.
    if port:
        ok = enter_bootloader(port)
        if not ok:
            print("Failed to enter bootloader via mpremote.")
            print("Try manually entering BOOTSEL (hold BOOTSEL button and plug in). Exiting.")
            sys.exit(1)
    else:
        # No device found or user skipping detection
        print("Assuming the Pico W is already in BOOTSEL mode (RPI-RP2 drive).")
        print("If not, hold BOOTSEL, plug in the Pico, and a drive should appear.")
        print("Press Enter to continue once the drive is present.")
        input()

    # Step 5: Copy the UF2 to the board (on Windows, try auto; on others, ask user).
    success = copy_uf2_to_bootloader(firmware_path)
    if success:
        print("Firmware flashing process complete.")
        print("If everything went well, the Pico W will reboot into MicroPython now.")
    else:
        print("Firmware flashing encountered errors. Please retry or flash manually.")


if __name__ == "__main__":
    main()
