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

from src.core import (
    DEFAULT_SYSTEM,
    DEFAULT_UPDATE_ASSET,
    SERIES_MENU_ORDER,
    SYSTEM_LABEL,
    SYSTEM_UPDATE_ASSET,
    find_system_firmware,
    firmware_system,
    list_bundled_uf2,
    uf2_target_processor,
)
from src.ray import Ray
from src.util import graceful_exit

# Matches a "**Label**: `version`" line in a release body's "## Versions" block.
_RELEASE_VERSION_RE = re.compile(r"\*\*([^*]+)\*\*:\s*`([^`]+)`")


def display_welcome():
    print("Trenchcoat by Warped Pinball")
    print("Use this tool to flash firmware and software to your Warped Pinball devices.")
    print("If you have any trouble, open an issue on GitHub:")
    print("https://github.com/warped-pinball/trench-coat/issues")
    print("Press Ctrl+C to exit at any time.")
    print()


def select_firmware_and_system():
    """Interactive game-series selector.

    Presents the supported game series (System 9 / 11, WPC, EM, Data East,
    Classic, ...). Each series maps to the OS firmware it boots -- several
    series can share one OS (EM runs on the WPC OS) -- plus its own software.
    Series whose OS is not bundled yet are shown as "(coming soon)" and cannot
    be selected.

    Returns ``(firmware_path, system_id)``.
    """
    bundled = [f for f in list_bundled_uf2() if "nuke.uf2" not in f]

    # Build a menu entry for each known series, resolving its OS firmware.
    entries = []  # list of (display_text, system_id, firmware_path_or_None)
    for system in SERIES_MENU_ORDER:
        label = SYSTEM_LABEL.get(system, system)
        firmware = find_system_firmware(system, bundled)
        display = label if firmware else f"{label} (coming soon)"
        entries.append((display, system, firmware))

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
        return path, firmware_system(path)

    display, system, firmware = next(e for e in entries if e[0] == menu_entry)
    if firmware is None:
        # Series chosen whose OS is not released yet -- explain and re-prompt.
        label = SYSTEM_LABEL.get(system, system)
        print(f"{label} is not available yet - its OS is still in development. Please choose another series.")
        return select_firmware_and_system()

    return firmware, system


def _identify_with_retry(port, attempts: int = 3, delay: float = 0.5):
    """Identify a board, retrying on transient serial errors.

    A freshly enumerated USB CDC port on Windows is often not ready for a read
    immediately, which surfaces as ClearCommError / PermissionError(13). We open
    a fresh connection each attempt (a half-failed handshake can leave the port
    unusable) and back off briefly between tries. Returns the identity dict, or
    ``None`` if every attempt fails.
    """
    for attempt in range(attempts):
        board = Ray(port)
        try:
            return board.identify()
        except Exception:
            if attempt + 1 < attempts:
                time.sleep(delay)
        finally:
            board.close()
    return None


def report_and_guard_boards(firmware):
    """Identify connected (running) boards, print what they are, and guard
    against a processor mismatch with the selected firmware.

    For each running board this prints whether it is a Pico W (legacy
    System 9 / 11) or a Pico 2 W (and, for the Pico 2 W, which Vector system
    its current firmware reports). If a firmware image was selected and its
    target processor does not match a detected board, the user is warned and
    asked whether to continue.

    Returns ``(proceed, infos)`` where ``proceed`` is ``True`` to continue
    flashing (``False`` to abort) and ``infos`` is the list of identity dicts
    for the boards that were successfully identified. Boards already in
    bootloader mode cannot be queried over the REPL and are skipped.
    """
    firmware_processor = uf2_target_processor(firmware) if firmware else None

    ports = Ray.find_board_ports()
    if not ports:
        # Nothing running to identify (e.g. all boards already in bootloader).
        return True, []

    print("Detected boards:")
    mismatch = False
    infos = []
    for port in ports:
        info = _identify_with_retry(port)
        if info is None:
            # Couldn't talk to the board within the timeout/retries. Tell the
            # user to replug (which reliably clears a wedged USB/REPL state)
            # rather than silently hanging or skipping.
            print(f"  {port}: no response from board.")
            print("     Try unplugging and replugging this board, then press ENTER to retry detection")
            print("     (or just press ENTER to skip detection and continue).")
            input()
            info = _identify_with_retry(port)
            if info is None:
                print(f"  {port}: still no response - skipping detection for this board.")
                continue

        infos.append(info)
        board_name = info["board"] or "Unknown board"
        if info["processor"] == "rp2350":
            system = info["system"] or "unknown system"
            print(f"  {port}: {board_name} (system: {system})")
        elif info["processor"] == "rp2040":
            print(f"  {port}: {board_name} (legacy System 9 / 11)")
        else:
            print(f"  {port}: {board_name}")

        if firmware_processor in ("rp2040", "rp2350") and info["processor"] and firmware_processor != info["processor"]:
            print(f"     WARNING: selected firmware targets {firmware_processor.upper()} but this board is {info['processor'].upper()}.")
            mismatch = True

    if mismatch:
        proceed = bool(inquirer.confirm(message="One or more boards do not match the selected firmware. Flash anyway?", default=False).execute())
        return proceed, infos
    return True, infos


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
