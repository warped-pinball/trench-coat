import argparse
import atexit
import signal
import traceback

from src.core import flash_firmware, flash_software, list_rpi_rp2_drives
from src.interactive import display_welcome, select_software, select_uf2
from src.ray import Ray
from src.util import graceful_exit, wait_for

atexit.register(Ray.close_all)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Flash firmware and software to devices")
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.3")
    parser.add_argument("--firmware", help="Path to firmware UF2 file")
    parser.add_argument("--software", help="Path to software file")
    parser.add_argument("--skip-firmware", action="store_true", help="Skip firmware flashing")
    parser.add_argument("--once", action="store_true", help="Flash only once and exit")
    parser.add_argument("--listen-after", action="store_true", help="Show device output after flashing and rebooting")

    args = parser.parse_args()

    # Check for incompatible options
    if args.firmware and args.skip_firmware:
        parser.error("--firmware and --skip-firmware cannot be used together")

    # if listen-after is set, set once to true
    if args.listen_after:
        args.once = True

    return args


# Set up signal handler for Ctrl+C
def signal_handler(sig, frame):
    # Avoid print statements in signal handlers
    Ray.close_all()
    # Use sys.exit to terminate immediately
    import sys

    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def wait_for_one_or_more_devices():
    """
    Wait until at least one device is connected
    """

    def firmware_listen_func():
        print("Listening for devices (press ctrl + c to exit)", end="")
        return len(Ray.find_board_ports() + list_rpi_rp2_drives())

    wait_for(firmware_listen_func, timeout=None)
    return len(Ray.find_board_ports() + list_rpi_rp2_drives())


def wait_for_zero_devices():
    # wait until all devices disconnect
    def disconnect_listen_func():
        print("Flash complete, disconnect all boards before flashing more", end="")
        return len(Ray.find_board_ports() + list_rpi_rp2_drives()) == 0

    wait_for(disconnect_listen_func, timeout=None)


def wait_for_n_devices(n):
    # wait until n devices are connected
    def firmware_listen_func():
        print(f"Waiting for {n} devices (press ctrl + c to exit)", end="")
        return len(Ray.find_board_ports() + list_rpi_rp2_drives()) == n

    wait_for(firmware_listen_func, timeout=None)
    return len(Ray.find_board_ports() + list_rpi_rp2_drives())


def main():
    args = parse_arguments()
    display_welcome()

    # Firmware selection
    firmware = None
    if not args.skip_firmware:
        firmware = args.firmware if args.firmware else select_uf2()

    # Select the software to flash
    software = args.software if args.software else select_software()

    # flash devices until user cancels
    while True:
        # wait until at least one device is connected
        total_boards = wait_for_one_or_more_devices()

        if firmware:
            flash_firmware(firmware)
            wait_for_n_devices(total_boards)

        flash_software(software)

        # if once argument is passed, exit loop immediately
        if args.once:
            break

        # wait until all have restarted
        wait_for_n_devices(total_boards)

        # wait until all devices disconnect
        wait_for_zero_devices()

    if args.listen_after:
        while not (ports := Ray.find_board_ports()):
            pass
        port = ports[0]
        board = Ray(port)
        print("Listening for device output (press ctrl + c to exit)")
        print("")
        print("")
        board.listen()
        board.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nError: {e}")
        traceback.print_exc()
        print("Program did not exit gracefully, do not install boards in pinball machine without sucsessfully flashing.")
        graceful_exit()
