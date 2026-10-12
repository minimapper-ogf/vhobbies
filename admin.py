"""Admin panel. Add new admin pages by writing a route here and adding it to SECTIONS."""
import os, re, sqlite3, tempfile, zipfile, hmac, secrets, time, shutil
from datetime import datetime
from functools import wraps
from pathlib import PurePosixPath
from flask import send_from_directory, Blueprint, render_template, request, redirect, url_for, session, flash, abort, g
import config, importer
from images import save_public_image, delete_public_image

bp = Blueprint('admin', __name__, url_prefix='/admin')
SECTIONS = [('admin.dashboard', 'Dashboard'), ('admin.days', 'Race days'), ('admin.approvals', 'Approvals'), ('admin.names', 'Driver names'), ('admin.news', 'News'), ('admin.events', 'Track events'), ('admin.home', 'Home page')]   # later parts append here

def adb():
    if 'adb' not in g:
        g.adb = sqlite3.connect(config.DB_PATH); g.adb.row_factory = sqlite3.Row
        g.adb.execute("PRAGMA foreign_keys=ON")
    return g.adb

def init(app):
    app.register_blueprint(bp)
    @app.teardown_appcontext
    def _c(e):
        d = g.pop('adb', None)
        if d: d.close()

def configured():
    return config.ADMIN_PASSWORD != 'change-me' and config.SECRET_KEY != 'put-a-long-random-string-here'

def admin_accounts():
    accounts = [(config.ADMIN_USERNAME, config.ADMIN_PASSWORD)]
    username = getattr(config, 'ADMIN_USERNAME_2', '')
    password = getattr(config, 'ADMIN_PASSWORD_2', '')
    if username and password: accounts.append((username, password))
    return accounts

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get('admin'): return redirect(url_for('admin.login'))
        return f(*a, **k)
    return w

def token():
    if 'csrf' not in session: session['csrf'] = secrets.token_hex(16)
    return session['csrf']

@bp.before_request
def csrf_check():
    if request.method == 'POST':
        if not hmac.compare_digest(request.form.get('csrf', ''), session.get('csrf', 'x')): abort(400, 'Bad or expired form. Go back, refresh, and try again.')

@bp.context_processor
def ctx():
    n = 0
    if session.get('admin'):
        n = adb().execute("SELECT (SELECT COUNT(*) FROM name_suggestions WHERE status='pending')+(SELECT COUNT(*) FROM photo_submissions WHERE status='pending')").fetchone()[0]
    return dict(csrf=token(), sections=SECTIONS, current=request.endpoint, pending_count=n)

# ---- login ----
_fails = {}
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('admin'): return redirect(url_for('admin.dashboard'))
    ip = request.remote_addr or '?'
    f = _fails.get(ip, [0, 0])
    if request.method == 'POST':
        if not configured():
            flash('Admin is disabled until you change ADMIN_PASSWORD and SECRET_KEY in config.py.', 'error')
        elif f[0] >= 5 and time.time() < f[1]:
            flash('Too many attempts. Try again in a few minutes.', 'error')
        else:
            username, password = request.form.get('username', ''), request.form.get('password', '')
            ok = any(hmac.compare_digest(username, u) & hmac.compare_digest(password, p) for u, p in admin_accounts())
            if ok:
                _fails.pop(ip, None); session.clear(); session['admin'] = True; session.permanent = True
                return redirect(url_for('admin.dashboard'))
            _fails[ip] = [f[0] + 1, time.time() + 300]
            flash('Wrong username or password.', 'error')
    return render_template('admin/login.html', configured=configured())

@bp.route('/logout', methods=['POST'])
def logout():
    session.clear(); flash('Logged out.'); return redirect(url_for('home'))

# ---- dashboard ----
@bp.route('/')
@login_required
def dashboard():
    one = lambda sql: adb().execute(sql).fetchone()[0]
    stats = dict(days=one("SELECT COUNT(*) FROM race_days"), results=one("SELECT COUNT(*) FROM results"), laps=one("SELECT COUNT(*) FROM laps"),
                 drivers=one("SELECT COUNT(DISTINCT COALESCE(nm.full_name, r.raw_name)) FROM results r LEFT JOIN name_map nm ON nm.raw_name=r.raw_name"))
    return render_template('admin/dashboard.html', stats=stats)

# ---- race days ----
def guess_date(*names):
    for n in names:
        if not n: continue
        n = re.sub(r'\.zip$', '', n, flags=re.I).replace('_', ' ').replace('-', ' ').strip()
        for fmt in ('%d %b %Y', '%d %B %Y', '%Y %m %d', '%m %d %Y'):
            try: return datetime.strptime(n.title(), fmt).strftime('%Y-%m-%d')
            except ValueError: pass
    return None

def extract_html(zf, dest):
    """Copy only *.html files that sit in a folder named 'html' into dest/html. Returns (count, top folder name)."""
    os.makedirs(os.path.join(dest, 'html'), exist_ok=True)
    n, top = 0, None
    for info in zf.infolist():
        parts = PurePosixPath(info.filename.replace('\\', '/')).parts
        if info.is_dir() or '..' in parts or len(parts) < 2: continue
        if parts[-2].lower() == 'html' and parts[-1].lower().endswith('.html') and info.file_size < 2_000_000:
            with zf.open(info) as src, open(os.path.join(dest, 'html', os.path.basename(parts[-1])), 'wb') as out: shutil.copyfileobj(src, out)
            n += 1
            if len(parts) > 2: top = top or parts[0]
    return n, top

@bp.route('/days')
@login_required
def days():
    rows = adb().execute("""SELECT d.*, (SELECT COUNT(*) FROM results r WHERE r.day_id=d.id) AS results,
                            (SELECT COUNT(DISTINCT class_name) FROM results r WHERE r.day_id=d.id) AS classes FROM race_days d ORDER BY race_date DESC""").fetchall()
    return render_template('admin/days.html', rows=rows)

@bp.route('/days/upload', methods=['POST'])
@login_required
def upload_day():
    f = request.files.get('zipfile'); kind = request.form.get('day_type'); date = request.form.get('race_date', '').strip()
    if not f or not f.filename.lower().endswith('.zip'): flash('Please choose a .zip of the race day folder.', 'error'); return redirect(url_for('admin.days'))
    if kind not in ('oval', 'offroad'): flash('Pick Oval or Offroad.', 'error'); return redirect(url_for('admin.days'))
    tmp = tempfile.mkdtemp()
    try:
        try: zf = zipfile.ZipFile(f.stream)
        except zipfile.BadZipFile: flash('That file is not a valid zip.', 'error'); return redirect(url_for('admin.days'))
        n, top = extract_html(zf, tmp)
        if n == 0: flash('No race result files found. The zip needs the folder with the "html" subfolder inside it.', 'error'); return redirect(url_for('admin.days'))
        date = date or guess_date(f.filename, top)
        if not date: flash('Could not work out the date from the file name. Please enter it.', 'error'); return redirect(url_for('admin.days'))
        try: datetime.strptime(date, '%Y-%m-%d')
        except ValueError: flash('Date must look like 2026-09-07.', 'error'); return redirect(url_for('admin.days'))
        try:
            _, d, a, b, c = importer.import_day(adb(), tmp, kind, date, label=top or re.sub(r'\.zip$', '', f.filename, flags=re.I))
        except ValueError as e: flash(str(e), 'error'); return redirect(url_for('admin.days'))
        except Exception as e: adb().rollback(); flash(f'Import failed, nothing was saved: {e}', 'error'); return redirect(url_for('admin.days'))
        flash(f'Imported {kind} day {d}: {a} results, {b} laps, {c} standings rows.')
    finally: shutil.rmtree(tmp, ignore_errors=True)
    return redirect(url_for('admin.days'))

@bp.route('/days/<int:did>/edit', methods=['POST'])
@login_required
def edit_day(did):
    kind = request.form.get('day_type'); date = request.form.get('race_date', '').strip()
    try:
        datetime.strptime(date, '%Y-%m-%d'); assert kind in ('oval', 'offroad')
        adb().execute("UPDATE race_days SET race_date=?, day_type=? WHERE id=?", (date, kind, did)); adb().commit(); flash('Race day updated.')
    except sqlite3.IntegrityError: flash('A race day of that type already exists on that date.', 'error')
    except (ValueError, AssertionError): flash('Enter a valid date (2026-09-07) and type.', 'error')
    return redirect(url_for('admin.days'))

@bp.route('/days/<int:did>/delete', methods=['POST'])
@login_required
def delete_day(did):
    adb().execute("DELETE FROM race_days WHERE id=?", (did,)); adb().commit(); flash('Race day deleted.')
    return redirect(url_for('admin.days'))

# ---- approvals: name suggestions + photos ----
def display_names_for(display):
    """All raw timing names that currently show as this display name."""
    rows = adb().execute("""SELECT r.raw_name FROM results r LEFT JOIN name_map nm ON nm.raw_name=r.raw_name WHERE COALESCE(nm.full_name, r.raw_name)=?
                            UNION SELECT e.raw_name FROM eor_results e LEFT JOIN name_map nm ON nm.raw_name=e.raw_name WHERE COALESCE(nm.full_name, e.raw_name)=?""", (display, display)).fetchall()
    return [r[0] for r in rows]

def rename_driver(old, new):
    """Point every raw name currently shown as `old` at `new` (merges if `new` already exists), carrying photo + pending items along."""
    db = adb()
    for raw in display_names_for(old): db.execute("INSERT OR REPLACE INTO name_map(raw_name, full_name) VALUES(?,?)", (raw, new))
    if old != new:
        if db.execute("SELECT 1 FROM driver_photos WHERE driver_name=?", (new,)).fetchone(): db.execute("DELETE FROM driver_photos WHERE driver_name=?", (old,))
        else: db.execute("UPDATE driver_photos SET driver_name=? WHERE driver_name=?", (new, old))
        db.execute("UPDATE photo_submissions SET driver_name=? WHERE driver_name=? AND status='pending'", (new, old))
        db.execute("UPDATE name_suggestions SET driver_name=? WHERE driver_name=? AND status='pending'", (new, old))

@bp.route('/approvals')
@login_required
def approvals():
    db = adb()
    names = []
    for s in db.execute("SELECT * FROM name_suggestions WHERE status='pending' ORDER BY created"):
        exists = db.execute("SELECT COUNT(DISTINCT day_id) FROM results r LEFT JOIN name_map nm ON nm.raw_name=r.raw_name WHERE COALESCE(nm.full_name, r.raw_name)=?", (s['suggested'],)).fetchone()[0]
        names.append(dict(s, merge_days=exists))
    photos = []
    for p in db.execute("SELECT * FROM photo_submissions WHERE status='pending' ORDER BY created"):
        cur = db.execute("SELECT filename FROM driver_photos WHERE driver_name=?", (p['driver_name'],)).fetchone()
        photos.append(dict(p, current=cur[0] if cur else None))
    current = db.execute("SELECT * FROM driver_photos ORDER BY driver_name").fetchall()
    return render_template('admin/approvals.html', names=names, photos=photos, current=current)

@bp.route('/pending-photo/<fn>')
@login_required
def pending_photo(fn):
    if not re.fullmatch(r'[0-9a-f]{24}\.jpg', fn): abort(404)
    return send_from_directory(config.PENDING_DIR, fn)

def _remove_file(folder, fn):
    try: os.remove(os.path.join(folder, fn))
    except OSError: pass

@bp.route('/approvals/name/<int:sid>/<action>', methods=['POST'])
@login_required
def decide_name(sid, action):
    s = adb().execute("SELECT * FROM name_suggestions WHERE id=? AND status='pending'", (sid,)).fetchone()
    if not s or action not in ('approve', 'deny'): abort(404)
    if action == 'approve':
        rename_driver(s['driver_name'], s['suggested'])
        flash(f"Approved: {s['driver_name']} is now shown as {s['suggested']}.")
    else: flash('Name suggestion denied.')
    adb().execute("UPDATE name_suggestions SET status=? WHERE id=?", ('approved' if action == 'approve' else 'denied', sid)); adb().commit()
    return redirect(url_for('admin.approvals'))

@bp.route('/approvals/photo/<int:pid>/<action>', methods=['POST'])
@login_required
def decide_photo(pid, action):
    db = adb(); p = db.execute("SELECT * FROM photo_submissions WHERE id=? AND status='pending'", (pid,)).fetchone()
    if not p or action not in ('approve', 'deny'): abort(404)
    src = os.path.join(config.PENDING_DIR, p['filename'])
    if action == 'approve':
        dest_dir = os.path.join(config.UPLOAD_DIR, 'drivers'); os.makedirs(dest_dir, exist_ok=True)
        old = db.execute("SELECT filename FROM driver_photos WHERE driver_name=?", (p['driver_name'],)).fetchone()
        if old: _remove_file(dest_dir, old[0])
        os.replace(src, os.path.join(dest_dir, p['filename']))
        db.execute("INSERT OR REPLACE INTO driver_photos(driver_name, filename) VALUES(?,?)", (p['driver_name'], p['filename']))
        flash(f"Photo approved for {p['driver_name']}.")
    else:
        _remove_file(config.PENDING_DIR, p['filename']); flash('Photo denied and deleted.')
    db.execute("UPDATE photo_submissions SET status=? WHERE id=?", ('approved' if action == 'approve' else 'denied', pid)); db.commit()
    return redirect(url_for('admin.approvals'))

@bp.route('/photos/remove', methods=['POST'])
@login_required
def remove_photo():
    name = request.form.get('driver_name', ''); row = adb().execute("SELECT filename FROM driver_photos WHERE driver_name=?", (name,)).fetchone()
    if row:
        _remove_file(os.path.join(config.UPLOAD_DIR, 'drivers'), row[0]); adb().execute("DELETE FROM driver_photos WHERE driver_name=?", (name,)); adb().commit(); flash('Photo removed.')
    return redirect(url_for('admin.approvals'))

# ---- driver names (direct edit, no approval needed because you are the admin) ----
@bp.route('/names')
@login_required
def names():
    rows = adb().execute("""SELECT r.raw_name, nm.full_name, COUNT(DISTINCT r.day_id) days FROM results r LEFT JOIN name_map nm ON nm.raw_name=r.raw_name
                            GROUP BY r.raw_name ORDER BY r.raw_name COLLATE NOCASE""").fetchall()
    return render_template('admin/names.html', rows=rows)

@bp.route('/names/save', methods=['POST'])
@login_required
def save_name():
    raw = request.form.get('raw_name', ''); full = ' '.join(request.form.get('full_name', '').split())
    if not adb().execute("SELECT 1 FROM results WHERE raw_name=? LIMIT 1", (raw,)).fetchone(): abort(404)
    if full and not re.fullmatch(r"[\w .'\-]{2,60}", full): flash('Names can be 2-60 letters, spaces, . \' -', 'error')
    else:
        old = adb().execute("SELECT COALESCE(nm.full_name, ?) FROM (SELECT 1) LEFT JOIN name_map nm ON nm.raw_name=?", (raw, raw)).fetchone()[0]
        if full: adb().execute("INSERT OR REPLACE INTO name_map(raw_name, full_name) VALUES(?,?)", (raw, full))
        else: adb().execute("DELETE FROM name_map WHERE raw_name=?", (raw,))
        adb().commit(); flash(f'{raw} now shows as {full or raw}.')
    return redirect(url_for('admin.names') + '#' + re.sub(r'\W', '_', raw))

# ---- news ----
def _valid_date(s):
    try: datetime.strptime(s, '%Y-%m-%d'); return True
    except ValueError: return False

@bp.route('/news')
@login_required
def news():
    edit = None
    if request.args.get('edit', '').isdigit():
        edit = adb().execute("SELECT * FROM news WHERE id=?", (int(request.args['edit']),)).fetchone()
        if edit:
            edit = dict(edit, images=[r['image'] for r in adb().execute('SELECT image FROM news_images WHERE news_id=? ORDER BY id', (edit['id'],))] or ([edit['image']] if edit['image'] else []))
    posts = adb().execute("SELECT * FROM news ORDER BY created DESC").fetchall()
    posts = [dict(p, images=[r['image'] for r in adb().execute('SELECT image FROM news_images WHERE news_id=? ORDER BY id', (p['id'],))] or ([p['image']] if p['image'] else [])) for p in posts]
    return render_template('admin/news.html', posts=posts, edit=edit, today=datetime.now().strftime('%Y-%m-%d'))

@bp.route('/news/save', methods=['POST'])
@login_required
def save_news():
    db = adb(); nid = request.form.get('id', ''); title = request.form.get('title', '').strip(); body = request.form.get('body', '').strip()
    date = request.form.get('date', '').strip(); files = [f for f in request.files.getlist('images') if f and f.filename]
    back = url_for('admin.news', edit=nid) if nid else url_for('admin.news')
    if not title or len(title) > 120 or len(body) > 10000 or not _valid_date(date):
        flash('A title (up to 120 characters) and a valid date are required.', 'error'); return redirect(back)
    old = db.execute("SELECT * FROM news WHERE id=?", (nid,)).fetchone() if nid.isdigit() else None
    image = old['image'] if old else None
    original_images = [r['image'] for r in db.execute('SELECT image FROM news_images WHERE news_id=? ORDER BY id', (old['id'],))] if old else ([image] if image else [])
    existing_images = [] if old and request.form.get('remove_image') else (original_images or ([image] if image else []))
    added = []
    try:
        for f in files: added.append(save_public_image(f, 'news'))
    except ValueError as e:
        for uploaded in added: delete_public_image(uploaded)
        flash(str(e), 'error'); return redirect(back)
    all_images = existing_images + added
    image = all_images[0] if all_images else None
    if old:
        created = old['created'] if old['created'][:10] == date else date + ' 12:00:00'
        db.execute("UPDATE news SET title=?, body=?, image=?, created=? WHERE id=?", (title, body, image, created, old['id']))
        db.execute('DELETE FROM news_images WHERE news_id=?', (old['id'],))
        db.executemany('INSERT INTO news_images(news_id,image) VALUES(?,?)', [(old['id'], p) for p in all_images]); flash('News post updated.')
    else:
        cur = db.execute("INSERT INTO news(title, body, image, created) VALUES(?,?,?,?)", (title, body, image, date + ' ' + datetime.now().strftime('%H:%M:%S')))
        db.executemany('INSERT INTO news_images(news_id,image) VALUES(?,?)', [(cur.lastrowid, p) for p in all_images]); flash('News post published.')
    for removed in set(original_images) - set(all_images): delete_public_image(removed)
    db.commit(); return redirect(url_for('admin.news'))

@bp.route('/news/<int:nid>/delete', methods=['POST'])
@login_required
def delete_news(nid):
    db = adb(); row = db.execute("SELECT image FROM news WHERE id=?", (nid,)).fetchone()
    if row:
        images = [r['image'] for r in db.execute('SELECT image FROM news_images WHERE news_id=?', (nid,))] or ([row['image']] if row['image'] else [])
        for image in images: delete_public_image(image)
        db.execute("DELETE FROM news WHERE id=?", (nid,)); db.commit(); flash('News post deleted.')
    return redirect(url_for('admin.news'))

# ---- track events (shown as markers on charts) ----
@bp.route('/events')
@login_required
def events():
    edit = None
    if request.args.get('edit', '').isdigit(): edit = adb().execute("SELECT * FROM track_events WHERE id=?", (int(request.args['edit']),)).fetchone()
    rows = adb().execute("SELECT * FROM track_events ORDER BY event_date DESC").fetchall()
    return render_template('admin/events.html', rows=rows, edit=edit, today=datetime.now().strftime('%Y-%m-%d'))

@bp.route('/events/save', methods=['POST'])
@login_required
def save_event():
    eid = request.form.get('id', ''); date = request.form.get('event_date', '').strip(); title = request.form.get('title', '').strip()
    desc = request.form.get('description', '').strip(); kind = request.form.get('day_type') if request.form.get('day_type') in ('oval', 'offroad') else None
    if not title or len(title) > 60 or len(desc) > 2000 or not _valid_date(date):
        flash('A short title (up to 60 characters) and a valid date are required.', 'error'); return redirect(url_for('admin.events', edit=eid) if eid else url_for('admin.events'))
    if eid.isdigit(): adb().execute("UPDATE track_events SET event_date=?, title=?, description=?, day_type=? WHERE id=?", (date, title, desc, kind, int(eid))); flash('Track event updated.')
    else: adb().execute("INSERT INTO track_events(event_date, title, description, day_type) VALUES(?,?,?,?)", (date, title, desc, kind)); flash('Track event added. It now shows on driver charts.')
    adb().commit(); return redirect(url_for('admin.events'))

@bp.route('/events/<int:eid>/delete', methods=['POST'])
@login_required
def delete_event(eid):
    adb().execute("DELETE FROM track_events WHERE id=?", (eid,)); adb().commit(); flash('Track event deleted.'); return redirect(url_for('admin.events'))

# ---- home page ----
HOME_TEXT = ('home_title', 'home_intro', 'home_info')

@bp.route('/home', methods=['GET', 'POST'])
@login_required
def home():
    db = adb()
    get = lambda k, d='': (db.execute("SELECT value FROM site_content WHERE key=?", (k,)).fetchone() or [d])[0]
    if request.method == 'POST':
        for k in HOME_TEXT: db.execute("INSERT OR REPLACE INTO site_content(key, value) VALUES(?,?)", (k, request.form.get(k, '').strip()[:5000]))
        for i in (1,):
            key = f'home_photo_{i}'; f = request.files.get('photo'); old = get(key)
            try:
                if f and f.filename:
                    new = save_public_image(f, 'home'); delete_public_image(old); db.execute("INSERT OR REPLACE INTO site_content(key, value) VALUES(?,?)", (key, new))
                elif request.form.get(f'remove{i}') and old:
                    delete_public_image(old); db.execute("DELETE FROM site_content WHERE key=?", (key,))
            except ValueError as e: flash(f'Photo {i}: {e}', 'error')
        db.commit(); flash('Home page saved.'); return redirect(url_for('admin.home'))
    vals = {k: get(k) for k in HOME_TEXT + ('home_photo_1',)}
    return render_template('admin/home.html', v=vals)
