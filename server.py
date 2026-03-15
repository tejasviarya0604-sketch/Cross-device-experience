import asyncio
import logging
import os
import tempfile
import threading
import time
import winreg
from pathlib import Path

import pyperclip
from flask import Flask, jsonify, request
from PIL import Image
from pillow_heif import register_heif_opener
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver
from windows_toasts import (
    InteractableWindowsToaster,
    Toast,
    ToastButton,
    ToastDisplayImage,
    ToastDuration,
    ToastImagePosition,
)

from winrt.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage import FileAccessMode
from winrt.windows.storage.streams import FileRandomAccessStream

# Register HEIC/HEIF support so Pillow handles iPhone photos transparently
register_heif_opener()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
_ICLOUD_SUFFIX = ".icloud"

UPLOAD_DIR = Path(tempfile.gettempdir()) / "cross_device_ocr" / "uploads"
FLASK_PORT = 5000

THUMB_SIZE = (256, 256)
OCR_MAX_DIM = 4096  # WinRT OCR cap is 5000px; stay safely below
THUMB_DIR = Path(tempfile.gettempdir()) / "cross_device_ocr" / "thumbs"
CLEANUP_AGE_SECONDS = 3600  # 1 hour

# Candidate iCloud Photos locations (iCloud for Windows default and variants)
ICLOUD_CANDIDATE_PATHS = [
    Path.home() / "Pictures" / "iCloud Photos" / "Photos",
    Path.home() / "Pictures" / "iCloud Photos",
    Path.home() / "iCloudDrive" / "iCloud Photos" / "Photos",
    Path.home() / "iCloudDrive" / "iCloud Photos",
]

# Using the Command Prompt AUMID avoids any registry registration while still
# allowing on_activated callbacks to fire from the Windows Action Center.
TOASTER_AUMID = "CrossDeviceExperience.iPhonePhotos"


_ICON_PATH = Path(__file__).parent / "Phone.png"


def _register_aumid():
    key_path = f"SOFTWARE\\Classes\\AppUserModelId\\{TOASTER_AUMID}"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "My iPhone 17")
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(_ICON_PATH))
        log.info("AUMID registered with phone icon")
    except Exception:
        log.warning("Could not register AUMID")

_LOG_FILE = Path(__file__).parent / "server.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# iCloud folder detection
# ---------------------------------------------------------------------------

def find_icloud_photos_folder() -> Path | None:
    for candidate in ICLOUD_CANDIDATE_PATHS:
        if candidate.exists():
            log.info("Found iCloud Photos folder: %s", candidate)
            return candidate
    return None


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------

class ImageProcessor:
    def __init__(self):
        THUMB_DIR.mkdir(parents=True, exist_ok=True)

    def make_thumbnail(self, image_path: Path) -> Path:
        """Create a small JPEG thumbnail for the toast image preview."""
        img = Image.open(image_path).convert("RGB")
        img.thumbnail(THUMB_SIZE, Image.LANCZOS)
        thumb_path = THUMB_DIR / (image_path.stem + "_thumb.jpg")
        img.save(str(thumb_path), "JPEG", quality=85)
        return thumb_path

    def prepare_for_ocr(self, image_path: Path) -> Path:
        """Convert image to an RGB PNG, resizing if needed, for WinRT OCR."""
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        if max(w, h) > OCR_MAX_DIM:
            scale = OCR_MAX_DIM / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        ocr_path = THUMB_DIR / (image_path.stem + "_ocr.png")
        img.save(str(ocr_path), "PNG")
        return ocr_path

    def cleanup_old_thumbs(self):
        """Remove thumbnails older than CLEANUP_AGE_SECONDS."""
        cutoff = time.time() - CLEANUP_AGE_SECONDS
        for f in THUMB_DIR.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception as e:
                log.warning("Cleanup error for %s: %s", f, e)


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

async def _ocr_async(png_path_str: str) -> str:
    stream = None
    try:
        stream = await FileRandomAccessStream.open_async(png_path_str, FileAccessMode.READ)
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()

        # OcrEngine requires Bgra8 pixel format
        if bitmap.bitmap_pixel_format != BitmapPixelFormat.BGRA8:
            bitmap = SoftwareBitmap.convert(bitmap, BitmapPixelFormat.BGRA8)

        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            log.error(
                "OcrEngine returned None. "
                "Install an OCR language pack in Windows Settings > "
                "Time & Language > Language."
            )
            return ""

        result = await engine.recognize_async(bitmap)
        lines = []
        for line in result.lines:
            t = line.text.strip()
            # Skip edge artifacts: very short lines or lines with few real letters
            alpha = sum(c.isalpha() for c in t)
            if len(t) >= 4 and alpha >= 3:
                lines.append(t)
        return "\n".join(lines).strip()
    except Exception:
        log.exception("OCR failed for %s", png_path_str)
        return ""
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass


def run_ocr(png_path: Path) -> str:
    """Synchronous wrapper — creates a fresh asyncio event loop per call."""
    return asyncio.run(_ocr_async(str(png_path)))


# ---------------------------------------------------------------------------
# Toast notifications
# ---------------------------------------------------------------------------

class ToastNotifier:
    def __init__(self):
        self.toaster = InteractableWindowsToaster(
            "Photo OCR", notifierAUMID=TOASTER_AUMID
        )

    def show(self, image_path: Path, thumb_path: Path, text: str):
        try:
            toast = Toast()
            toast.duration = ToastDuration.Long
            toast.tag = image_path.stem[:60]
            toast.group = "iphone_photos"

            # Image preview (AppLogo = square thumbnail on the left)
            toast.AddImage(
                ToastDisplayImage.fromPath(
                    str(thumb_path),
                    altText="Photo preview",
                    position=ToastImagePosition.Hero,
                )
            )

            if text:
                display_text = text if len(text) <= 200 else text[:200] + "…"
                toast.text_fields = ["Text found in photo", display_text]
                toast.AddAction(ToastButton("Copy Text", "action=copy"))
            else:
                toast.text_fields = ["New photo synced", "No text found in this image."]

            toast.AddAction(ToastButton("Open Image", "action=open"))

            # Capture values in a closure so each toast has its own callback
            _image_path = str(image_path)
            _text = text

            def on_activated(event):
                try:
                    if event.arguments == "action=copy":
                        pyperclip.copy(_text)
                        log.info("Text copied to clipboard (%d chars)", len(_text))
                    elif event.arguments == "action=open":
                        os.startfile(_image_path)
                        log.info("Opened image: %s", _image_path)
                except Exception:
                    log.exception("on_activated error")

            toast.on_activated = on_activated
            self.toaster.show_toast(toast)
            log.info("Toast shown for %s", image_path.name)
        except Exception:
            log.exception("Failed to show toast")

    def show_startup(self, watch_folder: Path):
        try:
            toast = Toast()
            toast.text_fields = [
                "Photo OCR is running",
                f"Watching: {watch_folder}",
            ]
            self.toaster.show_toast(toast)
            log.info("Startup toast shown")
        except Exception:
            log.exception("Failed to show startup toast")


# ---------------------------------------------------------------------------
# Folder watcher
# ---------------------------------------------------------------------------

def _wait_for_file_ready(path: Path, timeout: int = 30) -> bool:
    """Wait until a file stops growing (i.e. iCloud has finished writing it)."""
    prev_size = -1
    for _ in range(timeout):
        try:
            size = path.stat().st_size
            if size > 0 and size == prev_size:
                return True
            prev_size = size
        except FileNotFoundError:
            return False
        time.sleep(1)
    return False


class PhotoEventHandler(FileSystemEventHandler):
    def __init__(self, processor: ImageProcessor, notifier: ToastNotifier):
        super().__init__()
        self.processor = processor
        self.notifier = notifier
        # Track recently seen paths to avoid duplicate events
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def _is_image(self, path: Path) -> bool:
        return path.suffix.lower() in IMAGE_EXTENSIONS

    def _handle(self, path: Path):
        key = str(path).lower()
        with self._lock:
            if key in self._seen:
                return
            self._seen.add(key)

        # Process in a daemon thread so the watchdog callback returns immediately
        threading.Thread(
            target=self._process,
            args=(path,),
            daemon=True,
        ).start()

    def _process(self, image_path: Path):
        log.info("New photo detected: %s", image_path.name)

        if not _wait_for_file_ready(image_path):
            log.warning("Timed out waiting for file to be ready: %s", image_path.name)
            with self._lock:
                self._seen.discard(str(image_path))
            return

        try:
            thumb_path = self.processor.make_thumbnail(image_path)
            ocr_png = self.processor.prepare_for_ocr(image_path)
            text = run_ocr(ocr_png)

            try:
                ocr_png.unlink()
            except Exception:
                pass

            self.notifier.show(image_path, thumb_path, text)
        except Exception:
            log.exception("Failed to process photo: %s", image_path.name)

    def _trigger_icloud_download(self, real_path: Path):
        """Open the target path to force iCloud to download it; on_moved fires on completion."""
        log.info("Triggering iCloud download for: %s", real_path.name)
        try:
            with open(real_path, "rb") as f:
                f.read(1)
        except Exception:
            log.warning("Could not trigger download for %s — will wait for on_moved", real_path.name)

    def on_created(self, event):
        if not event.is_directory:
            path = Path(event.src_path)
            if self._is_image(path):
                self._handle(path)
            elif path.suffix.lower() == _ICLOUD_SUFFIX:
                # Trigger iCloud on-demand download by opening the real path
                real_path = path.with_suffix("")  # strip ".icloud"
                if self._is_image(real_path):
                    threading.Thread(
                        target=self._trigger_icloud_download,
                        args=(real_path,),
                        daemon=True,
                    ).start()

    def on_moved(self, event):
        # iCloud sometimes syncs as a .icloud placeholder then renames on download
        if not event.is_directory:
            path = Path(event.dest_path)
            if self._is_image(path):
                self._handle(path)


# ---------------------------------------------------------------------------
# Flask upload server
# ---------------------------------------------------------------------------

flask_app = Flask(__name__)
_processor_ref = None
_notifier_ref = None
_upload_seen: dict[str, float] = {}
_upload_seen_lock = threading.Lock()
_UPLOAD_DEDUP_SECONDS = 60


@flask_app.route("/upload", methods=["POST"])
def upload():
    if "image" not in request.files:
        if request.files:
            file = next(iter(request.files.values()))
        else:
            return jsonify({"error": "No image field"}), 400
    else:
        file = request.files["image"]

    # Deduplicate — ignore same filename within 60 seconds
    original_name = Path(file.filename).name if file.filename else ""
    now = time.time()
    with _upload_seen_lock:
        last_seen = _upload_seen.get(original_name, 0)
        if now - last_seen < _UPLOAD_DEDUP_SECONDS:
            log.info("Duplicate upload ignored: %s", original_name)
            return jsonify({"status": "duplicate"}), 200
        _upload_seen[original_name] = now
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    suffix = Path(file.filename).suffix or ".jpg"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    save_path = UPLOAD_DIR / f"upload_{int(time.time())}{suffix}"
    file.save(str(save_path))
    log.info("Received upload: %s", save_path.name)

    threading.Thread(
        target=_process_upload,
        args=(save_path,),
        daemon=True,
    ).start()
    return jsonify({"status": "ok"}), 200


def _process_upload(image_path: Path):
    try:
        thumb_path = _processor_ref.make_thumbnail(image_path)
        ocr_png = _processor_ref.prepare_for_ocr(image_path)
        text = run_ocr(ocr_png)
        try:
            ocr_png.unlink()
        except Exception:
            pass
        _notifier_ref.show(image_path, thumb_path, text)
    except Exception:
        log.exception("Failed to process upload: %s", image_path.name)


def _start_flask():
    import logging as _logging
    _logging.getLogger("werkzeug").setLevel(_logging.WARNING)
    flask_app.run(host="0.0.0.0", port=FLASK_PORT, threaded=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("=" * 52)
    print("  Photo OCR — iCloud Watcher")
    print("=" * 52)

    _register_aumid()

    processor = ImageProcessor()
    notifier = ToastNotifier()

    _processor_ref = processor
    _notifier_ref = notifier

    # --- iCloud watcher disabled (comment back in to re-enable) ---
    # watch_folder = find_icloud_photos_folder()
    # if watch_folder:
    #     notifier.show_startup(watch_folder)
    #     event_handler = PhotoEventHandler(processor, notifier)
    #     observer = PollingObserver(timeout=10)
    #     observer.schedule(event_handler, str(watch_folder), recursive=True)
    #     observer.start()
    # else:
    #     log.warning("iCloud Photos folder not found — watcher disabled")

    threading.Thread(target=_start_flask, daemon=True).start()
    log.info("Upload server listening on port %d", FLASK_PORT)

    # Periodic thumbnail cleanup
    def _cleanup_loop():
        while True:
            time.sleep(1800)
            processor.cleanup_old_thumbs()

    threading.Thread(target=_cleanup_loop, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down...")
