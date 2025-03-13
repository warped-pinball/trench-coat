from src.core import flash_firmware
from src.interactive import display_welcome, select_devices, select_uf2


def main():
    display_welcome()

    # Step 1: Firmware selection
    firmware_path = select_uf2()

    # Step 2: Device detection and selection
    ports = select_devices()

    # Step 3: Flash the firmware
    flash_firmware(firmware_path, ports)


if __name__ == "__main__":
    main()
