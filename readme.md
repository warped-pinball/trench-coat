# TrenchCoat

A simple tool by Warped Pinball for flashing MicroPython firmware to Warped Pinball hardware.


# Developing locally

```bash
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
