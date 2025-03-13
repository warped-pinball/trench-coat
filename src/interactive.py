import os
import sys

from InquirerPy import inquirer

from src.core import find_pico_ports_separated, flash_firmware, list_bundled_uf2


def interactive_mode():
    """Run the interactive UI to guide users through device selection and flashing"""
    display_welcome()

    # Step 1: Firmware selection
    firmware_path = select_uf2()

    # Step 2: Device detection and selection
    ports, bootloader_ports = find_pico_ports_separated()
    all_ports = [f"{p} - Normal Mode" for p in ports] + [f"{p} - Bootloader Mode" for p in bootloader_ports]
    all_ports.append("Exit")

    if not ports and not bootloader_ports:
        print("No Warped Pinball devices found. Please plug in via USB and try again.")
        sys.exit(0)

    selections = []
    while not selections:
        if len(all_ports) == 2:
            single_choice = inquirer.select(message="Confirm the device to flash:", choices=all_ports).execute()
            if single_choice == "Exit":
                sys.exit(0)
            selections = [single_choice]
        else:
            print("\nUse SPACE to select multiple devices, then press ENTER to confirm.")
            selections = inquirer.checkbox(message="Confirm the devices to flash:", choices=all_ports).execute()

        if not selections:
            print("No devices selected. Please select at least one device.")
        elif "Exit" in selections:
            sys.exit(0)

    normal_ports = [p.replace(" - Normal Mode", "") for p in selections if "Normal Mode" in p]
    bootloader_ports = [p.replace(" - Bootloader Mode", "") for p in selections if "Bootloader Mode" in p]

    # Step 3: Flash the firmware
    if flash_firmware(firmware_path, normal_ports, bootloader_ports):
        sys.exit(0)
    else:
        sys.exit(1)


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
