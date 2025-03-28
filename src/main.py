from src.core import flash_firmware, flash_software
from src.interactive import display_welcome, select_devices, select_software, select_uf2


def main():
    display_welcome()

    # Step 1: Device detection and selection
    ports = select_devices()

    # Step 2: Firmware selection
    firmware = select_uf2()

    # Step 3: Select the software to flash
    software = select_software()

    for port in ports:
        # Step 4: Flash the firmware
        if firmware:
            flash_firmware(firmware, port)

        # Step 5: Flash the software
        if software:
            flash_software(software, port)


if __name__ == "__main__":
    main()
