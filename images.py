"""Shared image handling: validate and re-encode uploads as clean JPEGs (strips metadata)."""
import io, os, secrets
from PIL import Image, ImageOps
import config
Image.MAX_IMAGE_PIXELS = 30_000_000
MAX_BYTES = 5 * 1024 * 1024

def process_image(data, max_px=800):
    try:
        im = Image.open(io.BytesIO(data)); im.verify()
        im = Image.open(io.BytesIO(data))
        if im.format not in ('JPEG', 'PNG', 'WEBP'): return None
        im = ImageOps.exif_transpose(im).convert('RGB'); im.thumbnail((max_px, max_px))
        out = io.BytesIO(); im.save(out, 'JPEG', quality=85, optimize=True); return out.getvalue()
    except Exception:
        return None

def save_public_image(file_storage, subfolder, max_px=1600):
    """Save an uploaded image under static/uploads/<subfolder>/. Returns '<subfolder>/<name>.jpg' or raises ValueError."""
    data = file_storage.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES: raise ValueError('Please choose an image under 5 MB.')
    jpg = process_image(data, max_px)
    if jpg is None: raise ValueError('That file is not a valid JPG, PNG or WebP image.')
    folder = os.path.join(config.UPLOAD_DIR, subfolder); os.makedirs(folder, exist_ok=True)
    fn = secrets.token_hex(12) + '.jpg'
    with open(os.path.join(folder, fn), 'wb') as fh: fh.write(jpg)
    return f'{subfolder}/{fn}'

def delete_public_image(rel):
    if rel and '..' not in rel:
        try: os.remove(os.path.join(config.UPLOAD_DIR, rel))
        except OSError: pass
