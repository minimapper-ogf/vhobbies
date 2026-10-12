"""Village Hobbies Racing - race day importer.
Parses a LiveTime export folder (the /html files) into SQLite + CSV.
Usable from the admin panel or from the command line:
    python importer.py "7 SEP 2026" oval|offroad [YYYY-MM-DD]
"""
import os, re, csv, html, sqlite3, glob, sys
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS race_days(
  id INTEGER PRIMARY KEY, race_date TEXT, label TEXT, day_type TEXT CHECK(day_type IN ('oval','offroad')), UNIQUE(race_date, day_type));
CREATE TABLE IF NOT EXISTS results(           -- one row per driver per heat/final (from h*r* and f*r* files)
  id INTEGER PRIMARY KEY, day_id INTEGER REFERENCES race_days(id) ON DELETE CASCADE,
  class_name TEXT, stage TEXT,                -- stage: 'heat' or 'final'
  heat_no INTEGER, round_no INTEGER, final_group TEXT,   -- final_group: 'A','B' (finals only)
  raw_name TEXT, car_no INTEGER, position INTEGER, laps INTEGER,
  total_time REAL, fastest_lap REAL, avg_lap REAL);
CREATE TABLE IF NOT EXISTS laps(              -- one row per lap
  id INTEGER PRIMARY KEY, result_id INTEGER REFERENCES results(id) ON DELETE CASCADE,
  lap_no INTEGER, lap_time REAL);
CREATE TABLE IF NOT EXISTS eor_results(       -- end-of-round standings (eor files)
  id INTEGER PRIMARY KEY, day_id INTEGER REFERENCES race_days(id) ON DELETE CASCADE,
  eor_x INTEGER, eor_y INTEGER, class_name TEXT, position INTEGER,
  raw_name TEXT, laps INTEGER, total_time REAL, best_round INTEGER);
CREATE TABLE IF NOT EXISTS name_map(raw_name TEXT PRIMARY KEY, full_name TEXT NOT NULL);   -- approved name edits
CREATE TABLE IF NOT EXISTS news(id INTEGER PRIMARY KEY, title TEXT, body TEXT, image TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS news_images(id INTEGER PRIMARY KEY, news_id INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE, image TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS track_events(id INTEGER PRIMARY KEY, event_date TEXT, title TEXT, description TEXT, day_type TEXT);
CREATE TABLE IF NOT EXISTS site_content(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS name_suggestions(id INTEGER PRIMARY KEY, driver_name TEXT, suggested TEXT, status TEXT DEFAULT 'pending', created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS photo_submissions(id INTEGER PRIMARY KEY, driver_name TEXT, filename TEXT, status TEXT DEFAULT 'pending', created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS driver_photos(driver_name TEXT PRIMARY KEY, filename TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_res_day ON results(day_id);
CREATE INDEX IF NOT EXISTS ix_res_name ON results(raw_name);
CREATE INDEX IF NOT EXISTS ix_laps_res ON laps(result_id);
"""

def init_db(path):
    db = sqlite3.connect(path); db.execute("PRAGMA foreign_keys=ON"); db.executescript(SCHEMA); return db

def secs(s):
    """'5m17.490' -> 317.49 ; '35.277' -> 35.277 ; ''/'NO TIME' -> None"""
    s = (s or '').strip()
    m = re.fullmatch(r'(?:(\d+)m)?(\d+(?:\.\d+)?)', s)
    if not m: return None
    return (int(m.group(1) or 0) * 60) + float(m.group(2))

def tables(path):
    t = open(path, encoding='cp1252', errors='replace').read()
    caps = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<CAPTION[^>]*>(.*?)</CAPTION>', t, re.S | re.I)]
    h2 = re.sub(r'<[^>]+>', '', (re.findall(r'<H2[^>]*>(.*?)</H2>', t, re.S | re.I) or [''])[0]).strip()
    out = []
    for tb in re.findall(r'<TABLE.*?</TABLE>', t, re.S | re.I):
        rows = []
        for tr in re.findall(r'<TR>(.*?)</TR>', tb, re.S | re.I):
            rows.append([html.unescape(re.sub(r'<[^>]+>', '', c)).strip() for c in re.findall(r'<TD[^>]*>(.*?)</TD>', tr, re.S | re.I)])
        if rows and rows[0] and rows[0][0] in ('Position', 'Lap'):
            out.append(rows)
    return h2, caps, out

def import_day(db, folder, day_type, race_date=None, label=None):
    hdir = os.path.join(folder, 'html')
    if race_date is None:   # 1) try the folder name, e.g. "7 SEP 2026"
        try:
            race_date = datetime.strptime(os.path.basename(folder.rstrip('/\\')).strip().title(), '%d %b %Y').strftime('%Y-%m-%d')
        except ValueError:
            race_date = None
    if race_date is None:   # 2) fall back to newest file's date
        newest = max(os.path.getmtime(f) for f in glob.glob(os.path.join(hdir, '*.html')))
        race_date = datetime.fromtimestamp(newest).strftime('%Y-%m-%d')
    if db.execute("SELECT 1 FROM race_days WHERE race_date=? AND day_type=?", (race_date, day_type)).fetchone():
        raise ValueError(f"A {day_type} race day for {race_date} already exists. Delete it first to re-import.")
    cur = db.execute("INSERT INTO race_days(race_date,label,day_type) VALUES(?,?,?)",
                     (race_date, label or os.path.basename(folder.rstrip('/\\')), day_type))
    day_id = cur.lastrowid
    n_res = n_laps = n_eor = 0
    for f in sorted(os.listdir(hdir)):
        low = f.lower(); p = os.path.join(hdir, f)
        m = re.fullmatch(r'([hf])(\d+)r(\d+)\.html', low)
        if m:
            h2, caps, tbs = tables(p)
            cls = h2.split('Round:')[1].split(' ', 1)[1].strip()
            stage = 'final' if m.group(1) == 'f' else 'heat'
            grp = (re.search(r'(A|B) Final', h2) or [None, None])[1]
            heat_no = int(m.group(2)) if stage == 'heat' else None
            rnd = int(m.group(3))
            res, lapt = tbs[0], tbs[1] if len(tbs) > 1 else []
            ids = {}
            for r in res[1:]:
                if len(r) < 7: continue
                pos, car, name, laps, tt, fl, av = r[:7]
                c = db.execute("INSERT INTO results(day_id,class_name,stage,heat_no,round_no,final_group,raw_name,car_no,position,laps,total_time,fastest_lap,avg_lap) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (day_id, cls, stage, heat_no, rnd, grp, name.strip(), int(car), int(pos), int(laps or 0), secs(tt), secs(fl) or None, secs(av)))
                ids[int(car)] = c.lastrowid; n_res += 1
            if lapt:
                hdr = lapt[0]
                for r in lapt[1:]:
                    for i, v in enumerate(r[1:], start=1):
                        mm = re.search(r'(\d+)$', hdr[i]) if i < len(hdr) else None
                        if mm and v and int(mm.group(1)) in ids:
                            db.execute("INSERT INTO laps(result_id,lap_no,lap_time) VALUES(?,?,?)", (ids[int(mm.group(1))], int(r[0]), secs(v))); n_laps += 1
            continue
        m = re.fullmatch(r'eor(\d+)_(\d+)\.html', low)
        if m:
            h2, caps, tbs = tables(p)
            caps = [c for c in caps if c.startswith('Class:')]
            for cap, tb in zip(caps, tbs):
                cls = re.sub(r'^Class:\((.*)\)$', r'\1', cap)
                for r in tb:
                    if len(r) >= 5 and r[0].isdigit():
                        db.execute("INSERT INTO eor_results(day_id,eor_x,eor_y,class_name,position,raw_name,laps,total_time,best_round) VALUES(?,?,?,?,?,?,?,?,?)",
                            (day_id, int(m.group(1)), int(m.group(2)), cls, int(r[0]), r[1], int(r[2]), secs(r[3]), int(r[4]))); n_eor += 1
    db.commit()
    return day_id, race_date, n_res, n_laps, n_eor

def export_csv(db, day_id, outdir):
    os.makedirs(outdir, exist_ok=True)
    for name, q in {
        'results': "SELECT * FROM results WHERE day_id=?",
        'laps': "SELECT l.*, r.class_name, r.stage, r.heat_no, r.round_no, r.final_group, r.raw_name FROM laps l JOIN results r ON r.id=l.result_id WHERE r.day_id=?",
        'eor_results': "SELECT * FROM eor_results WHERE day_id=?"}.items():
        cur = db.execute(q, (day_id,))
        with open(os.path.join(outdir, name + '.csv'), 'w', newline='') as fh:
            w = csv.writer(fh); w.writerow([d[0] for d in cur.description]); w.writerows(cur)

if __name__ == '__main__':
    folder, kind = sys.argv[1], sys.argv[2]
    date = sys.argv[3] if len(sys.argv) > 3 else None
    db = init_db(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'vhr.db'))
    did, d, a, b, c = import_day(db, folder, kind, date)
    print(f"Imported day {d}: {a} results, {b} laps, {c} end-of-round rows")
    export_csv(db, did, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', f'csv_{d}'))
