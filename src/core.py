import json
import os
import shutil
import string
import struct
import sys
import tempfile
import time

from src import ui
from src.ray import Ray
from src.util import graceful_exit, wait_for


#
# Firmware flashing functions
#
def get_all_boards_into_bootloader():
    # get all bootloader drives
    bootloader_drives = list_rpi_rp2_drives()
    initial_drives = len(bootloader_drives)
    ui.step(f"{len(bootloader_drives)} device(s) already in bootloader mode")

    # Find all connected devices
    ports = Ray.find_board_ports()
    initial_ports = len(ports)
    ui.step(f"{len(ports)} device(s) running, need a reset into bootloader mode")
    for port in ports:
        # Put the board in bootloader mode
        ui.detail(f"resetting {port} into bootloader mode...")
        Ray(port).enter_bootloader_mode()

    expected_drive_count = initial_drives + initial_ports

    # Wait for bootloader drives to appear
    def wait_for_bootloader():
        drives = list_rpi_rp2_drives()
        print(ui.status(f"waiting for ({len(drives)} of {expected_drive_count}) device(s) to appear in bootloader mode"), end="")
        return len(drives) >= expected_drive_count

    wait_for(wait_for_bootloader, timeout=60)


def _abort_before_wipe(message, hints=()):
    """Stop flashing before anything has been erased."""
    ui.error(message)
    for hint in hints:
        ui.detail(hint, indent=2)
    ui.detail("Nothing was erased. The board(s) are sitting in bootloader mode; unplug them before continuing.", indent=2)
    graceful_exit()


def choose_batch_firmware(selection, drive_infos):
    """Validate a batch of bootloader drives and pick the one image to flash.

    ``drive_infos`` maps drive path -> ``read_drive_info()`` result. A batch
    must be a single board type (mixed Pico W + Pico 2 W batches are
    rejected). Returns ``(firmware_path, processor)``; raises
    ``FirmwarePlanError`` with a user-facing message if the batch can't be
    flashed with ``selection``.
    """
    if not drive_infos:
        raise FirmwarePlanError("No boards found in bootloader mode.", ["Unplug and replug the board(s), then run the program again."])
    processors = {info["processor"] for info in drive_infos.values()}
    unknown = [drive for drive, info in drive_infos.items() if info["processor"] is None]
    known = processors - {None}

    if len(known) > 1:
        counts = ", ".join(f"{sum(1 for i in drive_infos.values() if i['processor'] == p)} x {processor_label(p)}" for p in sorted(known))
        raise FirmwarePlanError(
            f"Mixed board types connected ({counts}).",
            ["Flash one board type at a time: unplug the other type and run again."],
        )

    # A bundled series needs the chip to pick its image. A custom image may be
    # flashed onto a batch nobody could identify (after an explicit
    # confirmation), but never onto a part-identified batch: the re-check after
    # the wipe would refuse the unreadable drive once every board is erased.
    if unknown and (known or not selection.custom):
        raise FirmwarePlanError(
            f"Could not tell which Pico is in bootloader drive(s) {', '.join(unknown)}.",
            [
                "The drive's INFO_UF2.TXT did not report a known Board-ID (expected RPI-RP2 or RP2350).",
                "Unplug and replug the board(s), then run the program again.",
            ],
        )

    processor = next(iter(known), None)
    firmware_path = selection.image_for(processor)
    if firmware_path is None:
        available = ", ".join(processor_label(p) for p in selection.images) or "no boards"
        raise FirmwarePlanError(
            f"No {SYSTEM_LABEL.get(selection.system, selection.system)} OS is bundled for {processor_label(processor)} boards.",
            [f"This series currently supports: {available}."],
        )
    return firmware_path, processor


def custom_flash_concerns(selection, firmware_path, batch_processor):
    """Reasons a custom image might not suit the batch it is about to replace.

    Returns a list of user-facing sentences, empty when the image is known to
    fit the connected board(s). Bundled series never have concerns: their
    image is picked from the detected chip."""
    if not selection.custom:
        return []
    name = os.path.basename(firmware_path)
    target = uf2_target_processor(firmware_path)
    concerns = []
    if batch_processor is None:
        concerns.append("Could not tell which Pico is connected, so this firmware cannot be checked against it.")
    if target is None:
        concerns.append(f"{name} does not say which chip it is built for (no recognizable UF2 family ID).")
    elif target in PROCESSOR_LABEL and batch_processor is not None and target != batch_processor:
        concerns.append(f"{name} is built for {processor_label(target)}, but the connected board is {processor_label(batch_processor)}.")
    return concerns


def _mismatch_already_accepted(selection, firmware_path, batch_processor):
    """True when the only concern is a chip mismatch the user already accepted
    for this batch while the boards were still running."""
    if batch_processor is None or uf2_target_processor(firmware_path) is None:
        return False
    return batch_processor in selection.accepted_mismatches


def read_drive_processor(drive, timeout=15.0, delay=0.5):
    """Read a bootloader drive's chip, retrying while it cannot be identified.

    A drive that has only just re-mounted (after a wipe) can briefly fail to
    serve INFO_UF2.TXT, so one failed read is not proof of a different board.
    Returns the processor, or ``None`` if it is still unknown at ``timeout``."""
    deadline = time.monotonic() + timeout
    while True:
        processor = read_drive_info(drive)["processor"]
        if processor is not None or time.monotonic() >= deadline:
            return processor
        time.sleep(delay)


def _report_drives(drives):
    """Read and print the chip/bootloader diagnostics for each drive."""
    infos = {}
    for drive in drives:
        info = read_drive_info(drive)
        infos[drive] = info
        ui.step(f"{drive} -> {processor_label(info['processor'])}")
        ui.detail(f"Board-ID: {info['board_id'] or '(not found)'} | Model: {info['model'] or '(not found)'} | {info['bootloader'] or 'bootloader version unknown'}")
    return infos


def flash_firmware(selection, confirm=None):
    """Core function to flash firmware to devices.

    ``selection`` is a ``FirmwareSelection``; the actual UF2 image is chosen
    per batch from the chip each bootloader drive reports, *before* any
    board is wiped.

    ``confirm`` is called with no arguments and returns ``True`` to go ahead
    when a custom image cannot be shown to fit the connected board(s). Without
    it, such a batch is refused rather than erased.
    """
    ui.heading("Flashing firmware")
    get_all_boards_into_bootloader()

    # Get the updated list of bootloader drives
    bootloader_drives = list_rpi_rp2_drives()

    # Work out which Pico(s) we're talking to and pick the matching OS image.
    ui.step("Detecting board type from bootloader drive(s)")
    drive_infos = _report_drives(bootloader_drives)
    try:
        firmware_path, batch_processor = choose_batch_firmware(selection, drive_infos)
    except FirmwarePlanError as e:
        _abort_before_wipe(e.message, e.hints)

    target = uf2_target_processor(firmware_path)
    ui.success(f"Selected OS image for {processor_label(batch_processor)}: {os.path.basename(firmware_path)}")
    ui.detail(f"image targets: {processor_label(target) if target in PROCESSOR_LABEL else (target or 'unknown')}")
    concerns = custom_flash_concerns(selection, firmware_path, batch_processor)
    for concern in concerns:
        ui.warning(concern)
    if concerns:
        if _mismatch_already_accepted(selection, firmware_path, batch_processor):
            ui.detail("flashing anyway, as confirmed above.", indent=2)
        elif confirm is None or not confirm():
            _abort_before_wipe("Flashing cancelled.")

    # wipe the board with nuke.uf2
    nuke_path = [path for path in list_bundled_uf2() if "nuke.uf2" in path]
    if not nuke_path:
        ui.error("nuke.uf2 not found in bundled UF2 files.")
        graceful_exit()
    nuke_path = nuke_path[0]

    # give the drives a moment to settle
    time.sleep(5)

    for drive in bootloader_drives:
        ui.step(f"wiping {drive} with {os.path.basename(nuke_path)}")
        shutil.copy(nuke_path, drive)
        try:
            os.sync()
        except Exception:
            # only available on some platforms
            pass

    # Wait for the drives to start executing uf2s
    def wait_for_flash():
        drives = list_rpi_rp2_drives()
        print(ui.status(f"waiting for ({len(bootloader_drives) - len(drives)} of {len(bootloader_drives)}) device(s) to begin flashing"), end="")
        return len(drives) < len(bootloader_drives)

    wait_for(wait_for_flash, timeout=60)

    # Wait for the drives to reappear after nuking
    def wait_for_reappear():
        drives = list_rpi_rp2_drives()
        print(ui.status(f"waiting for ({len(drives)} of {len(bootloader_drives)}) device(s) to re-enter bootloader mode"), end="")
        return len(drives) >= len(bootloader_drives)

    wait_for(wait_for_reappear, timeout=60)

    # Get the final list of bootloader drives once they're all accounted for
    # (They could have changed paths)
    if len(bootloader_drives) == len(list_rpi_rp2_drives()):
        bootloader_drives = list_rpi_rp2_drives()

    # give the drives a moment to settle
    time.sleep(5)

    # Drive letters can change after a wipe, so re-check each drive's chip
    # right before copying rather than trusting the earlier mapping. The
    # boards are already erased here, so a drive that is merely slow to
    # answer is retried before it counts as a different board.
    if batch_processor is not None:
        for drive in bootloader_drives:
            processor = read_drive_processor(drive)
            if processor != batch_processor:
                if processor is None:
                    ui.error(f"{drive} could not be identified after the wipe (expected {processor_label(batch_processor)}).")
                else:
                    ui.error(f"{drive} now reports {processor_label(processor)}, expected {processor_label(batch_processor)}.")
                ui.detail("The board(s) have been erased and have no OS yet. Unplug all boards and run the program again to finish.", indent=2)
                graceful_exit()

    for drive in bootloader_drives:
        ui.step(f"flashing {os.path.basename(firmware_path)} to {drive}")
        shutil.copy(firmware_path, drive)
        try:
            os.sync()
        except Exception:
            # only available on some platforms
            pass

    # Wait for the drives to reappear as Ray devices
    def wait_for_rpi_rp2():
        boards = Ray.find_board_ports()
        print(ui.status(f"waiting for ({len(boards)} of {len(bootloader_drives)}) board(s) to restart"), end="")
        return len(boards) >= len(bootloader_drives)

    try:
        wait_for(wait_for_rpi_rp2, timeout=60)
    except TimeoutError:
        ui.error("Boards did not restart after firmware flashing.")
        ui.detail("Please try running the program again.", indent=1)
        ui.detail("If this issue persists:", indent=1)
        ui.detail("1. eject / safely remove all drives mounted in the process. They will all contain a file called 'INFO_UF2.TXT'", indent=2)
        ui.detail("2. unplug all devices from the computer and wait for 10 seconds", indent=2)
        ui.detail("3. plug the devices back in and run the program again", indent=2)
        ui.detail("4. if the issue persists, please reach out for help", indent=2)
        graceful_exit()
    else:
        ui.success("Firmware flashed.")


def list_bundled_uf2():
    """List available bundled UF2 files"""

    candidates = []
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller bundle (--add-data "uf2:uf2")
        candidates.append(os.path.join(sys._MEIPASS, "uf2"))
    else:
        # Installed package data (if present)
        candidates.append(os.path.join(os.path.dirname(__file__), "uf2"))
        # Development checkout: uf2/ lives at the repository root
        candidates.append(os.path.join(os.path.dirname(os.path.dirname(__file__)), "uf2"))

    for uf2_dir in candidates:
        if os.path.isdir(uf2_dir):
            return [os.path.join(uf2_dir, f) for f in os.listdir(uf2_dir) if f.lower().endswith(".uf2")]
    return []


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
    ("classic", "classic"),
    # System 9 / 11 ("Vector_system_11_and_9_v4.uf2") is the default below.
    # NOTE: only keywords for bundled, unambiguous firmware are listed here.
    # Avoid loose tokens like "em" -- it is a substring of "system" and would
    # mis-match the sys11 image. Add em/whitestar with a safe keyword
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


# Firmware (OS) keyword used to find the bundled UF2 image for each system, per
# board processor. Several systems can share one OS -- EM games run on the WPC
# OS, and the Pico 2 W System 9 / 11 board runs the Data East OS (with the
# normal System 11 software) -- so this maps (system, processor) to the OS it
# boots, matched by keyword in the UF2 filename. A system with no matching
# bundled UF2 is treated as "not available yet" (e.g. WhiteStar).
SYSTEM_FIRMWARE_KEYWORDS = {
    "sys11": {
        "rp2040": "system",  # vector_system_11_and_9_v4.uf2 (original Pico W board)
        "rp2350": "dataeast",  # Vector_DataEast_v1.uf2 (Pico 2 W board: Sys9/11 + Data East)
    },
    "wpc": {"rp2350": "wpc"},  # Vector_WPC_v5.uf2
    "em": {"rp2350": "wpc"},  # EM uses the WPC OS
    "data_east": {"rp2350": "dataeast"},  # Vector_DataEast_v1.uf2
    "classic": {"rp2350": "classic"},  # Vector_Classics_V1.uf2
}

# Order the game series are offered in the selection menu.
SERIES_MENU_ORDER = ["sys11", "wpc", "em", "data_east", "classic"]

# Human-friendly board names per processor.
PROCESSOR_LABEL = {
    "rp2040": "Pico W (RP2040)",
    "rp2350": "Pico 2 W (RP2350)",
}


def processor_label(processor):
    return PROCESSOR_LABEL.get(processor, "unknown board")


def custom_image_systems(firmware_path):
    """Game series that boot the OS a custom image's filename names.

    One OS can serve several series (the Data East image also runs System 9 /
    11 on the Pico 2 W, and the WPC image also runs EM), so the filename
    alone does not always say which software belongs with it. Returns the
    candidate system ids in menu order; more than one means the caller has to
    ask."""
    name = os.path.basename(firmware_path or "").lower()
    return [system for system in SERIES_MENU_ORDER if any(keyword in name for keyword in SYSTEM_FIRMWARE_KEYWORDS.get(system, {}).values())]


def find_system_images(system, bundled_paths):
    """Return ``{processor: uf2_path}`` for the bundled OS images of ``system``.

    For each processor the system supports, picks the first (sorted) bundled
    UF2 whose filename contains that processor's keyword. A candidate whose
    UF2 headers explicitly target the *other* processor is skipped, so a
    filename collision can never put an RP2040 image on an RP2350 or vice
    versa. Returns ``{}`` if nothing is bundled (OS not available yet)."""
    images = {}
    for processor, keyword in SYSTEM_FIRMWARE_KEYWORDS.get(system, {}).items():
        for path in sorted(bundled_paths, key=lambda p: os.path.basename(p).lower()):
            if keyword not in os.path.basename(path).lower():
                continue
            target = uf2_target_processor(path)
            if target in PROCESSOR_LABEL and target != processor:
                continue
            images[processor] = path
            break
    return images


class FirmwarePlanError(Exception):
    def __init__(self, message, hints=()):
        super().__init__(message)
        self.message = message
        self.hints = list(hints)


class FirmwareSelection:
    """The OS the user asked for, resolved to a UF2 per board processor.

    ``images`` maps processor -> UF2 path. Bundled series pick the image that
    matches the connected board's chip. A ``custom`` selection is a single
    user-supplied file that is flashed as-is (the user is warned about a
    processor mismatch, but may override it)."""

    def __init__(self, system, images, custom=False):
        self.system = system
        self.images = dict(images)
        self.custom = custom
        # Board chips the user agreed to flash a mismatched custom image onto,
        # for the batch currently connected (reset for every batch).
        self.accepted_mismatches = set()

    @classmethod
    def bundled(cls, system, bundled_paths):
        return cls(system, find_system_images(system, bundled_paths))

    @classmethod
    def from_custom(cls, path, system=None):
        """``system`` names the software series; without it the series is
        inferred from the filename."""
        target = uf2_target_processor(path)
        if target in PROCESSOR_LABEL:
            images = {target: path}
        else:  # universal / unknown image: usable on either chip
            images = {p: path for p in PROCESSOR_LABEL}
        return cls(system or firmware_system(path), images, custom=True)

    @property
    def available(self):
        return bool(self.images)

    def image_for(self, processor):
        if processor in self.images:
            return self.images[processor]
        if self.custom and self.images:
            return next(iter(self.images.values()))
        return None


def read_drive_info(drive):
    """Read a UF2 bootloader drive's INFO_UF2.TXT to identify the chip.

    Works for any board in bootloader mode -- blank, wiped, or running
    non-Vector firmware. Returns a dict with ``processor`` (``"rp2040"`` /
    ``"rp2350"`` / ``None``) plus the raw ``board_id``, ``model`` and
    ``bootloader`` lines for diagnostics."""
    info = {"processor": None, "board_id": None, "model": None, "bootloader": None}
    try:
        with open(os.path.join(drive, "INFO_UF2.TXT"), "r", errors="replace") as f:
            text = f.read()
    except OSError:
        return info

    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("board-id:"):
            info["board_id"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("model:"):
            info["model"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("uf2 bootloader"):
            info["bootloader"] = line

    ident = f"{info['board_id'] or ''} {info['model'] or ''}".upper()
    if "RP2350" in ident:
        info["processor"] = "rp2350"
    elif "RPI-RP2" in ident or "RP2040" in ident or ident.strip().endswith("RP2"):
        info["processor"] = "rp2040"
    return info


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
    ui.heading("Flashing software")

    # confirm known update format
    with open(software, "r") as f:
        software_metadata = json.loads(f.readline())
        if "update_file_format" not in software_metadata:
            ui.error("file format not specified in update.json.")
            sys.exit(1)
        if software_metadata["update_file_format"] != "1.0":
            ui.error("update.json file format not recognized. Check for more recent versions of this program.")
            sys.exit(1)
    ui.step("software file format confirmed")

    # Create a temporary directory for extracted files
    extract_dir = tempfile.mkdtemp(prefix="software_update_")
    ui.detail(f"extracting files to temporary directory: {extract_dir}")

    try:
        ports = Ray.find_board_ports()
        ui.step(f"found {len(ports)} device(s) to flash software to")
        boards = [Ray(port) for port in ports]
        update_files = get_files_from_update_file(software)
        for i, board in enumerate(boards):
            ui.step(f"flashing {board.port} ({i + 1} of {len(ports)})")
            # A board that was just firmware-flashed re-enumerates its serial
            # port seconds before its application finishes booting. Wait for the
            # REPL to actually respond before uploading, otherwise the first
            # command (the SHA256 index) fires into a still-booting board and
            # hangs with no output.
            if not board.wait_until_ready(on_wait=lambda b=board: ui.detail(f"{b.port}: waiting for the board to finish booting (this can take up to a minute)...")):
                ui.error(f"{board.port}: board never became ready for software flashing.", indent=2)
                ui.detail("Try unplugging and replugging this board, then run the program again.", indent=3)
                graceful_exit()
            # Copy files to the board
            board.write_update_to_board(update_files)
            ui.success(f"{board.port}: software flashed.", indent=2)

        # restart the boards
        for board in boards:
            board.restart_board()

        # wait for the boards to reboot
        def wait_for_reboot():
            restarted_boards = Ray.find_board_ports()
            print(ui.status(f"waiting for ({len(restarted_boards)} of {len(ports)}) board(s) to restart"), end="")
            return len(ports) <= len(restarted_boards)

        wait_for(wait_for_reboot, timeout=60)
        ui.success("Software flashing complete.")

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
