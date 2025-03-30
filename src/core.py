import json
import os
import shutil
import sys
import time
from binascii import a2b_base64

import src.ray as ray

# Known USB vendor/product ID for the Pico (RP2040 MicroPython)
PICO_VID = 0x2E8A
PICO_PID = 0x0005
BAUD_RATE = 115200


#
# Firmware flashing functions
#
def flash_firmware(firmware_path, port):
    """Core function to flash firmware to devices"""
    # Enter bootloader mode for normal ports
    print(f"Putting {port} into bootloader mode...")
    ray.enter_bootloader_mode(port, BAUD_RATE)

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


#
# Software flashing functions
#

# def make_file_line(
#     file_path: str,
#     file_contents: bytes,
#     custom_log: Optional[str] = None,
#     execute: bool = False,
# ) -> str:
#     """
#     Create a single line representing one file’s update entry:
#         filename + jsonDictionary + base64EncodedFileContents

#     Example line:
#         some_file.py{"checksum":"ABCD","bytes":1234,"log":"Uploading file"}c29tZSB
#     """
#     checksum = crc16_ccitt(file_contents)
#     file_size = len(file_contents)
#     b64_data = base64.b64encode(file_contents).decode("utf-8")

#     file_meta = {
#         "checksum": checksum,
#         "bytes": file_size,
#         "log": custom_log if custom_log else f"Uploading {file_path}",
#     }
#     if execute:
#         file_meta["execute"] = True

#     meta_json = json.dumps(file_meta, separators=(",", ":"))
#     return f"{file_path}{meta_json}{b64_data}"


def flash_software(software, port):
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

    # Create a local directory for extracted files
    extract_dir = os.path.join(os.getcwd(), "extracted_software_files")
    os.makedirs(extract_dir, exist_ok=True)
    print(f"Extracting files to: {extract_dir}")

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
    ray.wipe_board(port, BAUD_RATE)

    # Create directories first
    print("Creating directories on the board...")
    unique_dirs = set()
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, extract_dir)
            directory = os.path.dirname(relative_path)
            if directory and directory not in unique_dirs:
                unique_dirs.add(directory)

    ray.send_command(
        port,
        BAUD_RATE,
        "\n\r".join(
            # fmt: off
            [
                "import os",
                "def try_mkdir(path):",
                "    try:",
                "        os.mkdir(path)",
                "    except OSError:",
                "        pass",
                ""
            ]
            + [
                f"try_mkdir('{directory}')" for directory in unique_dirs
            ]
            # fmt: on
        ),
    )

    # Copy files to the board
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, extract_dir)
            ray.copy_file_to_board(port, BAUD_RATE, local_path, relative_path)

    # restart the board
    print("Restarting the board...")
    ray.send_command(port, BAUD_RATE, "import machine; machine.reset()")


# TODO add instructions for when the board doesn't show up (go to boot loader mode and nuke)
# TODO JUST WRITE THE FILES TO THE BOARD IN BASE64 and HAVE THE BOARD DECODE THEM
