import os
import sys

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

    print(f"You selected: {menu_entry}")
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
    return selections
