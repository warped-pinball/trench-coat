import os
import sys
import tempfile
from datetime import datetime

import requests
from InquirerPy import inquirer

from src.core import list_bundled_uf2
from src.ray import PICO_PID, PICO_VID, find_boards


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
        print("Exiting...\n")
        sys.exit(0)
    elif menu_entry == "Custom":
        path = inquirer.text("Enter the full path to a custom UF2 file:").execute()
        print(f"You entered: {path}")
        if not os.path.isfile(path):
            print("Invalid file path. Exiting.")
            sys.exit(1)
        return path

    return uf2_file_paths[uf2_files.index(menu_entry)]


def select_devices():
    ports = find_boards(PICO_VID, PICO_PID)
    ports.append("Exit")

    if not ports:
        print("No Warped Pinball devices found. Please plug in via USB and try again. Do not press the 'BOOTSEL' button when plugging in.")
        sys.exit(0)

    selections = []
    while not selections:
        if len(ports) == 2:
            single_choice = inquirer.select(message="Confirm the device to flash:", choices=ports).execute()
            if single_choice == "Exit":
                sys.exit(0)
            selections = [single_choice]
        else:
            print("\nUse SPACE to select multiple devices, then press ENTER to confirm.")
            selections = inquirer.checkbox(message="Confirm the devices to flash:", choices=ports).execute()

        if not selections:
            print("No devices selected. Please select at least one device.")
        elif "Exit" in selections:
            sys.exit(0)

    # make sure we return a list of ports
    if isinstance(selections, str):
        selections = [selections]

    return selections


def select_software():
    # get list of all releases from github
    url = "https://api.github.com/repos/warped-pinball/vector/releases"
    response = requests.get(url)
    response.raise_for_status()
    releases = response.json()

    if not releases:
        print("No releases found in the repository.")
        sys.exit(1)

    # Filter releases with update.json file and no development tags
    filtered_releases = []
    for release in releases:
        tag = release["tag_name"].lstrip("v")
        has_update_json = any(asset["name"] == "update.json" for asset in release["assets"])

        if "-" not in tag and has_update_json:
            filtered_releases.append(release)

    if not filtered_releases:
        print("No suitable releases found (must have update.json file).")
        sys.exit(1)

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
        print("Exiting...\n")
        sys.exit(0)

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

    print(f"Downloaded update file for {selected_release['tag_name']}")
    return temp_file.name
