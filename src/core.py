import json
import os
import shutil
import string
import struct
import sys
import tempfile
import time

import pkg_resources

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
    nuke_path = [path for path in list_bundled_uf2() if "nuke.uf2" in path]
    if not nuke_path:
        print("Error: nuke.uf2 not found in bundled UF2 files.")
        graceful_exit()
    nuke_path = nuke_path[0]

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
    if len(bootloader_drives) == len(list_rpi_rp2_drives()):
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
        try:
            # Try to get the installed package path first
            uf2_dir = pkg_resources.resource_filename("src", "uf2")
            if not os.path.isdir(uf2_dir):
                # Fall back to development path
                uf2_dir = os.path.join(os.path.dirname(__file__), "uf2")
        except (ImportError, ModuleNotFoundError):
            # Fall back to development path
            uf2_dir = os.path.join(os.path.dirname(__file__), "uf2")

    if not os.path.isdir(uf2_dir):
        return []
    return [os.path.join(uf2_dir, f) for f in os.listdir(uf2_dir) if f.lower().endswith(".uf2")]


# UF2 family IDs, used to tell which processor a firmware image targets.
# https://github.com/raspberrypi/pico-sdk (boot/uf2 family ids)
_UF2_MAGIC_START0 = b"UF2\n"
_UF2_FLAG_FAMILY_ID_PRESENT = 0x00002000
_UF2_FAMILY_RP2040 = 0xE48BFF56
_UF2_FAMILY_ABSOLUTE = 0xE48BFF57  # absolute-addressed; accepted by both bootroms
_UF2_FAMILY_RP2350 = {
    0xE48BFF59,  # RP2350 ARM secure
    0xE48BFF5A,  # RP2350 RISC-V
    0xE48BFF5B,  # RP2350 ARM non-secure
}


def uf2_target_processor(uf2_path):
    """Inspect a UF2 image's family IDs to determine its target processor.

    Returns ``"rp2040"`` (Pico W), ``"rp2350"`` (Pico 2 W), ``"universal"`` (an
    image accepted by both bootroms, e.g. a universal flash-nuke), or ``None``
    if the image carries no recognizable family ID. This reads the UF2 block
    headers directly, so it does not rely on the filename.
    """
    families = set()
    try:
        with open(uf2_path, "rb") as f:
            while True:
                block = f.read(512)
                if len(block) < 512:
                    break
                if block[0:4] != _UF2_MAGIC_START0:
                    continue
                flags = struct.unpack("<I", block[8:12])[0]
                if flags & _UF2_FLAG_FAMILY_ID_PRESENT:
                    families.add(struct.unpack("<I", block[28:32])[0])
    except OSError:
        return None

    has_rp2040 = _UF2_FAMILY_RP2040 in families
    has_rp2350 = bool(families & _UF2_FAMILY_RP2350)
    has_absolute = _UF2_FAMILY_ABSOLUTE in families

    # RP2350-specific families are the definitive marker: real RP2350 images
    # also carry a stray absolute (metadata) block, so check these first.
    if has_rp2350:
        return "rp2350"
    # No RP2350-specific blocks, but accepted by both bootroms (e.g. a universal
    # flash-nuke is RP2040 + absolute) -> not specific to one processor.
    if has_absolute:
        return "universal"
    if has_rp2040:
        return "rp2040"
    return None


# Each firmware image runs one Vector "system", and each system has its own
# software update file published as a distinct asset in the same
# warped-pinball/vector GitHub release (e.g. update_wpc.json). We infer the
# system from keywords in the firmware filename so new version suffixes
# (Vector_WPC_v6.uf2, ...) keep working. Order matters: more specific first.
_FIRMWARE_SYSTEM_KEYWORDS = [
    ("wpc", "wpc"),
    ("dataeast", "data_east"),
    ("data_east", "data_east"),
    ("data-east", "data_east"),
    # System 9 / 11 ("Vector_system_11_and_9_v4.uf2") is the default below.
    # NOTE: only keywords for bundled, unambiguous firmware are listed here.
    # Avoid loose tokens like "em" -- it is a substring of "system" and would
    # mis-match the sys11 image. Add em/whitestar/classic with a safe keyword
    # (e.g. "_em") when their firmware images are actually bundled.
]

# Per-system software update asset name in the GitHub release.
SYSTEM_UPDATE_ASSET = {
    "sys11": "update.json",
    "wpc": "update_wpc.json",
    "data_east": "update_data_east.json",
    "em": "update_em.json",
    "whitestar": "update_whitestar.json",
    "classic": "update_classic.json",
}

# Human-friendly series name per system. These also match the labels used in
# the "## Versions" block of each release body (e.g. "**WPC**: `1.7.5`"), which
# is how we read the per-system version for display.
SYSTEM_LABEL = {
    "sys11": "Sys11",
    "wpc": "WPC",
    "data_east": "DataEast",
    "em": "EM",
    "whitestar": "WhiteStar",
    "classic": "Classic",
}
DEFAULT_SYSTEM = "sys11"
DEFAULT_UPDATE_ASSET = SYSTEM_UPDATE_ASSET[DEFAULT_SYSTEM]


def firmware_system(firmware_path):
    """Infer the Vector system id from a firmware filename.

    Returns one of the keys in ``SYSTEM_UPDATE_ASSET``. Defaults to
    ``"sys11"`` (the System 9 / 11 build) when no keyword matches or no path
    is given.
    """
    name = os.path.basename(firmware_path or "").lower()
    for keyword, system in _FIRMWARE_SYSTEM_KEYWORDS:
        if keyword in name:
            return system
    return DEFAULT_SYSTEM


# Firmware (OS) keyword used to find the bundled UF2 image for each system.
# Several systems can share one OS -- EM games run on the WPC OS -- so this maps
# the system to the OS it boots, matched by keyword in the UF2 filename. A
# system whose keyword matches no bundled UF2 is treated as "not available yet"
# (e.g. the Classic OS is still in development).
SYSTEM_FIRMWARE_KEYWORD = {
    "sys11": "system",  # Vector_system_11_and_9_v4.uf2
    "wpc": "wpc",  # Vector_WPC_v5.uf2
    "em": "wpc",  # EM uses the WPC OS
    "data_east": "dataeast",  # Vector_DataEast_v1.uf2
    "classic": "classic",  # OS not yet released; no bundled UF2 matches yet
}

# Order the game series are offered in the selection menu.
SERIES_MENU_ORDER = ["sys11", "wpc", "em", "data_east", "classic"]


def find_system_firmware(system, bundled_paths):
    """Return the bundled UF2 path that provides the OS for ``system``.

    Matches ``SYSTEM_FIRMWARE_KEYWORD[system]`` against each UF2 filename.
    Returns ``None`` if the system has no firmware keyword or no bundled image
    matches (i.e. its OS is not available yet)."""
    keyword = SYSTEM_FIRMWARE_KEYWORD.get(system)
    if not keyword:
        return None
    for path in bundled_paths:
        if keyword in os.path.basename(path).lower():
            return path
    return None


def system_for_boards(infos, default=DEFAULT_SYSTEM):
    """Pick the Vector system id from already-detected board identities.

    Used when no firmware is being flashed (``--skip-firmware``): the system is
    read from the board itself rather than inferred from a firmware filename.
    ``infos`` is a list of identity dicts from ``Ray.identify()``. A Pico W is
    always the legacy System 9 / 11 board; a Pico 2 W reports its system via
    ``systemConfig``. Returns ``default`` if nothing usable was detected.
    """
    for info in infos:
        if info.get("processor") == "rp2040":
            return DEFAULT_SYSTEM
        if info.get("system"):
            return info["system"]
    return default


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

            files.append({"filename": filename, "metadata": json.loads("{" + metadata + "}"), "base64_contents": contents.strip()})

    return files


# TODO validate all files were correctly copied using hashes
