# trenchcoat.spec
# PyInstaller spec file for building a SINGLE-FILE "TrenchCoat" executable.

block_cipher = None

# List any modules that PyInstaller might not auto-detect.
# - mpremote + mpremote.main are needed if we call mpremote via subprocess
#   or if it’s dynamically imported. 
# - ipaddress is usually in Python 3 stdlib, but sometimes PyInstaller
#   needs it forced as a hidden import on some systems.
hidden_imports = [
    "mpremote",
    "mpremote.main",
    "ipaddress"
]

# ----------------------------------------------------------------------------
# 1) ANALYSIS: Determine which modules are needed.
# ----------------------------------------------------------------------------
a = Analysis(
    ["trenchcoat.py"],    # Your main script
    pathex=["."],         # Search path (use '.' if your script is in the current dir)
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False
)

# ----------------------------------------------------------------------------
# 2) PYZ: Create a .pyz archive of all Python modules.
# ----------------------------------------------------------------------------
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ----------------------------------------------------------------------------
# 3) EXE: Build the main executable object in memory.
# ----------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,            # Scripts from the analysis
    [],
    exclude_binaries=True,
    name="TrenchCoat",    # Final name (no extension on Linux, .exe on Windows)
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,             # Use UPX compression if available
    console=True,         # We want a CLI, so console=True
)

# ----------------------------------------------------------------------------
# 4) BUNDLE: Combine everything into ONE FILE.
# ----------------------------------------------------------------------------
# By default, PyInstaller’s spec would do a COLLECT for one-dir mode. 
# Instead, we use BUNDLE(..., onefile=True) to produce a single-file executable.
app = BUNDLE(
    exe,
    name="TrenchCoat",
    onefile=True
)
