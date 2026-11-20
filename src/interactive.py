import hashlib
import json
import os
import re
import tempfile
import time
from binascii import a2b_base64, unhexlify
from datetime import datetime

import requests
import rsa
from InquirerPy import inquirer
from InquirerPy.base.control import Choice

from src import ui
from src.core import (
    DEFAULT_SYSTEM,
    DEFAULT_UPDATE_ASSET,
    SERIES_MENU_ORDER,
    SYSTEM_LABEL,
    SYSTEM_UPDATE_ASSET,
    FirmwareSelection,
    custom_image_systems,
    firmware_system,
    list_bundled_uf2,
    processor_label,
)
from src.ray import Ray
from src.util import graceful_exit

# Matches a "**Label**: `version`" line in a release body's "## Versions" block.
_RELEASE_VERSION_RE = re.compile(r"\*\*([^*]+)\*\*:\s*`([^`]+)`")


def display_welcome():
    ui.title("Trenchcoat by Warped Pinball")
    print("Use this tool to flash firmware and software to your Warped Pinball devices.")
    ui.detail("If you have any trouble, open an issue on GitHub:", indent=0)
    ui.detail("https://github.com/warped-pinball/trench-coat/issues", indent=0)
    ui.detail("Press Ctrl+C to exit at any time.", indent=0)
    print()


def select_firmware_and_system():
    """Interactive game-series selector.

    Presents the supported game series (System 9 / 11, WPC, EM, Data East,
    Classic, ...). Each series maps to the OS firmware it boots -- several
    series can share one OS (EM runs on the WPC OS) -- plus its own software.
    Series whose OS is not bundled yet are shown as "(coming soon)" and cannot
    be selected.

    Returns ``(FirmwareSelection, system_id)``. A series can provide a
    different OS image per board type (System 9 / 11 runs one image on the
    Pico W and another on the Pico 2 W); the image is picked per batch once
    the connected board's chip is known.
    """
    bundled = [f for f in list_bundled_uf2() if "nuke.uf2" not in f]

    # Build a menu entry for each known series, resolving its OS firmware.
    entries = []  # list of (display_text, system_id, FirmwareSelection)
    for system in SERIES_MENU_ORDER:
        label = SYSTEM_LABEL.get(system, system)
        selection = FirmwareSelection.bundled(system, bundled)
        display = label if selection.available else f"{label} (coming soon)"
        entries.append((display, system, selection))

    choices = [e[0] for e in entries] + ["Custom firmware...", "Exit"]
    menu_entry = inquirer.select(message="Select the game series to flash:", choices=choices, default=0).execute()

    if menu_entry == "Exit":
        graceful_exit(now=True)
    if menu_entry == "Custom firmware...":
        path = inquirer.text("Enter the full path to a custom UF2 file:").execute()
        print(f"You entered: {path}")
        if not os.path.isfile(path):
            print("Invalid file path.")
            graceful_exit()
        selection = select_custom_firmware(path)
        return selection, selection.system

    display, system, selection = next(e for e in entries if e[0] == menu_entry)
    if not selection.available:
        # Series chosen whose OS is not released yet -- explain and re-prompt.
        label = SYSTEM_LABEL.get(system, system)
        print(f"{label} is not available yet - its OS is still in development. Please choose another series.")
        return select_firmware_and_system()

    describe_selection(selection)
    return selection, system


def select_custom_firmware(path, system=None):
    """Build the ``FirmwareSelection`` for a user-supplied UF2.

    The software series comes from ``system`` when the caller already knows
    it. Otherwise it is inferred from the filename, and when that filename
    names an OS shared by several series (the Data East image also runs
    System 9 / 11 on the Pico 2 W) the user is asked which one they mean.
    """
    if system is None:
        candidates = custom_image_systems(path)
        if len(candidates) > 1:
            system = inquirer.select(
                message="This OS is used by more than one game series. Which software should be installed with it?",
                choices=[Choice(value=s, name=SYSTEM_LABEL.get(s, s)) for s in candidates],
                default=firmware_system(path),
            ).execute()
    selection = FirmwareSelection.from_custom(path, system)
    describe_selection(selection)
    return selection


def confirm_risky_flash():
    """Ask before erasing boards a custom image cannot be shown to fit."""
    return bool(inquirer.confirm(message="Erase the board(s) and flash this firmware anyway?", default=False).execute())


def describe_selection(selection):
    """Print which OS image will be used for each board type."""
    label = SYSTEM_LABEL.get(selection.system, selection.system)
    if selection.custom:
        path = next(iter(selection.images.values()))
        targets = " / ".join(processor_label(p) for p in selection.images)
        ui.step(f"custom firmware: {os.path.basename(path)} (targets {targets})")
        ui.detail(f"software series: {label}")
        return
    ui.step(f"{label} OS - image used per board type:")
    for processor, path in selection.images.items():
        ui.detail(f"{processor_label(processor)}: {os.path.basename(path)}")


def _identify_with_retry(port, timeout: float = 45.0, delay: float = 0.5, on_wait=None):
    """Identify a board, retrying until ``timeout`` seconds have elapsed.

    Two things make the first attempts on a freshly plugged-in board fail:

    - A just-enumerated USB CDC port on Windows is often not ready for a read
      immediately, which surfaces as ClearCommError / PermissionError(13).
    - The COM port enumerates seconds before the Vector firmware finishes
      booting, and while boot code is still running the REPL does not answer
      the raw-REPL handshake. Boot can take tens of seconds, so a fixed small
      number of attempts always lands inside the boot window.

    We therefore retry on a wall-clock deadline rather than an attempt count,
    opening a fresh connection each attempt (a half-failed handshake can leave
    the port unusable) and backing off briefly between tries. ``on_wait`` is
    called once, after the first failed attempt, so callers can tell the user
    why detection is taking a moment. Returns the identity dict, or ``None``
    if the deadline passes without a response.
    """
    deadline = time.monotonic() + timeout
    waiting_reported = False
    while True:
        board = Ray(port)
        try:
            return board.identify()
        except Exception:
            if time.monotonic() >= deadline:
                return None
            if not waiting_reported and on_wait is not None:
                on_wait()
                waiting_reported = True
            time.sleep(delay)
        finally:
            board.close()


def report_and_guard_boards(selection):
    """Identify connected (running) boards, print what they are, and guard
    against flashing a batch the selected firmware can't handle.

    For each running board this prints the chip (Pico W / Pico 2 W), the raw
    ``os.uname().machine`` string, the Vector system its current firmware
    reports, and which OS image it will receive. Then:

      - a mixed batch (Pico W + Pico 2 W together) is rejected -- flash one
        board type at a time;
      - a bundled series with no OS image for a detected chip is rejected;
      - a custom image whose target chip doesn't match warns and asks; a yes
        is remembered for this batch so the bootloader check does not ask
        about the same mismatch twice.

    Returns ``(proceed, infos)`` where ``infos`` is the list of identity dicts
    for the boards that were successfully identified. Boards already in
    bootloader mode cannot be queried over the REPL and are skipped here; they
    are checked again from their bootloader drive before anything is wiped.
    """
    if selection is not None:
        selection.accepted_mismatches = set()

    ports = Ray.find_board_ports()
    if not ports:
        # Nothing running to identify (e.g. all boards already in bootloader).
        if selection is not None:
            ui.detail("No running boards to query - board type will be read from the bootloader drive before flashing.", indent=1)
        return True, []

    ui.heading("Detecting boards")
    mismatched = set()
    infos = []
    for port in ports:
        info = _identify_with_retry(port, on_wait=lambda port=port: ui.detail(f"{port}: waiting for the board to finish booting (this can take up to a minute)..."))
        if info is None:
            # Couldn't talk to the board even after waiting out a full boot.
            # Tell the user to replug (which reliably clears a wedged USB/REPL
            # state) rather than silently hanging or skipping.
            ui.error(f"{port}: no response from board.")
            ui.detail("Try unplugging and replugging this board, then press ENTER to retry detection")
            ui.detail("(or just press ENTER to skip detection and continue).")
            input()
            info = _identify_with_retry(port)
            if info is None:
                ui.warning(f"{port}: still no response - skipping detection for this board.")
                continue

        infos.append(info)
        processor = info.get("processor")
        ui.step(f"{port}: {processor_label(processor)}")
        ui.detail(f"chip reports: {info.get('machine') or '(no response)'}")
        if processor == "rp2350":
            ui.detail(f"current firmware system: {info.get('system') or 'unknown (blank or non-Vector firmware)'}")
        elif processor == "rp2040":
            ui.detail("current firmware system: legacy System 9 / 11 board")

        if selection is None:
            continue
        image = selection.image_for(processor) if processor else None
        if image:
            ui.detail(f"will flash: {os.path.basename(image)}")
        if processor and processor not in selection.images:
            if selection.custom:
                ui.warning(f"selected firmware does not target {processor_label(processor)}.", indent=2)
                mismatched.add(processor)
            else:
                label = SYSTEM_LABEL.get(selection.system, selection.system)
                ui.error(f"No {label} OS is bundled for {processor_label(processor)} boards.", indent=2)
                ui.detail(f"{label} supports: {', '.join(processor_label(p) for p in selection.images)}.", indent=3)
                return False, infos

    detected = {i.get("processor") for i in infos} - {None}
    if len(detected) > 1:
        ui.error("Mixed board types connected (" + " + ".join(processor_label(p) for p in sorted(detected)) + ").")
        ui.detail("Flash one board type at a time: unplug the other type and run again.", indent=2)
        return False, infos

    if mismatched:
        proceed = bool(inquirer.confirm(message="One or more boards do not match the selected firmware. Flash anyway?", default=False).execute())
        if proceed:
            selection.accepted_mismatches = mismatched
        return proceed, infos
    return True, infos


def prompt_next_action():
    """Ask the user what to do after a successful flash.

    Returns one of:
      - ``"again"``:       flash more boards with the same firmware/software
      - ``"reconfigure"``: pick a different game series / software, then flash
      - ``"quit"``:        exit the program
    """
    same = "Flash more boards with the same settings"
    change = "Change settings (game series / software), then flash"
    quit_ = "Quit"
    choice = inquirer.select(
        message="Flashing complete. What would you like to do next?",
        choices=[same, change, quit_],
        default=same,
    ).execute()
    if choice == change:
        return "reconfigure"
    if choice == quit_:
        return "quit"
    return "again"


def select_devices() -> list[Ray]:
    ports = Ray.find_board_ports()

    if not ports:
        print("No Warped Pinball devices found. Please plug in via USB and try again. Do not press the 'BOOTSEL' button when plugging in.")
        graceful_exit()

    ports.append("Exit")

    selected_ports = []
    while not selected_ports:
        if len(ports) < 2:
            single_choice = inquirer.select(message="Confirm the device to flash:", choices=ports).execute()
            selected_ports = [single_choice]
        else:
            print("\nUse SPACE to select multiple devices, then press ENTER to confirm.")
            selected_ports = inquirer.checkbox(message="Confirm the devices to flash:", choices=ports).execute()

        if not selected_ports:
            print("No devices selected. Please select at least one device.")
        elif "Exit" in selected_ports:
            graceful_exit(now=True)

    return selected_ports


def _parse_release_versions(body):
    """Parse the "## Versions" block of a release body into a {label: version}
    dict, e.g. {"Vector": "1.11.10", "WPC": "1.7.5", ...}. Returns {} if absent."""
    versions = {}
    for label, version in _RELEASE_VERSION_RE.findall(body or ""):
        versions[label.strip()] = version.strip()
    return versions


def select_software(system=DEFAULT_SYSTEM):
    # TODO allow for custom update.json files

    # Each Vector system publishes its own software update asset in the same
    # release (e.g. update_wpc.json), and the release body reports both the
    # overall Vector version and this system's own version.
    update_filename = SYSTEM_UPDATE_ASSET.get(system, DEFAULT_UPDATE_ASSET)
    series_label = SYSTEM_LABEL.get(system, system)
    print(f"Looking for {series_label} software updates ({update_filename})...")

    # get list of all releases from github
    url = "https://api.github.com/repos/warped-pinball/vector/releases"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        print("Connection timed out. Please check your internet connection.")
        graceful_exit()
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch releases from GitHub: {e}")
        graceful_exit()

    releases = response.json()

    if not releases:
        print("No releases found in the repository.")
        graceful_exit()

    # Filter releases that carry this system's update file and have no dev tags
    filtered_releases = []
    for release in releases:
        tag = release["tag_name"].lstrip("v")
        has_update_json = any(asset["name"] == update_filename for asset in release["assets"])

        if "-" not in tag and has_update_json:
            filtered_releases.append(release)

    if not filtered_releases:
        print(f"No suitable releases found (must have a '{update_filename}' file).")
        graceful_exit()

    # Sort releases by semantic version (latest first)
    def parse_version(tag_name):
        # Remove 'v' prefix if present
        tag_name = tag_name.lstrip("v")
        # Parse version components
        try:
            parts = [int(x) for x in tag_name.split(".")]
            # Pad with zeros for consistent comparison
            while len(parts) < 3:
                parts.append(0)
            return tuple(parts)
        except (ValueError, TypeError):
            # Return a minimal version for non-standard formats
            return (0, 0, 0)

    filtered_releases.sort(key=lambda r: parse_version(r["tag_name"]), reverse=True)

    # Format dates and prepare choices. Show both the series-specific version
    # and the overall Vector version, plus the series the build is from.
    choices = []
    release_map = {}  # Map formatted choice to original release

    for i, release in enumerate(filtered_releases):
        versions = _parse_release_versions(release.get("body"))
        vector_version = versions.get("Vector", release["tag_name"].lstrip("v"))
        system_version = versions.get(series_label)

        published_date = datetime.strptime(release["published_at"], "%Y-%m-%dT%H:%M:%SZ")
        formatted_date = published_date.strftime("%Y-%m-%d")

        if system_version:
            choice_text = f"{series_label} v{system_version}  (Vector {vector_version}, {formatted_date})"
        else:
            # Older release without a per-series version listed.
            choice_text = f"{series_label}  (Vector {vector_version}, {formatted_date})"
        if i == 0:
            choice_text += "  (Recommended)"
        choices.append(choice_text)
        release_map[choice_text] = release

    choices.append("Exit")

    selected_choice = inquirer.select(message="Select a software release:", choices=choices).execute()

    if selected_choice == "Exit":
        graceful_exit(now=True)

    # Get the selected release data
    selected_release = release_map[selected_choice]

    # Find the update asset for this system and its download URL
    try:
        update_json_asset = next(asset for asset in selected_release["assets"] if asset["name"] == update_filename)
        download_url = update_json_asset["browser_download_url"]
    except StopIteration:
        print(f"Error: No '{update_filename}' asset found in the selected release.")
        graceful_exit(now=True)
    # Download the update.json file to a temporary location
    temp_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    temp_file.close()

    # Download the file
    try:
        response = requests.get(download_url, timeout=60)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to download the update file: {e}")
        os.remove(temp_file.name)
        graceful_exit()

    with open(temp_file.name, "wb") as f:
        f.write(response.content)

    if validate_update_file(temp_file.name):
        print(f"Downloaded {update_filename} for {selected_release['tag_name']}")
        return temp_file.name
    else:
        print("Downloaded update file is invalid.")
        os.remove(temp_file.name)
        graceful_exit()


def read_last_significant_line(filepath):
    with open(filepath, "rb") as f:
        # Read lines in reverse order
        for line in reversed(f.readlines()):
            line = line.strip()
            if line:
                return line
    raise ValueError("No significant line found in the file.")


def validate_update_file(filepath) -> bool:
    # Step 1: Read the last line and calculate hash of content
    last_line_bytes = read_last_significant_line(filepath)

    # Calculate content length (file size minus last line and newline)
    with open(filepath, "rb") as f:
        f.seek(0, 2)  # Go to end
        file_size = f.tell()

    content_end = file_size - (len(last_line_bytes) + 1)  # -1 for newline

    # Step 2: Calculate hash of content (excluding signature line)
    with open(filepath, "r") as f:
        content = f.read(content_end).strip()  # Read file up to the signature line

    calculated_hash = hashlib.sha256(content.encode("utf-8")).digest()
    # Step 3: Parse signature metadata
    sig_data = json.loads(last_line_bytes.decode("utf-8"))
    expected_hash = unhexlify(sig_data.get("sha256", ""))
    signature = a2b_base64(sig_data.get("signature", ""))

    # Step 4: Verify hash integrity
    if calculated_hash != expected_hash:
        print("Hash mismatch! File may be corrupted.")
        print(f"Expected:   {expected_hash.hex()}")
        print(f"Calculated: {calculated_hash.hex()}")

        return False

    # Step 5: Verify signature
    try:
        public_key = rsa.PublicKey(
            n=25850530073502007505073398889935110756716032251132404339199218781380059422255360862345198138544675141546256513054332184373517438166092251410172963421556299077069195099284810366900994760048877561951388981897823462231871242380041390062269561386306787290618184745309059687916294069920586099425145107624115989895718851520436900326103985313232359151478484869518361685407610217568258949817227423076176730822354946128428713951948845035016003414197978601744938802692314180897355778380777214605494482082206918793349659727959426652897923672356221305760483911989683767700269466619761018439625757662776289786038860327614755771099,  # noqa
            e=65537,  # Common public exponent
        )
        rsa.verify(calculated_hash, signature, public_key)
    except Exception:
        return False

    # If we get here, validation passed
    return True
