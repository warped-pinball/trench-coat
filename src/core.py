import os
import shutil
import sys
import time

import src.ray as ray  # Import the ray module with direct serial functions

# Known USB vendor/product ID for the Pico (RP2040 MicroPython)
PICO_VID = 0x2E8A
PICO_PID = 0x0005
BAUD_RATE = 115200  # Standard baud rate for MicroPython REPL


def flash_firmware(firmware_path, ports=None):
    """Core function to flash firmware to devices"""
    ports = ports or []

    # Enter bootloader mode for normal ports
    for port in ports:
        print(f"Putting {port} into bootloader mode...")
        ray.enter_bootloader_mode(port, BAUD_RATE)

    # Setup a timeout to wait for bootloader drives to appear
    max_wait_time = 20  # Maximum wait time in seconds
    start_time = time.time()
    bootloader_drives = []

    while len(bootloader_drives) < len(ports):
        if (time.time() - start_time) > max_wait_time:
            raise TimeoutError("Timeout waiting for devices to appear in bootloader mode.")
        time.sleep(1)
        bootloader_drives = list_rpi_rp2_drives()

    if not bootloader_drives:
        raise RuntimeError("No devices found in bootloader mode. Please try again.")

    for drive in bootloader_drives:
        print(f"Flashing {firmware_path} to {drive}")
        copy_uf2_to_bootloader(firmware_path, drive)


def copy_uf2_to_bootloader(firmware_path, drive=None):
    """Copy the UF2 file to the bootloader drive"""
    if drive:
        print(f"Flashing UF2 to {drive}")
        shutil.copy(firmware_path, drive)
        return

    drives = list_rpi_rp2_drives()

    if len(drives) == 0:
        print("No Warped Pinball devices found in bootloader mode. Please put the device in bootloader mode and try again.")
        sys.exit(0)

    for i, drive in enumerate(drives):
        print(f"Flashing board {i+1} of {len(drives)}")
        shutil.copy(firmware_path, drive)


def resource_path(relative_path: str) -> str:
    """Returns the absolute path to a resource that may be bundled by PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        return os.path.join(os.path.dirname(__file__), relative_path)


def list_bundled_uf2():
    """List available bundled UF2 files"""
    uf2_dir = resource_path("uf2")
    if not os.path.isdir(uf2_dir):
        return []
    return [os.path.join(uf2_dir, f) for f in os.listdir(uf2_dir) if f.lower().endswith(".uf2")]


def list_rpi_rp2_drives():
    """List all RPI-RP2 drives on Windows, Linux, or macOS"""
    if os.name == "nt":
        return list_rpi_rp2_drives_windows()
    else:
        return list_rpi_rp2_drives_linux_macos()


def list_rpi_rp2_drives_windows():
    """List all RPI-RP2 drives on Windows"""
    import string

    found_drives = []
    for drive in string.ascii_uppercase:
        info_path = f"{drive}:\\INFO_UF2.TXT"
        if os.path.exists(info_path):
            found_drives.append(f"{drive}:\\")
    return found_drives


def list_rpi_rp2_drives_linux_macos():
    """List all RPI-RP2 drives on Linux/macOS"""
    found_drives = []
    for drive_dir in ["/Volumes", "/media"]:
        if not os.path.isdir(drive_dir):
            continue
        for root, dirs, files in os.walk(drive_dir):
            if "INFO_UF2.TXT" in files:
                found_drives.append(root)
    return found_drives
