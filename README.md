[![GitHub Release](https://img.shields.io/github/v/release/warped-pinball/vector?color=blue)](https://github.com/warped-pinball/vector/releases/latest)
![License](https://img.shields.io/badge/license-CC%20BY--NC-blue)
![GitHub issues](https://img.shields.io/github/issues/warped-pinball/vector)
![GitHub last commit](https://img.shields.io/github/last-commit/warped-pinball/vector)

# TrenchCoat

A simple tool by Warped Pinball for flashing MicroPython firmware to Warped Pinball hardware.

## Features
- Flash MicroPython firmware to Warped Pinball hardware
- Automatically detects connected devices
- Supports multiple firmware versions

## How to Use

> [!IMPORTANT]
> Turn off your pinball machine before flashing firmware. You do not need to uninstall your vector board to flash firmware.

1. Download the latest version of trench coat for your operating system [here](https://github.com/warped-pinball/trench-coat/releases/latest)
2. Connect your Warped Pinball hardware to your computer using a USB cable.
3. Run trench-coat:
    - **Windows**: double click on `TrenchCoat-windows.exe`. If you get a warning that the file is unrecognized, click "More info" and then "Run anyway".
    - **Linux & MacOS**: open a terminal and follow these steps:
        ```bash
        # Change to the directory where you downloaded the file
        cd ~/Downloads

        # Make the file executable
        chmod +x ./TrenchCoat-linux

        # Run the file
        ./TrenchCoat-linux
        ```
4. Follow the on-screen prompts to flash the firmware to your device.

## Package Information

This codebase is also available as a [Python package](https://pypi.org/project/wptc/). You can install it using pip: `pip install wptc`. This is mainly useful for building the [Vector Codebase](https://github.com/warped-pinball/vector)

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

## Contributors

<a href="https://github.com/warped-pinball/trench-coat/graphs/contributors" alt="Contributors">
  <img src="https://contrib.rocks/image?repo=warped-pinball/trench-coat" />
</a>


## License

This project is licensed under the CC BY-NC License. See the [LICENSE](LICENSE) file for details.
