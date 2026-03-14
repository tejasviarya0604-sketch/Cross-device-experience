# Photo OCR → Windows Notification

Take a photo on your iPhone — the moment it syncs to your PC via iCloud, a Windows notification appears with the extracted text, ready to copy.

**No tapping required on the phone after taking the photo.**

## How It Works

```
iPhone camera  →  iCloud Photos (auto-sync)  →  PC folder watcher  →  Windows OCR  →  Toast notification
```

The PC runs a background watcher. The moment iCloud delivers a new photo to your PC (typically within 30–60 seconds on Wi-Fi), it runs OCR and shows a Windows notification.

---

## Prerequisites

**On your PC:**
- Windows 10/11
- Python 3.10 or newer — download from [python.org](https://python.org), check **"Add to PATH"** during install
- **iCloud for Windows** — install from the Microsoft Store (search "iCloud")
- An OCR language pack:
  `Settings → Time & Language → Language & Region → [your language] → Optional features → search "OCR" → Install`

**On your iPhone:**
- iCloud Photos enabled: `Settings → [your name] → iCloud → Photos → toggle on`
- Connected to Wi-Fi (photos sync faster on Wi-Fi)

---

## PC Setup

1. Open the **iCloud** app on your PC, sign in with your Apple ID, and enable **Photos** sync. Note where iCloud saves your photos (usually `Pictures\iCloud Photos\Photos`).

2. Right-click `setup.bat` → **Run as administrator**
   - Creates a Python virtual environment
   - Installs all dependencies
   - Registers the watcher to auto-start 30 seconds after you log in

3. Double-click **`start.bat`** to launch the watcher now. A terminal window confirms it's running and shows which folder it's watching.

That's it — no phone configuration needed.

---

## Using the Notification

After you take a photo on your iPhone, wait ~30–60 seconds for iCloud to sync. A Windows notification appears automatically:

| Element | Description |
|---|---|
| Image thumbnail | Preview of the photo |
| Text | The extracted text (first 200 characters) |
| **Copy Text** | Copies the full extracted text to your clipboard |
| **Open Image** | Opens the photo in your default image viewer |
| **Dismiss** | Closes the notification |

If no text is found in the photo, the notification says "No text found in this image" (no Copy button).

---

## Troubleshooting

**Notification never appears**
- Check that iCloud for Windows is running and Photos sync is enabled (look for the iCloud icon in the system tray).
- Verify that new photos are actually appearing in your iCloud Photos folder on the PC.
- Make sure the watcher is running: double-click `start.bat` and check the terminal output.

**"iCloud Photos folder not found" error on startup**
- Install iCloud for Windows from the Microsoft Store and enable Photos sync.
- If you changed the default iCloud folder location, open `server.py` and add your custom path to the `ICLOUD_CANDIDATE_PATHS` list near the top.

**Notification doesn't appear**
- Check that Windows **Focus Assist / Do Not Disturb** is turned off.
- Check that notifications are enabled for "cmd.exe" in `Settings → System → Notifications`.

**OCR returns no text**
- Install an OCR language pack: `Settings → Time & Language → Language & Region → [your language] → Optional features → search "OCR" → Install`.

**Sync is slow (more than 2 minutes)**
- Make sure your iPhone is on Wi-Fi. iCloud syncs much slower over cellular.
- Open the iCloud app on your PC and check if it shows "Syncing…".

**Watcher doesn't auto-start after reboot**
- Re-run `setup.bat` as Administrator.
- Verify in Task Scheduler: search "Task Scheduler" in Start → look for `PhotoOCRServer`.

**Stop the watcher**
- Open Task Manager → Details → find `pythonw.exe` → End Task.
- Or run `taskkill /f /im pythonw.exe` in a terminal.
