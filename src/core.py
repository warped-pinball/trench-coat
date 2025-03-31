import json
import os
import shutil
import string
import sys
import tempfile
import time
from binascii import a2b_base64

from src.ray import Ray
from src.util import graceful_exit, wait_for


#
# Firmware flashing functions
#
def get_all_boards_into_bootloader():
    # get all bootloader drives
    bootloader_drives = list_rpi_rp2_drives()
    initial_drives = len(bootloader_drives)
    print(f"Found {len(bootloader_drives)} devices already in bootloader mode.")

    # Find all connected devices
    boards = Ray.find_boards()
    initial_boards = len(boards)
    print(f"Found {len(boards)} devices not already in bootloader mode.")
    for board in boards:
        # Put the board in bootloader mode
        print(f"Putting {board.port} into bootloader mode...")
        board.enter_bootloader_mode()

    expected_drive_count = initial_drives + initial_boards

    # Wait for bootloader drives to appear
    def wait_for_bootloader():
        drives = list_rpi_rp2_drives()
        print(f"Waiting for  ({len(drives)} of {expected_drive_count}) devices to appear in bootloader mode", end="")
        return len(drives) >= expected_drive_count

    wait_for(wait_for_bootloader, timeout=60)


def flash_firmware(firmware_path):
    """Core function to flash firmware to devices"""
    get_all_boards_into_bootloader()

    # Get the updated list of bootloader drives
    bootloader_drives = list_rpi_rp2_drives()

    # wipe the board with nuke.uf2
    nuke_path = [path for path in list_bundled_uf2() if "nuke.uf2" in path][0]
    if len(nuke_path) == 0:
        print("Error: nuke.uf2 not found in bundled UF2 files.")
        graceful_exit()

    for drive in bootloader_drives:
        print(f"Flashing {os.path.basename(nuke_path)} to {drive}")
        shutil.copy(nuke_path, drive)

    # Wait for the drives to start executing uf2s
    def wait_for_flash():
        drives = list_rpi_rp2_drives()
        print(f"Waiting for ({len(drives)} of {len(bootloader_drives)}) devices to finish flashing", end="")
        return len(drives) < len(bootloader_drives)

    wait_for(wait_for_flash, timeout=60)

    # Wait for the drives to reappear after nuking
    def wait_for_reappear():
        drives = list_rpi_rp2_drives()
        print(f"Waiting for {len(drives)} of {len(bootloader_drives)} to reappear in bootloader mode", end="")
        return len(drives) >= len(bootloader_drives)

    wait_for(wait_for_reappear, timeout=60)

    # Get the final list of bootloader drives once they're all accounted for
    # (They could have changed paths)
    if len(bootloader_drives) == list_rpi_rp2_drives():
        bootloader_drives = list_rpi_rp2_drives()

    for drive in bootloader_drives:
        print(f"Flashing {os.path.basename(firmware_path)} to {drive}")
        shutil.copy(firmware_path, drive)

    # Wait for the drives to reappear as Ray devices
    def wait_for_rpi_rp2():
        boards = Ray.find_boards()
        print(f"Waiting for ({len(boards)} of {len(bootloader_drives)}) boards to restart", end="")
        return len(boards) >= len(bootloader_drives)

    wait_for(wait_for_rpi_rp2, timeout=60)


def flash_uf2_to_drives(uf2_path, expected_drive_count, wait_after=True):
    """
    Flash a UF2 file to all bootloader drives and optionally wait for them to reappear

    Args:
        uf2_path: Path to the UF2 file to flash
        expected_drive_count: Number of drives expected to be available
        wait_after: Whether to wait for drives to reappear after flashing

    Returns:
        List of bootloader drives after flashing and waiting
    """
    # Get the current list of bootloader drives
    bootloader_drives = list_rpi_rp2_drives()

    # Flash the UF2 to each drive
    for drive in bootloader_drives:
        print(f"Flashing {uf2_path} to {drive}")
        shutil.copy(uf2_path, drive)

    if wait_after:
        time.sleep(5)  # Give devices time to process

        # Wait for the drives to reappear
        def wait_for_reappear():
            drives = list_rpi_rp2_drives()
            print(f"Waiting for ({len(drives)} of {expected_drive_count}) devices to reappear in bootloader mode", end="")
            return len(drives) >= expected_drive_count

        wait_for(wait_for_reappear, timeout=60)

    # Return the updated list of bootloader drives
    return list_rpi_rp2_drives()


def list_bundled_uf2():
    """List available bundled UF2 files"""
    if hasattr(sys, "_MEIPASS"):
        uf2_dir = os.path.join(sys._MEIPASS, "uf2")
    else:
        uf2_dir = os.path.join(os.path.dirname(__file__), "uf2")

    if not os.path.isdir(uf2_dir):
        return []
    return [os.path.join(uf2_dir, f) for f in os.listdir(uf2_dir) if f.lower().endswith(".uf2")]


def list_rpi_rp2_drives():
    """List all RPI-RP2 drives on Windows, Linux, or macOS"""
    found_drives = []
    if os.name == "nt":
        # Check for Windows
        for drive in string.ascii_uppercase:
            info_path = f"{drive}:\\INFO_UF2.TXT"
            if os.path.exists(info_path):
                found_drives.append(f"{drive}:\\")
    else:
        # Check for macOS and Linux
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
def flash_software(software):
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

        boards = Ray.find_boards()
        print(f"Found {len(boards)} devices to flash software to.")
        for i, board in enumerate(boards):
            print(f"Flashing software to {board.port} ({i+1} of {len(boards)})")
            # Copy files to the board
            board.ctrl_c()
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    local_path = os.path.join(root, file)
                    relative_path = os.path.relpath(local_path, extract_dir)
                    board.copy_file_to_board(local_path, relative_path)

        for board in boards:
            # restart the board
            print("Restarting the board...")
            board.restart_board()

        # wait for the boards to reboot
        def wait_for_reboot():
            restarted_boards = Ray.find_boards()
            print(f" ({len(restarted_boards)} of {len(boards)}) restarted", end="")
            return len(boards) <= len(restarted_boards)

        wait_for(wait_for_reboot, timeout=60)

    finally:
        # Clean up the temporary directory
        shutil.rmtree(extract_dir, ignore_errors=True)


# TODO validate all files were correctly copied using hashes
