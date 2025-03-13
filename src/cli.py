import argparse
import os
import sys

from src.core import find_pico_ports_separated, flash_firmware, list_rpi_rp2_drives


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Trenchcoat - Flash MicroPython firmware to Warped Pinball hardware")
    parser.add_argument("-f", "--firmware", help="Path to UF2 firmware file")
    parser.add_argument("-p", "--ports", nargs="+", help="Serial ports of devices in normal mode to flash")
    parser.add_argument("-l", "--list", action="store_true", help="List available devices and exit")
    parser.add_argument("-a", "--all", action="store_true", help="Flash all detected devices")
    parser.add_argument("-i", "--interactive", action="store_true", help="Force interactive mode")

    return parser.parse_args()


def cmd_mode(args):
    """Run in command line mode based on provided arguments"""
    if args.list:
        list_devices()
        sys.exit(0)

    # Check if firmware is specified
    if not args.firmware:
        print("Error: Firmware path is required when using command line mode.")
        print("Use --firmware to specify the path to a UF2 file.")
        sys.exit(1)

    # Check if firmware file exists
    if not os.path.isfile(args.firmware):
        print(f"Error: Firmware file not found: {args.firmware}")
        sys.exit(1)

    # Select ports based on arguments
    normal_ports = []
    bootloader_ports = []

    if args.all:
        normal_ports, bootloader_ports = find_pico_ports_separated()
        print(f"Found {len(normal_ports)} normal mode device(s) and {len(bootloader_ports)} bootloader mode device(s)")
    elif args.ports:
        # Verify the specified ports exist
        available_ports, _ = find_pico_ports_separated()
        for port in args.ports:
            if port in available_ports:
                normal_ports.append(port)
            else:
                print(f"Warning: Port {port} not found or not in normal mode.")

    if not normal_ports and not bootloader_ports:
        print("No valid devices selected for flashing.")
        sys.exit(1)

    # Flash the firmware
    if flash_firmware(args.firmware, normal_ports, bootloader_ports):
        sys.exit(0)
    else:
        sys.exit(1)


def list_devices():
    """List all available devices"""
    ports, bootloader_ports = find_pico_ports_separated()
    print("Available devices:")
    for port in ports:
        print(f"  {port} (Normal Mode)")
    for port in bootloader_ports:
        print(f"  {port} (Bootloader Mode)")

    drives = list_rpi_rp2_drives()
    if drives:
        print("\nBootloader drives:")
        for drive in drives:
            print(f"  {drive}")
