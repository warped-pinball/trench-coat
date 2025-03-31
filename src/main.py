import atexit
import signal
import traceback

from src.core import flash_firmware, flash_software, list_rpi_rp2_drives
from src.interactive import display_welcome, select_software, select_uf2
from src.ray import Ray
from src.util import graceful_exit, wait_for

atexit.register(Ray.close_all)


# Set up signal handler for Ctrl+C
def signal_handler(sig, frame):
    print("\nCtrl+C pressed. Cleaning up...")
    Ray.close_all()
    graceful_exit(now=True)


signal.signal(signal.SIGINT, signal_handler)


def wait_for_devices():
    def firmware_listen_func():
        print("Listening for devices (press ctrl + c to exit)", end="")
        return len(Ray.find_board_ports() + list_rpi_rp2_drives())

    try:
        wait_for(firmware_listen_func, timeout=None)
    except KeyboardInterrupt:
        print("\nExiting...")
        graceful_exit(now=True)

    return len(Ray.find_board_ports() + list_rpi_rp2_drives())


def wait_for_disconnect():
    # wait until all devices disconnect
    def discconnect_listen_func():
        print("Flash complete, disconnetc all boards before flashing more", end="")
        return len(Ray.find_board_ports() + list_rpi_rp2_drives()) == 0

    try:
        wait_for(discconnect_listen_func, timeout=None)
    except KeyboardInterrupt:
        print("\nExiting...")
        graceful_exit(now=True)


def main():
    display_welcome()
    # Firmware selection
    firmware = select_uf2()

    # Select the software to flash
    software = select_software()

    # flash devices until user cancels
    while True:
        # wait until at least one device is connected
        total_boards = wait_for_devices()

        flash_firmware(firmware)

        # wait until all devices finish flashing
        def software_listen_func():
            print("Waiting for boards to reboot", end="")
            return len(Ray.find_board_ports()) == total_boards

        wait_for(software_listen_func, timeout=360)

        flash_software(software)

        wait_for(software_listen_func, timeout=360)

        wait_for_disconnect()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nError: {e}")
        traceback.print_exc()
        print("Program did not exit gracefully, do not install boards in pinball machine without sucsessfully flashing.")
        graceful_exit()
