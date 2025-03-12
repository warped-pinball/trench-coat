#!/usr/bin/env python3

import sys
import os
import time
import subprocess
import serial.tools.list_ports
import shutil
from InquirerPy import inquirer

# Known USB vendor/product ID for the Pico (RP2040 MicroPython)
PICO_VID = 0x2E8A
PICO_PID = 0x0005

#######################
# MAIN PROGRAM FLOW   #
#######################

def main():
    display_welcome()
    
    # Step 1: Firmware selection
    firmware_path = select_uf2()

    # Step 2: Device detection
    ports, bootloader_ports = find_pico_ports_separated()
    
    all_ports = [f"{p.device} ({p.manufacturer}) - Normal Mode" for p in ports] + \
                [f"{p} - Bootloader Mode" for p in bootloader_ports]
    
    if not all_ports:
        print("No Warped Pinball devices found. Please plug in via USB and try again.")
        sys.exit(0)
    
    print("\nUse SPACE to select multiple devices, then press ENTER to confirm.")
    selections = inquirer.checkbox(
        message="Confirm the device(s) to flash:",
        choices=all_ports
    ).execute()
    
    print(f"You selected: {selections}")
    if "Exit" in selections or not selections:
        print("Exiting...\n")
        sys.exit(0)
    
    normal_ports = [p.device for p in ports if f"{p.device} ({p.manufacturer}) - Normal Mode" in selections]
    bootloader_ports = [p.replace(" - Bootloader Mode", "") for p in bootloader_ports if p + " - Bootloader Mode" in selections]
    
    for port in normal_ports:
        if enter_bootloader(port):
            print(f"Successfully entered bootloader mode on {port}")
            bootloader_ports.append(port)
        else:
            print(f"Failed to enter bootloader mode on {port}")
            exit(1)
    
    for port in bootloader_ports:
        copy_uf2_to_bootloader(firmware_path)

    print("All done. Exiting.")
    sys.exit(0)

#######################
# USER INTERFACE      #
#######################

def display_welcome():
    print("Trenchcoat by Warped Pinball")
    print("A simple tool to flash MicroPython firmware to Warped Pinball hardware.")

def select_uf2():
    """Interactive function to select a UF2 file"""
    uf2_file_paths = list_bundled_uf2()
    uf2_files = [os.path.basename(f) for f in uf2_file_paths]
    uf2_files.append("Custom")
    uf2_files.append("Exit")
    
    menu_entry = inquirer.select(
        message="Select a firmware file to flash:",
        choices=uf2_files,
        default=0
    ).execute()
    
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

#######################
# OPERATIONAL LOGIC   #
#######################

def find_pico_ports_separated():
    """Find available Pico ports and separate normal from bootloader mode"""
    pico_ports = []
    bootloader_ports = list_rpi_rp2_drives()
    
    for port in serial.tools.list_ports.comports():
        if port.vid is not None and port.pid is not None:
            if (port.vid == PICO_VID) and (port.pid == PICO_PID):
                pico_ports.append(port)
    
    return pico_ports, bootloader_ports

def enter_bootloader(port):
    """Use mpremote to enter bootloader mode"""
    result = subprocess.run(
        ["mpremote", "connect", port, "bootloader"],
        capture_output=True, text=True
    )
    time.sleep(3)  # Allow enough time for the board to reconnect in bootloader mode
    return result.returncode == 0

def copy_uf2_to_bootloader(firmware_path):
    """Copy the UF2 file to the bootloader drive"""
    pico_drive = None
    
    drives = list_rpi_rp2_drives()
    
    if len(drives) == 0:
        print("No Warped Pinball devices found. Please plug in via USB and try again.")
        sys.exit(0)
    
    for i, drive in enumerate(drives):
        print(f"Flashing board {i+1} of {len(drives)}")
        shutil.copy(firmware_path, drive)

#######################
# UTILITY FUNCTIONS   #
#######################

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
    if os.name == 'nt':
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
    for drive_dir in ['/Volumes', '/media']:
        if not os.path.isdir(drive_dir):
            continue
        for root, dirs, files in os.walk(drive_dir):
            if "INFO_UF2.TXT" in files:
                found_drives.append(root)
    return found_drives

if __name__ == "__main__":
    main()
