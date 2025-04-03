import hashlib
import json
import os
import shutil
import string
import sys
import tempfile
import time

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
    ports = Ray.find_board_ports()
    initial_ports = len(ports)
    print(f"Found {len(ports)} devices not already in bootloader mode.")
    for port in ports:
        # Put the board in bootloader mode
        print(f"Putting {port} into bootloader mode...")
        Ray(port).enter_bootloader_mode()

    expected_drive_count = initial_drives + initial_ports

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

    # give the drives a moment to settle
    time.sleep(5)

    for drive in bootloader_drives:
        print(f"Flashing {os.path.basename(nuke_path)} to {drive}")
        shutil.copy(nuke_path, drive)
        try:
            os.sync()
        except Exception:
            # only available on some platforms
            pass

    # Wait for the drives to start executing uf2s
    def wait_for_flash():
        drives = list_rpi_rp2_drives()
        print(f"Waiting for ({len(bootloader_drives) - len(drives)} of {len(bootloader_drives)}) devices to begin flashing", end="")
        return len(drives) < len(bootloader_drives)

    wait_for(wait_for_flash, timeout=60)

    # Wait for the drives to reappear after nuking
    def wait_for_reappear():
        drives = list_rpi_rp2_drives()
        print(f"Waiting for ({len(drives)} of {len(bootloader_drives)}) devices to enter bootloader mode", end="")
        return len(drives) >= len(bootloader_drives)

    wait_for(wait_for_reappear, timeout=60)

    # Get the final list of bootloader drives once they're all accounted for
    # (They could have changed paths)
    if len(bootloader_drives) == list_rpi_rp2_drives():
        bootloader_drives = list_rpi_rp2_drives()

    # give the drives a moment to settle
    time.sleep(5)

    for drive in bootloader_drives:
        print(f"Flashing {os.path.basename(firmware_path)} to {drive}")
        shutil.copy(firmware_path, drive)
        try:
            os.sync()
        except Exception:
            # only available on some platforms
            pass

    # Wait for the drives to reappear as Ray devices
    def wait_for_rpi_rp2():
        boards = Ray.find_board_ports()
        print(f"Waiting for ({len(boards)} of {len(bootloader_drives)}) boards to restart", end="")
        return len(boards) >= len(bootloader_drives)

    try:
        wait_for(wait_for_rpi_rp2, timeout=60)
    except TimeoutError:
        msg = [
            "Please try running the program again.",
            "If this issue persists:",
            "    1. eject / safely remove all drives mounted in the process. They will all contain a file called 'INFO_UF2.TXT'",
            "    2. unplug all devices from the computer and wait for 10 seconds",
            "    3. plug the devices back in and run the program again",
            "    4. if the issue persists, please reachout for help",
        ]
        print("\n" + "\n".join(msg))
        graceful_exit()


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
        ports = Ray.find_board_ports()
        print(f"Found {len(ports)} devices to flash software to.")
        boards = [Ray(port) for port in ports]
        for i, board in enumerate(boards):
            print(f"Flashing software to {board.port} ({i+1} of {len(ports)})")
            # Copy files to the board
            update_files = get_files_from_update_file(software)
            board.write_update_to_board(update_files)

        # restart the boards
        for board in boards:
            board.restart_board()

        # wait for the boards to reboot
        def wait_for_reboot():
            restarted_boards = Ray.find_board_ports()
            print(f" ({len(restarted_boards)} of {len(ports)}) restarted", end="")
            return len(ports) <= len(restarted_boards)

        wait_for(wait_for_reboot, timeout=60)

    finally:
        # Clean up the temporary directory
        shutil.rmtree(extract_dir, ignore_errors=True)


def get_files_from_update_file(update_file):
    """Get the files from the update file"""
    files = []
    with open(update_file, "r") as f:
        f.readline()  # Skip the first line (metadata)
        for line in f.readlines():
            line = line.strip()
            if line == "":
                continue
            filename, metadata_and_contents = line.split("{", 1)
            metadata, contents = metadata_and_contents.split("}", 1)

            if filename == "":
                # This is probably the last line in the file, which is the signature
                continue

            # calculate the sha256 hash of the contents
            hasher = hashlib.sha256()
            hasher.update(contents.encode())
            sha256 = hasher.hexdigest()

            files.append(
                {
                    "filename": filename,
                    "metadata": json.loads("{" + metadata + "}"),
                    "base64_contents": contents.strip(),
                    "sha256": sha256,
                }
            )

    return files


# TODO validate all files were correctly copied using hashes
