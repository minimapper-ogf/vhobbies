"""Shared driver name resolution and lap-time settings."""

MINIMUMS = {'oval': 5.0, 'offroad': 0.0}


def name_join(alias):
    return f"LEFT JOIN name_map nm ON nm.raw_name={alias}.raw_name"


def display_name(alias):
    return f"""COALESCE((SELECT dn.full_name FROM dated_names dn
                         JOIN race_days rd ON rd.id={alias}.day_id
                         WHERE dn.raw_name={alias}.raw_name
                           AND rd.race_date BETWEEN dn.start_date AND dn.end_date),
                        nm.full_name, {alias}.raw_name)"""


RESULT_NAME = display_name('r')
RESULT_JOIN = name_join('r')
EOR_NAME = display_name('e')
EOR_JOIN = name_join('e')


def lap_minimums(db):
    minimums = MINIMUMS.copy()
    rows = db.execute("SELECT key, value FROM site_content WHERE key IN ('min_lap_oval', 'min_lap_offroad')")
    minimums.update((key.removeprefix('min_lap_'), float(value)) for key, value in rows)
    return minimums


def valid_lap(value, minimum):
    return value is not None and value > 0 and value >= minimum


def best_lap(recorded, reported=None):
    return min((*recorded, reported) if reported is not None else recorded, default=None)
