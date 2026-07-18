# TrenchCoat

A simple tool by Warped Pinball for flashing MicroPython firmware and software to Warped Pinball hardware.

## Features
- Flash MicroPython firmware to Warped Pinball hardware
- Automatically detects connected devices
- Supports multiple firmware versions

## Installing & Using TrenchCoat

> [!IMPORTANT]
> Turn off your pinball machine before flashing firmware. You do not need to uninstall your Vector board to flash firmware.

See the **[Trench Coat Setup Guide](Trench-Coat-Install-Guide.md)** for step-by-step instructions on downloading, opening, and running TrenchCoat on Windows, macOS, and Linux.

In short: download the latest build for your operating system from the [releases page](https://github.com/warped-pinball/trench-coat/releases/latest), run it, and follow the on-screen prompts.

## Developing locally
To develop locally, set up a Python virtual environment and install the required dependencies:
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

# Run the tests
python -m pytest

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
