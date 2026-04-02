#!/usr/bin/env python3
"""Fetch Artemis II trajectory data from JPL Horizons and write JS data modules."""

import json
import math
import os
import urllib.request
import urllib.parse

HORIZONS_API = 'https://ssd.jpl.nasa.gov/api/horizons.api'
MISSION_START = '2026-04-02 02:00'
MISSION_END = '2026-04-10 23:59'
STEP_SIZE = '1m'
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')


def fetch_horizons(command, ephem_type, extra_params=None):
    """Fetch data from JPL Horizons API."""
    params = {
        'format': 'json',
        'COMMAND': f"'{command}'",
        'OBJ_DATA': 'NO',
        'MAKE_EPHEM': 'YES',
        'EPHEM_TYPE': f"'{ephem_type}'",
        'CENTER': "'500@399'",
        'START_TIME': f"'{MISSION_START}'",
        'STOP_TIME': f"'{MISSION_END}'",
        'STEP_SIZE': f"'{STEP_SIZE}'",
        'CSV_FORMAT': 'YES',
    }
    if extra_params:
        params.update(extra_params)

    query = '&'.join(f'{k}={urllib.parse.quote(str(v), safe="'@")}' for k, v in params.items())
    url = f'{HORIZONS_API}?{query}'
    print(f'  Fetching: {command} {ephem_type}...')

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())

    return data['result']


def extract_rows(raw):
    """Extract data rows between $$SOE and $$EOE markers."""
    lines = raw.split('\n')
    in_data = False
    rows = []
    for line in lines:
        if '$$SOE' in line:
            in_data = True
            continue
        if '$$EOE' in line:
            break
        if in_data and line.strip():
            rows.append(line.strip())
    return rows


def write_vectors(rows, filepath, varname, comment):
    """Write vector data as a JS module."""
    with open(filepath, 'w') as f:
        f.write(f'// {comment}\n')
        f.write(f'// [jd, dateStr, x, y, z, vx, vy, vz, range, rangeRate]\n')
        f.write(f'export const {varname} = [\n')
        for row in rows:
            parts = [p.strip() for p in row.split(',')]
            jd = parts[0]
            ds = parts[1].strip().replace('A.D. ', '')
            nums = ','.join([parts[2], parts[3], parts[4], parts[5], parts[6], parts[7], parts[9], parts[10]])
            f.write(f'[{jd},"{ds}",{nums}],\n')
        f.write('];\n')


def write_elements(rows, filepath):
    """Write orbital elements as a JS module."""
    with open(filepath, 'w') as f:
        f.write('// Orion orbital elements from JPL Horizons (Earth-centered)\n')
        f.write('// [jd, ecc, periapsis, incl, raan, argPeri, trueAnom, sma, apoapsis, period]\n')
        f.write('export const ORION_ELEMENTS = [\n')
        for row in rows:
            parts = [p.strip() for p in row.split(',')]
            vals = ','.join([parts[0], parts[2], parts[3], parts[4], parts[5], parts[6],
                            parts[10], parts[11], parts[12], parts[13]])
            f.write(f'[{vals}],\n')
        f.write('];\n')


def append_verlet_extension(vectors_path):
    """Append 30 minutes of ballistic Verlet integration from the last data point."""
    with open(vectors_path, 'r') as f:
        content = f.read()

    # Find the last data row
    lines = content.strip().split('\n')
    last_row = None
    for line in reversed(lines):
        if line.strip().startswith('['):
            last_row = line.strip().rstrip(',')
            break

    if not last_row:
        return

    parts = last_row.strip('[').strip(']').split(',')
    jd0 = float(parts[0])
    x, y, z = float(parts[2]), float(parts[3]), float(parts[4])
    vx, vy, vz = float(parts[5]), float(parts[6]), float(parts[7])

    GM = 398600.4418  # km^3/s^2
    dt = 1.0  # 1 second steps
    extra_rows = []

    for step in range(1, 1801):  # 30 minutes
        r = math.sqrt(x**2 + y**2 + z**2)
        ax = -GM * x / (r**3)
        ay = -GM * y / (r**3)
        az = -GM * z / (r**3)
        vx += ax * dt
        vy += ay * dt
        vz += az * dt
        x += vx * dt
        y += vy * dt
        z += vz * dt

        if step % 10 == 0:  # every 10 seconds
            r = math.sqrt(x**2 + y**2 + z**2)
            rr = (x*vx + y*vy + z*vz) / r
            jd = jd0 + step / 86400.0

            from datetime import datetime, timedelta
            base = datetime(2026, 4, 10, 23, 59, 0)
            dt_obj = base + timedelta(seconds=step)
            datestr = dt_obj.strftime('%Y-%b-%d %H:%M:%S.0000')

            extra_rows.append(f'[{jd},"{datestr}",{x},{y},{z},{vx},{vy},{vz},{r},{rr}],\n')

    # Insert before the closing ];\n
    insert_point = content.rstrip().rfind('];')
    new_content = content[:insert_point] + ''.join(extra_rows) + '];\n'

    with open(vectors_path, 'w') as f:
        f.write(new_content)

    print(f'  Appended {len(extra_rows)} Verlet extension points')


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    print('Fetching Artemis II data from JPL Horizons...')

    # Fetch all three datasets
    orion_raw = fetch_horizons('-1024', 'VECTORS')
    moon_raw = fetch_horizons('301', 'VECTORS')
    elem_raw = fetch_horizons('-1024', 'ELEMENTS')

    # Parse
    orion_rows = extract_rows(orion_raw)
    moon_rows = extract_rows(moon_raw)
    elem_rows = extract_rows(elem_raw)

    print(f'  Orion vectors: {len(orion_rows)} rows')
    print(f'  Moon vectors: {len(moon_rows)} rows')
    print(f'  Orbital elements: {len(elem_rows)} rows')

    # Write JS modules
    orion_path = os.path.join(DATA_DIR, 'orion_vectors.js')
    moon_path = os.path.join(DATA_DIR, 'moon_vectors.js')
    elem_path = os.path.join(DATA_DIR, 'orion_elements.js')

    write_vectors(orion_rows, orion_path,
                  'ORION_VECTORS',
                  'Orion state vectors from JPL Horizons ID:-1024 (Earth ICRF J2000) - 1min resolution')
    write_vectors(moon_rows, moon_path,
                  'MOON_VECTORS',
                  'Moon state vectors from JPL Horizons ID:301 (Earth ICRF J2000) - 1min resolution')
    write_elements(elem_rows, elem_path)

    # Append Verlet extension for reentry visualization
    append_verlet_extension(orion_path)

    for name in ['orion_vectors.js', 'moon_vectors.js', 'orion_elements.js']:
        path = os.path.join(DATA_DIR, name)
        size = os.path.getsize(path)
        print(f'  {name}: {size:,} bytes')

    print('Done.')


if __name__ == '__main__':
    main()
