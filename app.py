import os, statistics
from flask import Flask, g, session, render_template, request, jsonify, abort
import config, importer

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

NAME = "COALESCE(nm.full_name, r.raw_name)"
JOIN = "LEFT JOIN name_map nm ON nm.raw_name = r.raw_name"

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

def day_data(did, cls):
    """Everything for one class on one day, one dict per driver."""
    rows = q(f"SELECT r.*, {NAME} AS name FROM results r {JOIN} WHERE r.day_id=? AND r.class_name=?", (did, cls))
    laps = q(f"""SELECT {NAME} AS name, l.lap_time FROM laps l JOIN results r ON r.id=l.result_id {JOIN}
                 WHERE r.day_id=? AND r.class_name=? AND l.lap_time IS NOT NULL""", (did, cls))
    lapmap = {}
    for l in laps: lapmap.setdefault(l['name'], []).append(l['lap_time'])
    eor = q(f"""SELECT e.*, COALESCE(nm.full_name, e.raw_name) AS name FROM eor_results e
                LEFT JOIN name_map nm ON nm.raw_name=e.raw_name WHERE e.day_id=? AND e.class_name=?""", (did, cls))
    top_y = max([e['eor_y'] for e in eor], default=0)
    last = [e for e in eor if e['eor_y'] == top_y]
    final_x = max([e['eor_x'] for e in last], default=0); qual_x = min([e['eor_x'] for e in last], default=0)
    final_pos = {e['name']: e for e in last if e['eor_x'] == final_x}
    qual_pos = {e['name']: e for e in last if e['eor_x'] == qual_x}
    drivers = {}
    for r in rows:
        d = drivers.setdefault(r['name'], dict(name=r['name'], rounds={}, final=None))
        if r['stage'] == 'final': d['final'] = r
        else: d['rounds'][r['round_no']] = r
    for n, d in drivers.items():
        L = lapmap.get(n, [])
        d['all_laps'] = len(L)
        d['avg'] = sum(L) / len(L) if L else None
        d['best'] = min(L) if L else None
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
    drivers, rounds = day_data(did, cls) if classes else ([], [])
    return render_template('day.html', day=d[0], classes=classes, cls=cls, drivers=drivers, rounds=rounds)

METRICS = {'avg_lap': 'Average lap (s)', 'fastest_lap': 'Fastest lap (s)', 'total_time': 'Total time (s)', 'laps': 'Laps completed', 'position': 'Position'}

@app.route('/api/day/<int:did>/chart')
def chart(did):
    cls = request.args.get('class', ''); mode = request.args.get('mode', 'rounds')
    if mode == 'laps':
        sel = request.args.get('round', 'final')
        where = "r.stage='final'" if sel == 'final' else "r.stage='heat' AND r.round_no=%d" % int(sel)
        rows = q(f"""SELECT {NAME} AS name, l.lap_no, l.lap_time FROM laps l JOIN results r ON r.id=l.result_id {JOIN}
                     WHERE r.day_id=? AND r.class_name=? AND {where} ORDER BY l.lap_no""", (did, cls))
        series = {}
        for r in rows: series.setdefault(r['name'], {})[r['lap_no']] = r['lap_time']
        n = max([max(v) for v in series.values()], default=0)
        return jsonify(categories=[str(i) for i in range(1, n + 1)], xTitle='Lap', yTitle='Lap time (s)', reversed=False,
                       series=[dict(name=k, data=[v.get(i) for i in range(1, n + 1)]) for k, v in sorted(series.items())])
    metric = request.args.get('metric', 'avg_lap')
    if metric not in METRICS: metric = 'avg_lap'
    rows = q(f"SELECT r.stage, r.round_no, {NAME} AS name, r.{metric} AS v FROM results r {JOIN} WHERE r.day_id=? AND r.class_name=?", (did, cls))
    rounds = sorted({r['round_no'] for r in rows if r['stage'] == 'heat'})
    cats = [f"Round {i}" for i in rounds] + (['Final'] if any(r['stage'] == 'final' for r in rows) else [])
    series = {}
    for r in rows:
        key = 'Final' if r['stage'] == 'final' else f"Round {r['round_no']}"
        series.setdefault(r['name'], {})[key] = r['v'] if (r['v'] or r['v'] == 0) and not (metric in ('avg_lap', 'fastest_lap', 'total_time') and not r['v']) else None
    return jsonify(categories=cats, xTitle='', yTitle=METRICS[metric], reversed=(metric == 'position'),
                   series=[dict(name=k, data=[v.get(c) for c in cats]) for k, v in sorted(series.items())])


# ---------- drivers ----------
@app.route('/drivers')
def drivers():
    term = request.args.get('q', '').strip()
    like = f"%{term}%"
    rows = q(f"""SELECT {NAME} AS name, COUNT(DISTINCT r.day_id) days, GROUP_CONCAT(DISTINCT r.class_name) classes, MIN(r.fastest_lap) best
                 FROM results r {JOIN} WHERE {NAME} LIKE ? OR r.raw_name LIKE ? GROUP BY name ORDER BY name""", (like, like))
    return render_template('drivers.html', rows=rows, term=term)

def _mean(v): return sum(v) / len(v) if v else None

def driver_data(name):
    res = q(f"SELECT r.*, d.race_date, d.day_type FROM results r JOIN race_days d ON d.id=r.day_id {JOIN} WHERE {NAME}=? ORDER BY d.race_date", (name,))
    if not res: return None
    laps = q(f"SELECT r.day_id, r.class_name, l.lap_time FROM laps l JOIN results r ON r.id=l.result_id {JOIN} WHERE {NAME}=? AND l.lap_time IS NOT NULL", (name,))
    meta = {}                                     # (day,class) -> [top eor_y, final_x, qual_x]
    for r in q("SELECT DISTINCT day_id, class_name, eor_x, eor_y FROM eor_results"):
        m = meta.setdefault((r['day_id'], r['class_name']), {'y': 0, 'xs': set()})
        if r['eor_y'] > m['y']: m['y'], m['xs'] = r['eor_y'], {r['eor_x']}
        elif r['eor_y'] == m['y']: m['xs'].add(r['eor_x'])
    eor = q("SELECT e.* FROM eor_results e LEFT JOIN name_map nm ON nm.raw_name=e.raw_name WHERE COALESCE(nm.full_name,e.raw_name)=?", (name,))
    E = {}
    for r in res:
        e = E.setdefault((r['day_id'], r['class_name']), dict(day_id=r['day_id'], date=r['race_date'], type=r['day_type'], cls=r['class_name'],
                         heat_pos=[], cars=set(), group=None, laps_list=[], final_pos=None, qual_pos=None))
        e['cars'].add(r['car_no'])
        if r['stage'] == 'heat': e['heat_pos'].append(r['position'])
        else: e['group'] = r['final_group']
    for l in laps:
        e = E.get((l['day_id'], l['class_name']))
        if e: e['laps_list'].append(l['lap_time'])
    for r in eor:
        k = (r['day_id'], r['class_name']); m = meta.get(k)
        if not m or r['eor_y'] != m['y'] or k not in E: continue
        if r['eor_x'] == max(m['xs']): E[k]['final_pos'] = r['position']
        if r['eor_x'] == min(m['xs']): E[k]['qual_pos'] = r['position']
    for e in E.values():
        L = e['laps_list']
        e.update(avg_lap=_mean(L), median_lap=statistics.median(L) if L else None, best_lap=min(L) if L else None,
                 stdev=statistics.pstdev(L) if len(L) > 1 else None, laps=len(L), avg_heat_pos=_mean(e['heat_pos']))
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
        out.append(dict(type=t, cls=c, days=len(es), laps=len(L), avg_lap=_mean(L), median_lap=statistics.median(L) if L else None,
                        best_lap=min(L) if L else None, stdev=statistics.pstdev(L) if len(L) > 1 else None,
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
    summary = dict(days=len({e['day_id'] for e in entries}), laps=len(allL), avg=_mean(allL), best=min(allL) if allL else None,
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
    dates = sorted({e['date'] for e in entries})
    series = {}
    for e in entries: series.setdefault(label(e['type'], e['cls']), {})[e['date']] = e[metric]
    resp.update(categories=dates, series=[dict(name=k, data=[v.get(d) for d in dates]) for k, v in sorted(series.items())])
    if dates:                                      # track-change markers from the admin "track events" list
        for ev in q("SELECT * FROM track_events ORDER BY event_date"):
            if kind != 'all' and ev['day_type'] not in (None, '', kind): continue
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
