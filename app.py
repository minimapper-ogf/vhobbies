import os, statistics
from datetime import date
from flask import Flask, g, session, render_template, request, jsonify, abort
import config, importer
from race_stats import RESULT_NAME as NAME, RESULT_JOIN as JOIN, EOR_NAME, EOR_JOIN
from race_stats import best_lap, lap_minimums, valid_lap

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config.update(MAX_CONTENT_LENGTH=50 * 1024 * 1024, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_HTTPONLY=True,
                  PERMANENT_SESSION_LIFETIME=12 * 3600)
os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
importer.init_db(config.DB_PATH).close()          # auto-creates the database on first run

import sqlite3
def db():
    if 'db' not in g:
        g.db = sqlite3.connect(config.DB_PATH); g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def _close(e):
    d = g.pop('db', None)
    if d: d.close()
def q(sql, args=()): return db().execute(sql, args).fetchall()

@app.template_filter('t')
def fmt_time(s):
    if s is None: return '-'
    m, sec = divmod(s, 60)
    return f"{int(m)}m{sec:06.3f}" if m else f"{sec:.3f}"
@app.template_filter('lap')
def fmt_lap(s): return '-' if s is None else f"{s:.3f}"
@app.context_processor
def inject(): return dict(cfg=config, csrf_token=lambda: admin.token(), is_admin=bool(session.get('admin')), content=lambda k, d='': (q("SELECT value FROM site_content WHERE key=?", (k,)) or [{'value': d}])[0]['value'])

# ---------- public pages ----------
@app.route('/')
def home():
    news = q("SELECT * FROM news ORDER BY created DESC LIMIT 3")
    news = [dict(n, images=[r['image'] for r in q('SELECT image FROM news_images WHERE news_id=? ORDER BY id', (n['id'],))] or ([n['image']] if n['image'] else [])) for n in news]
    return render_template('home.html', news=news)

@app.route('/news')
def news():
    items = q("SELECT * FROM news ORDER BY created DESC")
    items = [dict(n, images=[r['image'] for r in q('SELECT image FROM news_images WHERE news_id=? ORDER BY id', (n['id'],))] or ([n['image']] if n['image'] else [])) for n in items]
    return render_template('news.html', items=items)

@app.route('/history')
def history():
    kind = request.args.get('type', 'offroad')
    if kind not in ('oval', 'offroad'): kind = 'offroad'
    days = []
    for d in q("SELECT * FROM race_days WHERE day_type=? ORDER BY race_date DESC", (kind,)):
        winners = q(f"""SELECT r.class_name, {NAME} AS name FROM results r {JOIN}
                        WHERE r.day_id=? AND r.stage='final' AND r.position=1 AND r.final_group='A' ORDER BY r.class_name""", (d['id'],))
        drivers = q(f"SELECT COUNT(DISTINCT {NAME}) c FROM results r {JOIN} WHERE r.day_id=?", (d['id'],))[0]['c']
        days.append(dict(d, winners=winners, drivers=drivers))
    events = q("SELECT * FROM track_events WHERE day_type IS NULL OR day_type='' OR day_type=? ORDER BY event_date DESC", (kind,))
    return render_template('history.html', days=days, kind=kind, events=events)

def day_runs(did, cls):
    return q(f"""SELECT r.*, {NAME} AS name FROM results r {JOIN}
                 WHERE r.day_id=? AND r.class_name=?""", (did, cls))


def day_laps(did, cls):
    rows = q("""SELECT l.result_id, l.lap_no, l.lap_time FROM laps l
                JOIN results r ON r.id=l.result_id WHERE r.day_id=? AND r.class_name=?
                ORDER BY l.lap_no""", (did, cls))
    laps = {}
    for row in rows:
        laps.setdefault(row['result_id'], []).append(row)
    return laps


def run_times(run, recorded, minimum):
    timed = [lap['lap_time'] for lap in recorded if lap['lap_time'] is not None]
    valid = [value for value in timed if valid_lap(value, minimum)]
    reported = run['fastest_lap']
    reported_best = reported if valid_lap(reported, minimum) else None
    best = best_lap(valid, reported_best)
    avg = _mean(valid)
    summary_usable = reported in (None, 0) or reported_best is not None
    if len(valid) == len(timed) and summary_usable and valid_lap(run['avg_lap'], minimum):
        avg = run['avg_lap']
    return len(timed), valid, best, avg


def day_data(did, cls, minimum):
    """Everything for one class on one day, one dict per driver."""
    rows = day_runs(did, cls)
    laps = day_laps(did, cls)
    eor = q(f"""SELECT e.*, {EOR_NAME} AS name FROM eor_results e {EOR_JOIN}
                WHERE e.day_id=? AND e.class_name=?""", (did, cls))
    top_y = max([e['eor_y'] for e in eor], default=0)
    last = [e for e in eor if e['eor_y'] == top_y]
    final_x = max([e['eor_x'] for e in last], default=0); qual_x = min([e['eor_x'] for e in last], default=0)
    final_pos = {e['name']: e for e in last if e['eor_x'] == final_x}
    qual_pos = {e['name']: e for e in last if e['eor_x'] == qual_x}
    drivers = {}
    for r in rows:
        d = drivers.setdefault(r['name'], dict(name=r['name'], rounds={}, final=None,
                                              all_laps=0, valid_laps=[], best_times=[]))
        lap_count, valid, best, avg = run_times(r, laps.get(r['id'], ()), minimum)
        d['all_laps'] += lap_count
        d['valid_laps'].extend(valid)
        if best is not None:
            d['best_times'].append(best)
        run = dict(r, fastest_lap=best, avg_lap=avg)
        if r['stage'] == 'final': d['final'] = run
        else: d['rounds'][r['round_no']] = run
    for n, d in drivers.items():
        L = d['valid_laps']
        d['avg'] = _mean(L)
        d['best'] = best_lap(d['best_times'])
        d['stdev'] = statistics.pstdev(L) if len(L) > 1 else None
        d['median'] = statistics.median(L) if L else None
        d['qual'] = qual_pos.get(n); d['fin'] = final_pos.get(n)
    order = sorted(drivers.values(), key=lambda d: (d['fin']['position'] if d['fin'] else 999, d['name']))
    rounds = sorted({r['round_no'] for r in rows if r['stage'] == 'heat'})
    return order, rounds

@app.route('/day/<int:did>')
def day(did):
    d = q("SELECT * FROM race_days WHERE id=?", (did,))
    if not d: abort(404)
    classes = [r['class_name'] for r in q("SELECT DISTINCT class_name FROM results WHERE day_id=? ORDER BY class_name", (did,))]
    cls = request.args.get('class', classes[0] if classes else '')
    if cls not in classes and classes: cls = classes[0]
    drivers, rounds = day_data(did, cls, lap_minimums(db())[d[0]['day_type']]) if classes else ([], [])
    return render_template('day.html', day=d[0], classes=classes, cls=cls, drivers=drivers, rounds=rounds)

METRICS = {'avg_lap': 'Average lap (s)', 'fastest_lap': 'Fastest lap (s)', 'total_time': 'Total time (s)', 'laps': 'Laps completed', 'position': 'Position'}

@app.route('/api/day/<int:did>/chart')
def chart(did):
    cls = request.args.get('class', ''); mode = request.args.get('mode', 'rounds')
    day = q("SELECT day_type FROM race_days WHERE id=?", (did,))
    minimum = lap_minimums(db()).get(day[0]['day_type'], 0) if day else 0
    rows = day_runs(did, cls)
    metric = request.args.get('metric', 'avg_lap')
    if metric not in METRICS: metric = 'avg_lap'
    laps = day_laps(did, cls) if mode == 'laps' or metric in ('avg_lap', 'fastest_lap') else {}
    if mode == 'laps':
        sel = request.args.get('round', 'final')
        round_no = request.args.get('round', type=int)
        series = {}
        for row in rows:
            if sel == 'final':
                matches = row['stage'] == 'final'
            else:
                matches = row['stage'] == 'heat' and row['round_no'] == round_no and round_no is not None
            recorded = laps.get(row['id'], ())
            if matches and recorded:
                points = series.setdefault(row['name'], {})
                for lap in recorded:
                    value = lap['lap_time']
                    points[lap['lap_no']] = value if valid_lap(value, minimum) else None
        n = max((max(v) for v in series.values()), default=0)
        return jsonify(categories=[str(i) for i in range(1, n + 1)], xTitle='Lap', yTitle='Lap time (s)', reversed=False,
                       series=[dict(name=k, data=[v.get(i) for i in range(1, n + 1)]) for k, v in sorted(series.items())])
    rounds = sorted({r['round_no'] for r in rows if r['stage'] == 'heat'})
    cats = [f"Round {i}" for i in rounds] + (['Final'] if any(r['stage'] == 'final' for r in rows) else [])
    series = {}
    for r in rows:
        key = 'Final' if r['stage'] == 'final' else f"Round {r['round_no']}"
        value = r[metric]
        if metric in ('avg_lap', 'fastest_lap'):
            _, _, best, avg = run_times(r, laps.get(r['id'], ()), minimum)
            value = avg if metric == 'avg_lap' else best
        elif metric == 'total_time':
            value = value or None
        series.setdefault(r['name'], {})[key] = value
    return jsonify(categories=cats, xTitle='', yTitle=METRICS[metric], reversed=(metric == 'position'),
                   series=[dict(name=k, data=[v.get(c) for c in cats]) for k, v in sorted(series.items())])


# ---------- drivers ----------
@app.route('/drivers')
def drivers():
    term = request.args.get('q', '').strip()
    like = f"%{term}%"
    minimums = lap_minimums(db())
    rows = q(f"""WITH driver_runs AS (
                     SELECT r.id, r.raw_name, r.day_id, r.class_name, d.day_type, r.fastest_lap,
                            {NAME} AS name, CASE d.day_type WHEN 'oval' THEN ? ELSE ? END AS minimum
                     FROM results r JOIN race_days d ON d.id=r.day_id {JOIN}
                 ), lap_candidates AS (
                     SELECT dr.*, (SELECT MIN(l.lap_time) FROM laps l WHERE l.result_id=dr.id
                                    AND l.lap_time>0 AND l.lap_time>=dr.minimum) AS recorded_best,
                            CASE WHEN fastest_lap>0 AND fastest_lap>=minimum THEN fastest_lap END AS reported_best
                     FROM driver_runs dr WHERE dr.name IN
                         (SELECT name FROM driver_runs WHERE name LIKE ? OR raw_name LIKE ?)
                 ), run_bests AS (
                     SELECT *, MIN(COALESCE(recorded_best, reported_best),
                                   COALESCE(reported_best, recorded_best)) AS best
                     FROM lap_candidates
                 )
                 SELECT name, COUNT(DISTINCT day_id) days, GROUP_CONCAT(DISTINCT class_name) classes,
                        MIN(CASE WHEN day_type='oval' THEN best END) best_oval,
                        MIN(CASE WHEN day_type='offroad' THEN best END) best_offroad
                 FROM run_bests GROUP BY name ORDER BY name""",
             (minimums['oval'], minimums['offroad'], like, like))
    return render_template('drivers.html', rows=rows, term=term)

def _mean(v): return sum(v) / len(v) if v else None

def driver_data(name):
    res = q(f"SELECT r.*, d.race_date, d.day_type FROM results r JOIN race_days d ON d.id=r.day_id {JOIN} WHERE {NAME}=? ORDER BY d.race_date", (name,))
    if not res: return None
    minimums = lap_minimums(db())
    laps = q(f"SELECT r.day_id, r.class_name, l.lap_time FROM laps l JOIN results r ON r.id=l.result_id {JOIN} WHERE {NAME}=? AND l.lap_time IS NOT NULL", (name,))
    meta = {}                                     # (day,class) -> [top eor_y, final_x, qual_x]
    for r in q("SELECT DISTINCT day_id, class_name, eor_x, eor_y FROM eor_results"):
        m = meta.setdefault((r['day_id'], r['class_name']), {'y': 0, 'xs': set()})
        if r['eor_y'] > m['y']: m['y'], m['xs'] = r['eor_y'], {r['eor_x']}
        elif r['eor_y'] == m['y']: m['xs'].add(r['eor_x'])
    eor = q(f"SELECT e.* FROM eor_results e {EOR_JOIN} WHERE {EOR_NAME}=?", (name,))
    E = {}
    for r in res:
        e = E.setdefault((r['day_id'], r['class_name']), dict(day_id=r['day_id'], date=r['race_date'], type=r['day_type'], cls=r['class_name'],
                         heat_pos=[], cars=set(), group=None, laps_list=[], reported_bests=[], laps=0, final_pos=None, qual_pos=None))
        if valid_lap(r['fastest_lap'], minimums[r['day_type']]):
            e['reported_bests'].append(r['fastest_lap'])
        e['cars'].add(r['car_no'])
        if r['stage'] == 'heat': e['heat_pos'].append(r['position'])
        else: e['group'] = r['final_group']
    for l in laps:
        e = E.get((l['day_id'], l['class_name']))
        if e:
            e['laps'] += 1
            if valid_lap(l['lap_time'], minimums[e['type']]):
                e['laps_list'].append(l['lap_time'])
    for r in eor:
        k = (r['day_id'], r['class_name']); m = meta.get(k)
        if not m or r['eor_y'] != m['y'] or k not in E: continue
        if r['eor_x'] == max(m['xs']): E[k]['final_pos'] = r['position']
        if r['eor_x'] == min(m['xs']): E[k]['qual_pos'] = r['position']
    for e in E.values():
        L = e['laps_list']
        e.update(avg_lap=_mean(L), median_lap=statistics.median(L) if L else None, best_lap=best_lap(L, best_lap(e['reported_bests'])),
                 stdev=statistics.pstdev(L) if len(L) > 1 else None, avg_heat_pos=_mean(e['heat_pos']))
    return sorted(E.values(), key=lambda e: (e['date'], e['cls']))

DRIVER_METRICS = {'avg_lap': 'Average lap (s)', 'median_lap': 'Median lap (s)', 'best_lap': 'Best lap (s)', 'stdev': 'Consistency, std dev (s, lower = steadier)',
                  'avg_heat_pos': 'Average heat position', 'qual_pos': 'Qualifying position', 'final_pos': 'Final position', 'laps': 'Laps run'}
POS_METRICS = ('avg_heat_pos', 'qual_pos', 'final_pos')

def by_vehicle(entries):
    g = {}
    for e in entries: g.setdefault((e['type'], e['cls']), []).append(e)
    out = []
    for (t, c), es in sorted(g.items()):
        L = [x for e in es for x in e['laps_list']]
        fp = [e['final_pos'] for e in es if e['final_pos']]
        out.append(dict(type=t, cls=c, days=len(es), laps=sum(e['laps'] for e in es), avg_lap=_mean(L), median_lap=statistics.median(L) if L else None,
                        best_lap=best_lap(e['best_lap'] for e in es if e['best_lap'] is not None), stdev=statistics.pstdev(L) if len(L) > 1 else None,
                        avg_heat_pos=_mean([p for e in es for p in e['heat_pos']]), qual_pos=_mean([e['qual_pos'] for e in es if e['qual_pos']]),
                        final_pos=_mean(fp), wins=sum(1 for p in fp if p == 1), podiums=sum(1 for p in fp if p <= 3)))
    return out

@app.route('/driver/<path:name>')
def driver(name):
    entries = driver_data(name)
    if entries is None: abort(404)
    veh = by_vehicle(entries)
    allL = [x for e in entries for x in e['laps_list']]
    fp = [e['final_pos'] for e in entries if e['final_pos']]
    bests = {kind: best_lap(e['best_lap'] for e in entries if e['type'] == kind and e['best_lap'] is not None)
             for kind in ('oval', 'offroad')}
    summary = dict(days=len({e['day_id'] for e in entries}), laps=sum(e['laps'] for e in entries), avg=_mean(allL), bests=bests,
                   wins=sum(1 for p in fp if p == 1), podiums=sum(1 for p in fp if p <= 3), classes=sorted({e['cls'] for e in entries}))
    photo = q("SELECT filename FROM driver_photos WHERE driver_name=?", (name,))
    return render_template('driver.html', photo=photo[0]['filename'] if photo else None, name=name, entries=list(reversed(entries)), veh=veh, s=summary, metrics=DRIVER_METRICS)

@app.route('/api/driver/chart')
def driver_chart():
    name = request.args.get('name', ''); mode = request.args.get('mode', 'time'); metric = request.args.get('metric', 'avg_lap')
    kind = request.args.get('type', 'all')
    if metric not in DRIVER_METRICS: metric = 'avg_lap'
    entries = driver_data(name) or []
    if kind in ('oval', 'offroad'): entries = [e for e in entries if e['type'] == kind]
    label = lambda t, c: c if kind != 'all' else f"{c} ({t})"
    resp = dict(yTitle=DRIVER_METRICS[metric], reversed=metric in POS_METRICS, integer=metric in POS_METRICS or metric == 'laps', plotLines=[])
    if mode == 'vehicle':
        v = by_vehicle(entries)
        resp.update(categories=[label(x['type'], x['cls']) for x in v], series=[dict(name=DRIVER_METRICS[metric], data=[x[metric] for x in v])])
        resp['integer'] = metric == 'laps'
        return jsonify(resp)
    years = request.args.get('years', type=int)
    cutoff = None
    if years in (1, 2, 4) and entries:
        latest = date.fromisoformat(entries[-1]['date'])
        target_year = max(1, latest.year - years)
        try:
            cutoff = latest.replace(year=target_year).isoformat()
        except ValueError:  # February 29 in a non-leap year
            cutoff = latest.replace(year=target_year, day=28).isoformat()
        entries = [e for e in entries if e['date'] >= cutoff]
    dates = sorted({e['date'] for e in entries})
    series = {}
    for e in entries: series.setdefault(label(e['type'], e['cls']), {})[e['date']] = e[metric]
    resp.update(categories=dates, series=[dict(name=k, data=[v.get(d) for d in dates]) for k, v in sorted(series.items())])
    if dates:                                      # track-change markers from the admin "track events" list
        for ev in q("SELECT * FROM track_events ORDER BY event_date"):
            if kind != 'all' and ev['day_type'] not in (None, '', kind): continue
            if cutoff and not cutoff <= ev['event_date'] <= dates[-1]: continue
            i = sum(1 for d in dates if d <= ev['event_date'])     # number of race days on/before the event
            resp['plotLines'].append(dict(value=i - 0.5, text=ev['title']))
    return jsonify(resp)

import admin, submissions
admin.init(app)
submissions.init(app)

@app.errorhandler(404)
def nf(e): return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=getattr(config, 'DEBUG', False))
