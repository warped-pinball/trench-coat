# TrenchCoat

A simple tool by Warped Pinball for flashing MicroPython firmware to Warped Pinball hardware.

## Features
- Flash MicroPython firmware to Warped Pinball hardware
- Automatically detects connected devices
- Supports multiple firmware versions

## How to Use

> [!IMPORTANT]
> Turn off your pinball machine before flashing firmware. You do not need to uninstall your vector board to flash firmware.

### Windows

1. Open the latest release of TrenchCoat.
2. Download TrenchCoat.exe from the attachments
3. Open the Zip file and run the TrenchCoat.exe file.
4. Windows will probably warn you that the file is unrecognized. Click "More info" and then "Run anyway".
5. Connect your Warped Pinball hardware to your computer using a USB cable.
6. Follow the on-screen prompts to flash the firmware to your device.

### Linux & MacOS

1. Open the latest release of TrenchCoat.
2. Download TrenchCoat.zip from the attachments
3. Open the Zip file and extract the contents.
4. Open a terminal and navigate to the extracted folder.
5. Connect your Warped Pinball hardware to your computer using a USB cable.
6. Run trench-coat by executing the following command: `./trench-coat`
7. Follow the on-screen prompts to flash the firmware to your device.

## Developing locally
To develop locally, you need to set up a Python virtual environment and install the required dependencies. Follow these steps:
```bash
# Clone the repository
git clone https://github.com/warped-pinball/trench-coat.git

# Change into the project directory
cd trench-coat

# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Build the application
pyinstaller --onefile --name TrenchCoat --add-data "uf2:uf2" src/main.py

# Run the application
./dist/TrenchCoat
```
