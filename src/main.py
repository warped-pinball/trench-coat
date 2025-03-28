from src.core import flash_firmware, flash_software
from src.interactive import display_welcome, select_devices, select_software, select_uf2


def main():
    display_welcome()

    # Step 1: Device detection and selection
    ports = select_devices()

    # Step 2: Firmware selection
    firmware_path = select_uf2()

    # Step 3: Flash the firmware
    flash_firmware(firmware_path, ports)

    # Step 4: Select the software to flash
    tag_name = select_software()

    # Step 5: Flash the software
    flash_software(tag_name, ports)


if __name__ == "__main__":
    main()
