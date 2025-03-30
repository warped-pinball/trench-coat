import time

from src.core import flash_firmware, flash_software
from src.interactive import display_welcome, select_software, select_uf2
from src.ray import Ray
from src.util import graceful_exit


def main():
    display_welcome()
    # Firmware selection
    firmware = select_uf2()

    # Select the software to flash
    software = select_software()

    # flash devices until user cancels
    dots = 0
    while True:
        # Listen for devices / allow user to exit
        print("If you want to cancel, press Ctrl+C")
        while True:
            boards = Ray.find_boards()
            if boards:
                print()
                break

            dots = (dots + 1) % 5
            print("\rListening for devices" + "." * dots + " " * (5 - dots), end="")
            time.sleep(0.5)

        flash_firmware(firmware)
        time.sleep(5)

        flash_software(software)
        time.sleep(5)

        dots = 0
        while boards:
            boards = Ray.find_boards()
            if not boards:
                print()
                break
            dots = (dots + 1) % 5
            print("\rWaiting for devices to disconnect" + "." * dots + " " * (5 - dots), end="")
            time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nError: {e}")
        graceful_exit()
