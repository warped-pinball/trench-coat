#!/usr/bin/env python3

import sys
import os
import time
import subprocess
import serial.tools.list_ports

# Known USB vendor/product ID for the Pico (RP2040 MicroPython)
PICO_VID = 0x2E8A
PICO_PID = 0x0005

#######################
# MAIN PROGRAM FLOW   #
#######################

def main():
    display_welcome()
    
    # Step 1: Device detection
    port = detect_pico_device()
    
    # Step 2: Firmware selection
    firmware_path = select_firmware()
    
    # Step 3: Confirmation
    if not confirm_flashing(firmware_path):
        exit_program("Aborted.")
        
    # Step 4: Prepare device for flashing
    prepare_device_for_flashing(port)
    
    # Step 5: Flash the firmware
    if flash_firmware(firmware_path):
        display_success_message()
    else:
        display_error_message()

#######################
# USER INTERFACE      #
#######################

def display_welcome():
    """Display welcome message"""
    print("=== Raspberry Pi Pico W MicroPython Flasher ===")
    print("This tool helps you flash a MicroPython .uf2 file onto a Pico W.\n")

def detect_pico_device():
    """Handle the device detection process with user interaction"""
    return pick_pico_port()

def select_firmware():
    """Handle the firmware selection process with user interaction"""
    print("\nWould you like to use one of the bundled UF2 files?")
    use_bundled = input("Enter 'y' to select from bundled, or 'n' for custom path [y/n]: ").strip().lower()

    if use_bundled == 'y':
        firmware_path = pick_bundled_uf2()
        if firmware_path:
            print(f"Selected bundled firmware: {os.path.basename(firmware_path)}")
            return firmware_path

    return select_custom_firmware()

def select_custom_firmware():
    """Prompt user for a custom firmware path"""
    print("Enter path to the MicroPython .uf2 firmware file.")
    custom_path = input("(default: ./micropython.uf2): ").strip()
    if not custom_path:
        custom_path = "./micropython.uf2"
    if not os.path.isfile(custom_path):
        print(f"Firmware file '{custom_path}' does not exist. Exiting.")
        sys.exit(1)
    return custom_path

def confirm_flashing(firmware_path):
    """Get user confirmation before proceeding with flashing"""
    print(f"\nReady to flash '{firmware_path}' onto the Pico W.")
    confirm = input("Proceed? (y/n): ").lower().strip()
    return confirm == 'y'

def display_success_message():
    """Display success message after flashing"""
    print("Firmware flashing process complete.")
    print("If everything went well, the Pico W will reboot into MicroPython now.")

def display_error_message():
    """Display error message if flashing fails"""
    print("Firmware flashing encountered errors. Please retry or flash manually.")

def exit_program(message):
    """Exit the program with a message"""
    print(message)
    sys.exit(0)

def pick_pico_port():
    """Interactive function to select a Pico port"""
    ports = find_pico_ports()
    if not ports:
        print("No Pico W running MicroPython found.")
        print("If the board is in BOOTSEL mode (mass storage), we can skip direct detection.")
        print("Press Enter to continue or Ctrl+C to abort.")
        input()
        return None
    elif len(ports) == 1:
        print(f"Detected one Pico W on port: {ports[0].device}")
        return ports[0].device
    else:
        print("Multiple Pico or RP2040 devices found:")
        for i, p in enumerate(ports, start=1):
            print(f"{i}. {p.device} - {p.description}")
        choice_str = input(f"Select a device [1-{len(ports)}]: ").strip()
        try:
            choice = int(choice_str)
            if 1 <= choice <= len(ports):
                return ports[choice - 1].device
        except ValueError:
            pass
        print("Invalid selection. Defaulting to first device.")
        return ports[0].device

def pick_bundled_uf2():
    """Interactive function to select a bundled UF2 file"""
    uf2_files = list_bundled_uf2()
    if not uf2_files:
        print("No bundled .uf2 files found in the embedded 'uf2' folder.")
        return None

    print("\nAvailable bundled .uf2 files:")
    for i, file_path in enumerate(uf2_files, start=1):
        filename = os.path.basename(file_path)
        print(f"  {i}. {filename}")

    choice = input(f"Select a file [1-{len(uf2_files)} or blank to skip]: ").strip()
    if not choice:
        return None

    try:
        idx = int(choice)
        if 1 <= idx <= len(uf2_files):
            return uf2_files[idx - 1]
    except ValueError:
        pass

    print("Invalid input, skipping.\n")
    return None

#######################
# OPERATIONAL LOGIC   #
#######################

def prepare_device_for_flashing(port):
    """Prepare the device for flashing (enter bootloader if needed)"""
    if port:
        ok = enter_bootloader(port)
        if not ok:
            print("Failed to enter bootloader via mpremote.")
            print("Try manually entering BOOTSEL (hold BOOTSEL button and plug in). Exiting.")
            sys.exit(1)
    else:
        # No device found or user skipping detection
        print("Assuming the Pico W is already in BOOTSEL mode (RPI-RP2 drive).")
        print("If not, hold BOOTSEL, plug in the Pico, and a drive should appear.")
        print("Press Enter to continue once the drive is present.")
        input()

def flash_firmware(firmware_path):
    """Flash the firmware to the device"""
    return copy_uf2_to_bootloader(firmware_path)

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
    print("Rebooting device into bootloader mode via mpremote...")
    try:
        result = subprocess.run(
            ["mpremote", "connect", port, "bootloader"],
            capture_output=True, text=True
        )
    except FileNotFoundError:
        print("Error: 'mpremote' command not found. Is it installed/bundled?")
        return False
    if result.returncode != 0:
        print("Error: mpremote failed to enter bootloader.")
        print("mpremote output:\n", result.stdout or result.stderr)
        return False
    return True

def copy_uf2_to_bootloader(firmware_path):
    """Copy the UF2 file to the bootloader drive"""
    pico_drive = None
    print("Looking for Pico in bootloader mode...")

    try:
        if os.name == 'nt':  # Windows
            print("Waiting a few seconds for the BOOTSEL drive to appear...")
            time.sleep(2)
            pico_drive = find_rpi_rp2_drive_windows()
        else:  # Linux/macOS
            pico_drive = find_rpi_rp2_drive_linux_macos()

        if pico_drive:
            print(f"Found Pico's bootloader drive at {pico_drive}")
            print(f"Copying {firmware_path} to {pico_drive} ...")
            import shutil
            try:
                shutil.copy(firmware_path, pico_drive)
                print("Copy complete. The board should reboot into MicroPython shortly.")
                return True
            except Exception as e:
                print(f"Error copying file: {e}")
                print("You may need to copy the file manually.")
        else:
            print("Unable to auto-detect the RPI-RP2 drive.")
    except Exception as e:
        print(f"Error during drive detection: {e}")

    # If we get here, automatic flashing failed
    print("\nManual flashing instructions:")
    print("1. Look for a drive named 'RPI-RP2' in your file explorer")
    print("2. Copy the UF2 file to this drive")
    print("3. The Pico should automatically reboot once the file is copied")
    print("\nPress Enter once done, or Ctrl+C to abort.")
    input()
    return True

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

def find_rpi_rp2_drive_windows():
    """Find the RPI-RP2 drive on Windows"""
    import string
    for drive in string.ascii_uppercase:
        drive_path = f"{drive}:\\INFO_UF2.TXT"
        if os.path.exists(drive_path):
            return f"{drive}:\\"
    return None

def find_rpi_rp2_drive_linux_macos():
    """Find the RPI-RP2 drive on Linux/macOS"""
    for drive_dir in ['/Volumes', '/media']:
        if not os.path.isdir(drive_dir):
            continue
        for root, dirs, files in os.walk(drive_dir):
            if "INFO_UF2.TXT" in files:
                return root
    return None


if __name__ == "__main__":
    main()
