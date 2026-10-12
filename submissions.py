"""Public submissions (name suggestions, driver photos). Nothing goes live until approved in the admin panel."""
import os, re, io, time, secrets, hmac
from flask import request, redirect, url_for, session, flash, abort
from PIL import Image, ImageOps
import config
from admin import adb
from images import process_image

Image.MAX_IMAGE_PIXELS = 30_000_000
MAX_BYTES = 5 * 1024 * 1024
MAX_PENDING = 200
_hits = {}

def init(app):
    app.add_url_rule('/submit/name', 'submit_name', submit_name, methods=['POST'])
    app.add_url_rule('/submit/photo', 'submit_photo', submit_photo, methods=['POST'])

def _guard():
    """Returns driver display name if the request is allowed, otherwise flashes and returns None."""
    if not hmac.compare_digest(request.form.get('csrf', ''), session.get('csrf', 'x')): abort(400, 'Form expired. Go back, refresh and try again.')
    if request.form.get('website'): abort(400)                      # honeypot: real visitors never fill this in
    ip = request.remote_addr or '?'; now = time.time()
    _hits[ip] = [t for t in _hits.get(ip, []) if now - t < 3600]
    if len(_hits[ip]) >= 5: flash('Too many submissions from you for now. Please try again later.', 'error'); return None
    name = request.form.get('driver', '')
    ok = adb().execute("SELECT 1 FROM results r LEFT JOIN name_map nm ON nm.raw_name=r.raw_name WHERE COALESCE(nm.full_name, r.raw_name)=? LIMIT 1", (name,)).fetchone()
    if not ok: abort(404)
    pending = adb().execute("SELECT (SELECT COUNT(*) FROM name_suggestions WHERE status='pending')+(SELECT COUNT(*) FROM photo_submissions WHERE status='pending')").fetchone()[0]
    if pending >= MAX_PENDING: flash('The review queue is full right now. Please try again later.', 'error'); return None
    _hits[ip].append(now)
    return name

def _back(name): return redirect(url_for('driver', name=name))

def submit_name():
    name = _guard()
    if name is None: return redirect(request.referrer or url_for('home'))
    sug = ' '.join(request.form.get('suggested', '').split())
    if not (2 <= len(sug) <= 60) or not re.fullmatch(r"[\w .'\-]+", sug):
        flash('Please enter a name of 2 to 60 characters (letters, spaces, . \' - only).', 'error'); return _back(name)
    if sug != name and not adb().execute("SELECT 1 FROM name_suggestions WHERE driver_name=? AND suggested=? AND status='pending'", (name, sug)).fetchone():
        adb().execute("INSERT INTO name_suggestions(driver_name, suggested) VALUES(?,?)", (name, sug)); adb().commit()
    flash('Thanks! Your suggestion will appear once it has been reviewed.')
    return _back(name)

def submit_photo():
    name = _guard()
    if name is None: return redirect(request.referrer or url_for('home'))
    f = request.files.get('photo'); data = f.read(MAX_BYTES + 1) if f else b''
    if not data or len(data) > MAX_BYTES: flash('Please choose an image under 5 MB.', 'error'); return _back(name)
    jpg = process_image(data)
    if jpg is None: flash('That file is not a valid JPG, PNG or WebP image.', 'error'); return _back(name)
    os.makedirs(config.PENDING_DIR, exist_ok=True)
    fn = secrets.token_hex(12) + '.jpg'
    with open(os.path.join(config.PENDING_DIR, fn), 'wb') as fh: fh.write(jpg)
    adb().execute("INSERT INTO photo_submissions(driver_name, filename) VALUES(?,?)", (name, fn)); adb().commit()
    flash('Thanks! Your photo will appear once it has been reviewed.')
    return _back(name)
