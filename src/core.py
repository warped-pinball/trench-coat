import json
import os
import shutil
import string
import sys
import tempfile
import time
from binascii import a2b_base64

from src.ray import Ray


#
# Firmware flashing functions
#
def flash_firmware(firmware_path, board: Ray):
    """Core function to flash firmware to devices"""
    # Enter bootloader mode for normal ports
    print(f"Putting {board.port} into bootloader mode...")
    board.enter_bootloader_mode()

    # Setup a timeout to wait for bootloader drives to appear
    start_time = time.time()
    bootloader_drives = []

    while len(bootloader_drives) == 0:
        if (time.time() - start_time) > 20:
            raise TimeoutError("Timeout waiting for devices to appear in bootloader mode.")
        time.sleep(1)
        bootloader_drives = list_rpi_rp2_drives()

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


#
# Software flashing functions
#
def flash_software(software, board: Ray):
    # confirm known update format
    with open(software, "r") as f:
        software_metadata = json.loads(f.readline())
        if "update_file_format" not in software_metadata:
            print("Error: file format not specified in update.json.")
            sys.exit(1)
        if software_metadata["update_file_format"] != "1.0":
            print("Error: update.json file format not recognized. Check for more recent versions of this program.")
            sys.exit(1)
    print("Software file format confirmed.")

    # Create a temporary directory for extracted files
    extract_dir = tempfile.mkdtemp(prefix="software_update_")
    print(f"Extracting files to temporary directory: {extract_dir}")

    try:
        # iterate over the files in the update.json file (each line except the first)
        with open(software, "r") as f:
            f.readline()  # Skip the first line (metadata)

            for line in f.readlines():
                line = line.strip()
                if line == "":
                    continue

                # split the line into filename, metadata, and contents
                filename, metadata_and_contents = line.split("{", 1)
                metadata, contents = metadata_and_contents.split("}", 1)
                metadata = json.loads("{" + metadata + "}")

                # decode base64 contents
                contents = a2b_base64(contents)

                # Write contents to local file
                file_path = os.path.join(extract_dir, filename)

                # Create directories if needed
                os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)

                if filename == "":
                    # This is probably the last line in the file, which is the signature
                    continue

                with open(file_path, "wb") as local_file:
                    local_file.write(contents)

                if metadata.get("execute", False):
                    print(f"File would be executed on board: {filename}")

        # Wipe all files from the board
        print("Wiping all files from the board recursively...")
        board.wipe_board()

        # Copy files to the board
        for root, dirs, files in os.walk(extract_dir):
            for file in files:
                local_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, extract_dir)
                board.copy_file_to_board(local_path, relative_path)

        # restart the board
        print("Restarting the board...")
        board.restart_board()
    finally:
        # Clean up the temporary directory
        shutil.rmtree(extract_dir, ignore_errors=True)


# TODO add instructions for when the board doesn't show up (go to boot loader mode and nuke)
