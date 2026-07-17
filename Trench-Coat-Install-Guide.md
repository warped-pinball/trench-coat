# Trench Coat Setup Guide

Trench Coat reprograms the operating system and application software on any Vector board. Download the app for your computer, make your selections, then plug in the board.

> [!IMPORTANT]
> Leave the pinball machine turned **off** for the entire process. You do not need to remove the Vector board from the machine. The board is powered through the USB cable from your computer, so the machine never needs to be switched on.

## Step 1 — Download the file for your computer

Pick the option that matches your machine. It's a single file — nothing to install.

| Your computer | Who it's for | Download |
| --- | --- | --- |
| Windows | Any Windows 10 or 11 PC | `TrenchCoat-windows.exe` |
| Mac – Apple Silicon | Newer Macs (2020+) with an M1, M2, M3, or M4 chip | `TrenchCoat-macos-arm64` |
| Mac – Intel | Older Macs (before 2020) with an Intel processor | `TrenchCoat-macos-x86_64` |
| Linux | Most 64-bit desktop Linux distributions | `TrenchCoat-linux` |

Get the latest build from the [releases page](https://github.com/warped-pinball/trench-coat/releases/latest).

**Not sure which Mac?** Click the Apple menu (top-left) → *About This Mac*. If it lists a chip named Apple M1/M2/M3/M4, choose Apple Silicon. If it says Intel, choose Intel.

## Step 2 — Open it the first time

Your computer will warn you the first time you run it, because Trench Coat isn't code-signed with Microsoft or Apple. It's safe — you just need to tell your system to allow it. You only do this once.

### Windows

1. Double-click `TrenchCoat-windows.exe` in your Downloads folder.
2. A blue box says "Windows protected your PC." Click the small **More info** link.
3. A new button appears — click **Run anyway**.

> [!NOTE]
> A black command window opens when it runs — that's normal, that's the app.

### Mac (Apple Silicon or Intel)

1. Find the downloaded file in Finder (usually your Downloads folder).
2. Right-click the file (or hold Control and click) and choose **Open**.
3. A warning appears — this time it includes an **Open** button. Click it.

> [!NOTE]
> If it's blocked on the newest macOS: double-click once, then go to Apple menu → **System Settings** → **Privacy & Security**, scroll down, and click **Open Anyway**. It runs in the Terminal app — that's expected.

### Linux

```bash
# Open a terminal in the folder where you downloaded the file
chmod +x TrenchCoat-linux
./TrenchCoat-linux
```

## Step 3 — Make your selections in the app

With the app running, make your selections **before** plugging in the board. Trench Coat asks you two questions up front:

1. **Which game series** you're flashing (this determines the operating system firmware).
2. **Which software version** to install for that series.

Do not plug in the Vector board yet — the prompts below appear with nothing connected.

### Example: choosing the game series

```
? Select the game series to flash: (Use arrow keys)
❯ Sys11
  WPC
  EM
  DataEast
  Classic (coming soon)
  Custom firmware...
  Exit
```

For a WPC-era machine, select **WPC**. For System 9 or System 11, select **Sys11**. Series marked "(coming soon)" don't have a released OS yet and can't be selected.

### Example: choosing the software version

```
? Select a software release: (Use arrow keys)
❯ WPC v1.7.5  (Vector 1.11.10, 2026-06-01)  (Recommended)
  WPC v1.7.4  (Vector 1.11.9, 2026-05-12)
  WPC v1.7.3  (Vector 1.11.7, 2026-04-02)
  Exit
```

The top entry is marked **(Recommended)** and is almost always the right choice — it's the newest tested release for your selected series.

## Step 4 — Plug in your Vector board

Only now, after your selections are made, connect the board.

> [!WARNING]
> Do **not** turn the pinball machine on. It must stay powered off for the entire time you use Trench Coat.

1. Using a USB cable, plug the Vector board directly into your computer (PC, Mac, or Linux).
2. Trench Coat detects the board automatically and reports what it found (board type and system).
3. Follow any remaining on-screen prompts to flash the firmware and software.

---

**Trouble downloading?** All files also live on the [releases page](https://github.com/warped-pinball/trench-coat/releases/latest).

Trench Coat is open-source and not code-signed, which is why your computer shows a first-run warning. The download links above always give you the latest version.
