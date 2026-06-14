import hashlib
import json
import os
import tempfile
import time
from binascii import a2b_base64, unhexlify
from datetime import datetime

import requests
import rsa
from InquirerPy import inquirer

from src.core import list_bundled_uf2, uf2_target_processor
from src.ray import Ray
from src.util import graceful_exit


def display_welcome():
    print("Trenchcoat by Warped Pinball")
    print("Use this tool to flash firmware and software to your Warped Pinball devices.")
    print("If you have any trouble, open an issue on GitHub:")
    print("https://github.com/warped-pinball/trench-coat/issues")
    print("Press Ctrl+C to exit at any time.")
    print()


def select_uf2():
    """Interactive function to select a UF2 file"""
    uf2_file_paths = list_bundled_uf2()

    # remove nuke
    uf2_file_paths = [f for f in uf2_file_paths if "nuke.uf2" not in f]

    uf2_files = [os.path.basename(f) for f in uf2_file_paths]

    # sort the list of uf2 files
    uf2_files.sort()

    uf2_files.append("Custom")
    uf2_files.append("Exit")

    menu_entry = inquirer.select(message="Select a firmware file to flash:", choices=uf2_files, default=0).execute()

    if menu_entry == "Exit":
        graceful_exit(now=True)
    elif menu_entry == "Custom":
        path = inquirer.text("Enter the full path to a custom UF2 file:").execute()
        print(f"You entered: {path}")
        if not os.path.isfile(path):
            print("Invalid file path.")
            graceful_exit()
        return path

    return uf2_file_paths[uf2_files.index(menu_entry)]


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
                print(f"  {port}: still no response — skipping detection for this board.")
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
    ports.append("Exit")

    if not ports:
        print("No Warped Pinball devices found. Please plug in via USB and try again. Do not press the 'BOOTSEL' button when plugging in.")
        graceful_exit()

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


def select_software(update_filename="update.json"):
    # TODO allow for custom update.json files

    # Each Vector system publishes its own software update asset in the same
    # release (e.g. update_wpc.json); update_filename selects which one to pull.
    print(f"Looking for software updates ({update_filename})...")

    # get list of all releases from github
    url = "https://api.github.com/repos/warped-pinball/vector/releases"
    try:
        response = requests.get(url)
    except requests.exceptions.Timeout:
        print("Connection timed out. Please check your internet connection.")
        graceful_exit()

    response.raise_for_status()
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

    # Format dates and prepare choices
    choices = []
    release_map = {}  # Map formatted choice to original release

    for i, release in enumerate(filtered_releases):
        name = release["name"] or release["tag_name"]
        published_date = datetime.strptime(release["published_at"], "%Y-%m-%dT%H:%M:%SZ")
        formatted_date = published_date.strftime("%Y-%m-%d")
        if i == 0:
            name += " (Recommended)"
        choice_text = f"{name} ({formatted_date})"
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
    response = requests.get(download_url)
    response.raise_for_status()

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
