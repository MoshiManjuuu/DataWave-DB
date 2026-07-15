# Turning WarrantIQ into a double-click app (Windows)

This folder is your app, set up to be built into a single `WarrantyTracker.exe`.
Once it's built, you (and anyone you copy the .exe to) never need Python,
pip, or a command prompt again — just double-click the icon.

## One-time setup (you do this once)

1. If you don't already have Python, install it from python.org (any
   version 3.9+). During install, tick **"Add Python to PATH."**
2. Double-click **`build_exe.bat`** in this folder.
   - A window will open, install a couple of packages, then build the app.
     It takes a minute or two. Don't close the window until it says "Done!"
3. When it finishes, open the new `dist` folder. Inside is
   **`WarrantyTracker.exe`**.
4. Move/copy `WarrantyTracker.exe` to your Desktop (or anywhere you like —
   it's fully self-contained, you can move it freely).

## Using the app from now on

- Double-click `WarrantyTracker.exe`.
- A small window opens showing it's running, and your browser opens
  automatically to the app — that's it, no typing required.
- To close the app, just close that window.
- Want a Start Menu / taskbar shortcut? Right-click the .exe → **Send to →
  Desktop (create shortcut)**, then drag that shortcut to your taskbar or
  Start menu, and rename/re-icon it however you like (right-click →
  Properties → Change Icon).

## Your existing data

Your current `warranty.db` (with your existing records, priced products,
and stock items) is bundled into the .exe and copied into
`%APPDATA%\WarrantyTracker\warranty.db` the very first time you run it.
After that, the app always uses that copy, so your data persists across
runs and across rebuilding the .exe in the future.

## Other people on your network

The app still binds to your whole network like before. The console window
will print an address like `http://192.168.1.23:5000` — anyone on the same
WiFi/LAN can open that in their browser to use the same app and data.

## If you ever change app.py

Just re-run `build_exe.bat` to rebuild the .exe with your changes. Your
data in `%APPDATA%\WarrantyTracker\warranty.db` is untouched by rebuilding.
