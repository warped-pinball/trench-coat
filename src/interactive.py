import hashlib
import json
import os
import tempfile
from binascii import a2b_base64, unhexlify
from datetime import datetime

import requests
import rsa
from InquirerPy import inquirer

from src.core import list_bundled_uf2
from src.ray import Ray
from src.util import graceful_exit


def display_welcome():
    print("Trenchcoat by Warped Pinball")
    print("A simple tool to flash MicroPython firmware to Warped Pinball hardware.")


def select_uf2():
    """Interactive function to select a UF2 file"""
    uf2_file_paths = list_bundled_uf2()
    uf2_files = [os.path.basename(f) for f in uf2_file_paths]
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


def select_devices() -> list[Ray]:
    boards = Ray.find_boards()
    ports = [board.port for board in boards]
    ports.append("Exit")

    if not ports:
        print("No Warped Pinball devices found. Please plug in via USB and try again. Do not press the 'BOOTSEL' button when plugging in.")
        graceful_exit()

    selected_ports = []
    while not selected_ports:
        if len(boards) < 2:
            single_choice = inquirer.select(message="Confirm the device to flash:", choices=ports).execute()
            selected_ports = [single_choice]
        else:
            print("\nUse SPACE to select multiple devices, then press ENTER to confirm.")
            selected_ports = inquirer.checkbox(message="Confirm the devices to flash:", choices=ports).execute()

        if not selected_ports:
            print("No devices selected. Please select at least one device.")
        elif "Exit" in selected_ports:
            graceful_exit(now=True)

    return [board for board in boards if board.port in selected_ports]


def select_software():
    # TODO allow for custom update.json files

    # get list of all releases from github
    url = "https://api.github.com/repos/warped-pinball/vector/releases"
    response = requests.get(url)
    response.raise_for_status()
    releases = response.json()

    if not releases:
        print("No releases found in the repository.")
        graceful_exit()

    # Filter releases with update.json file and no development tags
    filtered_releases = []
    for release in releases:
        tag = release["tag_name"].lstrip("v")
        has_update_json = any(asset["name"] == "update.json" for asset in release["assets"])

        if "-" not in tag and has_update_json:
            filtered_releases.append(release)

    if not filtered_releases:
        print("No suitable releases found (must have update.json file).")
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

    for release in filtered_releases:
        name = release["name"] or release["tag_name"]
        published_date = datetime.strptime(release["published_at"], "%Y-%m-%dT%H:%M:%SZ")
        formatted_date = published_date.strftime("%Y-%m-%d")
        choice_text = f"{name} ({formatted_date})"
        choices.append(choice_text)
        release_map[choice_text] = release

    choices.append("Exit")

    selected_choice = inquirer.select(message="Select a software release:", choices=choices).execute()

    if selected_choice == "Exit":
        graceful_exit(now=True)

    # Get the selected release data
    selected_release = release_map[selected_choice]

    # Find the update.json asset and its download URL
    update_json_asset = next(asset for asset in selected_release["assets"] if asset["name"] == "update.json")
    download_url = update_json_asset["browser_download_url"]

    # Download the update.json file to a temporary location
    temp_file = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    temp_file.close()

    # Download the file
    response = requests.get(download_url)
    response.raise_for_status()

    with open(temp_file.name, "wb") as f:
        f.write(response.content)

    if validate_update_file(temp_file.name):
        print(f"Downloaded update file for {selected_release['tag_name']}")
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
