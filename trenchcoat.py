#!/usr/bin/env python3

import sys
import os
import time
import subprocess
import serial.tools.list_ports
from simple_term_menu import TerminalMenu
import shutil

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
    ports = pick_pico_ports()
            
    for port in ports:
        # Step 3: Enter bootloader mode
        if enter_bootloader(port):
            print(f"Successfully entered bootloader mode on {port}")
        else:
            print(f"Failed to enter bootloader mode on {port}")
            exit(1)
    
        # Step 4: Flash the firmware
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
    
    menu = TerminalMenu(uf2_files, title="Select a firmware file to flash:")
    menu_entry_index = menu.show()
    
    if uf2_files[menu_entry_index] == "Exit":
        sys.exit(0)
    elif uf2_files[menu_entry_index] == "Custom":
        print("Enter the full path to a custom UF2 file:")
        path = input().strip()
        if not os.path.isfile(path):
            print("Invalid file path. Exiting.")
            sys.exit(1)
        print(f"Selected firmware: {path}")
        return path
    
    print(f"Selected firmware: {uf2_files[menu_entry_index]}")
    return uf2_file_paths[menu_entry_index]
    

def pick_pico_ports():
    """Interactive function to select a Pico port"""
    ports = find_pico_ports()
    if not ports:
        print("No available Warped Pinball devices found. Checking if any are in bootloader mode...")
        
        print("No Warped Pinball devices found. Please plug in via USB and try again.")
        sys.exit(0)
    
    # ask the user to pick a port
    port_names = [f"{p.device} ({p.manufacturer})" for p in ports]
    port_names.append("Exit")
    menu = TerminalMenu(port_names, title="Confirm the device to flash:", multi_select=True)
    selections = menu.show()

    if "Exit" in menu.chosen_menu_entries or not selections:
        sys.exit(0)
    
    # return the selected port(s)
    return [ports[i].device for i in selections]

#######################
# OPERATIONAL LOGIC   #
#######################
def find_pico_ports():
    """Find available Pico ports (non-interactive)"""
    pico_ports = []
    for port in serial.tools.list_ports.comports():
        if port.vid is not None and port.pid is not None:
            if (port.vid == PICO_VID) and (port.pid == PICO_PID):
                pico_ports.append(port)
    return pico_ports

def enter_bootloader(port):
    """Use mpremote to enter bootloader mode"""
    result = subprocess.run(
        ["mpremote", "connect", port, "bootloader"],
        capture_output=True, text=True
    )
    return result.returncode == 0

def copy_uf2_to_bootloader(firmware_path):
    """Copy the UF2 file to the bootloader drive"""
    pico_drive = None

    # Try to auto-detect the RPI-RP2 drive
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
        # Running in PyInstaller one-file bundle
        return os.path.join(sys._MEIPASS, relative_path)
    else:
        # Running directly from source
        return os.path.join(os.path.dirname(__file__), relative_path)

def list_bundled_uf2():
    """List available bundled UF2 files"""
    uf2_dir = resource_path("uf2")
    if not os.path.isdir(uf2_dir):
        return []
    files = [f for f in os.listdir(uf2_dir) if f.lower().endswith(".uf2")]
    return [os.path.join(uf2_dir, f) for f in files]

def list_rpi_rp2_drives():
    """List all RPI-RP2 drives on Windows, Linux, or macOS"""
    if os.name == 'nt':
        time.sleep(2)  # wait for the drive(s) to appear
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
