from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import os
import sys
import shutil
import socket
import threading
import webbrowser
import calendar
from datetime import datetime, date, timedelta


def resource_path(relative_path):
    """Path to a bundled (read-only) resource. Works both when running as a
    normal .py script and when running as a frozen PyInstaller .exe."""
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def persistent_data_dir():
    """A writable folder that survives between launches of the .exe.
    PyInstaller's onefile mode unpacks to a temp folder that gets deleted
    on exit, so the live database must live outside of that."""
    appdata = os.environ.get('APPDATA') or os.path.expanduser('~')
    data_dir = os.path.join(appdata, 'WarrantyTracker')
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


app = Flask(__name__, static_folder=resource_path('public'), static_url_path='')

DB_PATH = os.path.join(persistent_data_dir(), 'warranty.db')

# First launch ever: seed the persistent database from the copy bundled
# inside the app (which already contains your existing records) so nothing
# is lost. Every launch after that just reuses the persistent one.
if not os.path.exists(DB_PATH):
    bundled_db = resource_path('warranty.db')
    if os.path.exists(bundled_db):
        shutil.copy(bundled_db, DB_PATH)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchaser_name TEXT NOT NULL,
            address TEXT NOT NULL,
            purchase_date TEXT NOT NULL,
            turnover_date TEXT,
            supplier TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            serial_number TEXT NOT NULL,
            device_name TEXT NOT NULL,
            warranty_months INTEGER NOT NULL DEFAULT 12,
            FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS service_warranties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            service_name TEXT NOT NULL,
            warranty_months INTEGER NOT NULL DEFAULT 12,
            FOREIGN KEY (record_id) REFERENCES records(id) ON DELETE CASCADE
        )
    ''')
    # Product Prices table
    c.execute('''
        CREATE TABLE IF NOT EXISTS pp_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            model TEXT NOT NULL,
            product_type TEXT NOT NULL DEFAULT "",
            supplier_price REAL NOT NULL DEFAULT 0,
            custom_markup REAL NOT NULL DEFAULT 35,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        )
    ''')
    # Migrate: add any missing columns
    pp_cols = [row[1] for row in c.execute("PRAGMA table_info(pp_items)").fetchall()]
    for col, defn in [('code','TEXT'), ('product_type','TEXT NOT NULL DEFAULT ""'),
                      ('custom_markup','REAL NOT NULL DEFAULT 35'), ('is_hidden','INTEGER NOT NULL DEFAULT 0')]:
        if col not in pp_cols:
            c.execute(f"ALTER TABLE pp_items ADD COLUMN {col} {defn}")
    c.execute('''
        CREATE TABLE IF NOT EXISTS sc_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            size TEXT NOT NULL,
            qty INTEGER NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 0,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    # Migrate: add is_hidden if missing
    sc_cols = [row[1] for row in c.execute("PRAGMA table_info(sc_items)").fetchall()]
    if 'is_hidden' not in sc_cols:
        c.execute("ALTER TABLE sc_items ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
    # Take log table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sc_takes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            item_size TEXT NOT NULL DEFAULT '',
            qty_taken INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL,
            taken_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (item_id) REFERENCES sc_items(id)
        )
    ''')
    # Add stock log table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sc_adds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            item_size TEXT NOT NULL DEFAULT '',
            qty_added INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL,
            added_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (item_id) REFERENCES sc_items(id)
        )
    ''')
    # Migrate: add item_size to sc_takes and sc_adds if missing
    takes_cols = [row[1] for row in c.execute("PRAGMA table_info(sc_takes)").fetchall()]
    if 'item_size' not in takes_cols:
        c.execute("ALTER TABLE sc_takes ADD COLUMN item_size TEXT NOT NULL DEFAULT ''")
    adds_cols = [row[1] for row in c.execute("PRAGMA table_info(sc_adds)").fetchall()]
    if 'item_size' not in adds_cols:
        c.execute("ALTER TABLE sc_adds ADD COLUMN item_size TEXT NOT NULL DEFAULT ''")

    # Migrate cp_items: rename size -> type
    cp_cols = [row[1] for row in c.execute("PRAGMA table_info(cp_items)").fetchall()]
    if 'size' in cp_cols and 'type' not in cp_cols:
        c.execute("ALTER TABLE cp_items ADD COLUMN type TEXT NOT NULL DEFAULT ''")
        c.execute("UPDATE cp_items SET type = size")
    # Migrate cp_takes: rename item_size -> item_type
    cpt_cols = [row[1] for row in c.execute("PRAGMA table_info(cp_takes)").fetchall()]
    if 'item_size' in cpt_cols and 'item_type' not in cpt_cols:
        c.execute("ALTER TABLE cp_takes ADD COLUMN item_type TEXT NOT NULL DEFAULT ''")
        c.execute("UPDATE cp_takes SET item_type = item_size")
    # Migrate cp_adds: rename item_size -> item_type
    cpa_cols = [row[1] for row in c.execute("PRAGMA table_info(cp_adds)").fetchall()]
    if 'item_size' in cpa_cols and 'item_type' not in cpa_cols:
        c.execute("ALTER TABLE cp_adds ADD COLUMN item_type TEXT NOT NULL DEFAULT ''")
        c.execute("UPDATE cp_adds SET item_type = item_size")

    # Computer Peripherals table
    c.execute('''
        CREATE TABLE IF NOT EXISTS cp_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT "",
            qty INTEGER NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 0,
            is_hidden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS cp_takes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            item_type TEXT NOT NULL DEFAULT "",
            qty_taken INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL,
            taken_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS cp_adds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            item_type TEXT NOT NULL DEFAULT "",
            qty_added INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total_price REAL NOT NULL,
            added_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_type TEXT NOT NULL CHECK(transaction_type IN ('income', 'expense')),
            amount REAL NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            transaction_date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS transaction_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            created_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    # Backfill: any category text already used on transactions becomes a
    # managed category too, so nothing already typed in gets lost.
    existing_cats = c.execute(
        "SELECT DISTINCT category FROM transactions WHERE TRIM(category) != ''"
    ).fetchall()
    for row in existing_cats:
        name = row[0].strip()
        if name:
            c.execute(
                'INSERT OR IGNORE INTO transaction_categories (name) VALUES (?)', (name,)
            )
    # Migrate old schema
    cols = [row[1] for row in c.execute("PRAGMA table_info(records)").fetchall()]
    if 'warranty_months' in cols:
        dev_cols = [row[1] for row in c.execute("PRAGMA table_info(devices)").fetchall()]
        if 'warranty_months' not in dev_cols:
            c.execute("ALTER TABLE devices ADD COLUMN warranty_months INTEGER NOT NULL DEFAULT 12")
        c.execute('''
            UPDATE devices SET warranty_months = (
                SELECT warranty_months FROM records WHERE records.id = devices.record_id
            ) WHERE warranty_months = 12
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS records_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchaser_name TEXT NOT NULL,
                address TEXT NOT NULL,
                purchase_date TEXT NOT NULL,
                supplier TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        ''')
        c.execute('''
            INSERT INTO records_new (id, purchaser_name, address, purchase_date, supplier, created_at)
            SELECT id, purchaser_name, address, purchase_date, supplier, created_at FROM records
        ''')
        c.execute("DROP TABLE records")
        c.execute("ALTER TABLE records_new RENAME TO records")
    # Migrate: add turnover_date to records if missing
    rec_cols = [row[1] for row in c.execute("PRAGMA table_info(records)").fetchall()]
    if 'turnover_date' not in rec_cols:
        c.execute("ALTER TABLE records ADD COLUMN turnover_date TEXT")
    conn.commit()
    conn.close()

def add_months(d, months):
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def device_warranty(purchase_date_str, warranty_months):
    try:
        pd = datetime.strptime(purchase_date_str, '%Y-%m-%d').date()
    except:
        return 'unknown', None, None
    expiry = add_months(pd, warranty_months)
    today = date.today()
    days_left = (expiry - today).days
    if days_left < 0:
        status = 'expired'
    elif days_left <= 30:
        status = 'expiring_soon'
    else:
        status = 'active'
    return status, expiry.strftime('%Y-%m-%d'), days_left

def record_worst_status(device_statuses):
    if 'expired' in device_statuses:
        return 'expired'
    if 'expiring_soon' in device_statuses:
        return 'expiring_soon'
    if 'active' in device_statuses:
        return 'active'
    return 'unknown'

def build_record(r, devices, purchase_date, service_warranties=None):
    dev_list = []
    for d in devices:
        status, expiry, days_left = device_warranty(purchase_date, d['warranty_months'])
        dev_list.append({
            'id': d['id'],
            'serial_number': d['serial_number'],
            'device_name': d['device_name'],
            'warranty_months': d['warranty_months'],
            'warranty_expiry': expiry,
            'warranty_status': status,
            'days_left': days_left,
        })
    svc_list = []
    if service_warranties:
        for s in service_warranties:
            status, expiry, days_left = device_warranty(purchase_date, s['warranty_months'])
            svc_list.append({
                'id': s['id'],
                'service_name': s['service_name'],
                'warranty_months': s['warranty_months'],
                'warranty_expiry': expiry,
                'warranty_status': status,
                'days_left': days_left,
            })
    all_statuses = [dv['warranty_status'] for dv in dev_list] + [sv['warranty_status'] for sv in svc_list]
    record_status = record_worst_status(all_statuses) if all_statuses else 'unknown'
    return {
        'id': r['id'],
        'purchaser_name': r['purchaser_name'],
        'address': r['address'],
        'purchase_date': purchase_date,
        'turnover_date': r['turnover_date'] if 'turnover_date' in r.keys() else None,
        'supplier': r['supplier'],
        'created_at': r['created_at'],
        'warranty_status': record_status,
        'devices': dev_list,
        'service_warranties': svc_list,
    }

init_db()

# ── WARRANTY API ──────────────────────────────────────────────────────────────

@app.route('/api/records', methods=['GET'])
def get_records():
    conn = get_db()
    c = conn.cursor()
    search = request.args.get('search', '').strip()
    supplier = request.args.get('supplier', '').strip()
    status_filter = request.args.get('status', '').strip()
    conditions, params = [], []
    if search:
        conditions.append('''(
            r.purchaser_name LIKE ? OR r.address LIKE ?
            OR r.id IN (SELECT record_id FROM devices WHERE serial_number LIKE ?)
        )''')
        like = f'%{search}%'
        params += [like, like, like]
    if supplier:
        conditions.append('r.supplier = ?')
        params.append(supplier)
    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    rows = c.execute(
        f'SELECT * FROM records r {where} ORDER BY r.purchase_date DESC', params
    ).fetchall()
    result = []
    for r in rows:
        devices = c.execute('SELECT * FROM devices WHERE record_id = ?', (r['id'],)).fetchall()
        svcs = c.execute('SELECT * FROM service_warranties WHERE record_id = ?', (r['id'],)).fetchall()
        rec = build_record(r, devices, r['purchase_date'], svcs)
        if status_filter and rec['warranty_status'] != status_filter:
            continue
        result.append(rec)
    conn.close()
    return jsonify(result)

@app.route('/api/records/<int:record_id>', methods=['GET'])
def get_record(record_id):
    conn = get_db()
    c = conn.cursor()
    r = c.execute('SELECT * FROM records WHERE id = ?', (record_id,)).fetchone()
    if not r:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    devices = c.execute('SELECT * FROM devices WHERE record_id = ?', (record_id,)).fetchall()
    svcs = c.execute('SELECT * FROM service_warranties WHERE record_id = ?', (record_id,)).fetchall()
    result = build_record(r, devices, r['purchase_date'], svcs)
    conn.close()
    return jsonify(result)

@app.route('/api/records', methods=['POST'])
def create_record():
    data = request.get_json()
    for field in ['purchaser_name', 'address', 'purchase_date', 'supplier', 'devices']:
        if field not in data:
            return jsonify({'error': f'Missing field: {field}'}), 400
    if not data['devices']:
        return jsonify({'error': 'At least one device required'}), 400
    if data['supplier'] not in ['Prowatcher', 'Amax']:
        return jsonify({'error': 'Supplier must be Prowatcher or Amax'}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute(
        'INSERT INTO records (purchaser_name, address, purchase_date, turnover_date, supplier) VALUES (?, ?, ?, ?, ?)',
        (data['purchaser_name'], data['address'], data['purchase_date'],
         data.get('turnover_date') or None, data['supplier'])
    )
    record_id = c.lastrowid
    for device in data['devices']:
        c.execute(
            'INSERT INTO devices (record_id, serial_number, device_name, warranty_months) VALUES (?, ?, ?, ?)',
            (record_id, device['serial_number'], device.get('device_name', ''), int(device.get('warranty_months', 12)))
        )
    for svc in data.get('service_warranties', []):
        c.execute(
            'INSERT INTO service_warranties (record_id, service_name, warranty_months) VALUES (?, ?, ?)',
            (record_id, svc['service_name'], int(svc.get('warranty_months', 12)))
        )
    conn.commit()
    conn.close()
    return jsonify({'id': record_id, 'message': 'Record created'}), 201

@app.route('/api/records/<int:record_id>', methods=['PUT'])
def update_record(record_id):
    data = request.get_json()
    conn = get_db()
    c = conn.cursor()
    if not c.execute('SELECT id FROM records WHERE id = ?', (record_id,)).fetchone():
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    c.execute(
        'UPDATE records SET purchaser_name=?, address=?, purchase_date=?, turnover_date=?, supplier=? WHERE id=?',
        (data['purchaser_name'], data['address'], data['purchase_date'],
         data.get('turnover_date') or None, data['supplier'], record_id)
    )
    c.execute('DELETE FROM devices WHERE record_id = ?', (record_id,))
    for device in data['devices']:
        c.execute(
            'INSERT INTO devices (record_id, serial_number, device_name, warranty_months) VALUES (?, ?, ?, ?)',
            (record_id, device['serial_number'], device.get('device_name', ''), int(device.get('warranty_months', 12)))
        )
    c.execute('DELETE FROM service_warranties WHERE record_id = ?', (record_id,))
    for svc in data.get('service_warranties', []):
        c.execute(
            'INSERT INTO service_warranties (record_id, service_name, warranty_months) VALUES (?, ?, ?)',
            (record_id, svc['service_name'], int(svc.get('warranty_months', 12)))
        )
    conn.commit()
    conn.close()
    return jsonify({'message': 'Record updated'})

@app.route('/api/records/<int:record_id>', methods=['DELETE'])
def delete_record(record_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM devices WHERE record_id = ?', (record_id,))
    c.execute('DELETE FROM service_warranties WHERE record_id = ?', (record_id,))
    c.execute('DELETE FROM records WHERE id = ?', (record_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Record deleted'})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    c = conn.cursor()
    records = c.execute('SELECT id, purchase_date FROM records').fetchall()
    total = len(records)
    active = expiring_soon = expired = 0
    for r in records:
        devices = c.execute('SELECT warranty_months FROM devices WHERE record_id = ?', (r['id'],)).fetchall()
        statuses = [device_warranty(r['purchase_date'], d['warranty_months'])[0] for d in devices]
        s = record_worst_status(statuses)
        if s == 'active': active += 1
        elif s == 'expiring_soon': expiring_soon += 1
        elif s == 'expired': expired += 1
    device_count = c.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
    conn.close()
    return jsonify({'total': total, 'active': active, 'expiring_soon': expiring_soon, 'expired': expired, 'devices': device_count})

# ── SCREWS & CONNECTORS API ───────────────────────────────────────────────────

@app.route('/api/sc/items', methods=['GET'])
def sc_get_items():
    conn = get_db()
    c = conn.cursor()
    rows = c.execute('SELECT * FROM sc_items WHERE is_hidden = 0 ORDER BY name ASC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/sc/items', methods=['POST'])
def sc_create_item():
    data = request.get_json()
    for field in ['name', 'size', 'qty', 'price']:
        if field not in data:
            return jsonify({'error': f'Missing field: {field}'}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO sc_items (name, size, qty, price) VALUES (?, ?, ?, ?)',
              (data['name'], data['size'], int(data['qty']), float(data['price'])))
    item_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'id': item_id, 'message': 'Item created'}), 201

@app.route('/api/sc/items/<int:item_id>', methods=['PUT'])
def sc_update_item(item_id):
    data = request.get_json()
    conn = get_db()
    c = conn.cursor()
    if not c.execute('SELECT id FROM sc_items WHERE id = ?', (item_id,)).fetchone():
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    c.execute('UPDATE sc_items SET name=?, size=?, price=? WHERE id=?',
              (data['name'], data['size'], float(data['price']), item_id))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Item updated'})

@app.route('/api/sc/items/<int:item_id>', methods=['DELETE'])
def sc_delete_item(item_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE sc_items SET is_hidden = 1 WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Item hidden'})

@app.route('/api/sc/takes/<int:entry_id>', methods=['DELETE'])
def sc_delete_take(entry_id):
    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT * FROM sc_takes WHERE id = ?', (entry_id,)).fetchone()
    if row:
        c.execute('UPDATE sc_items SET qty = qty + ? WHERE id = ?', (row['qty_taken'], row['item_id']))
        c.execute('DELETE FROM sc_takes WHERE id = ?', (entry_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Log entry removed and stock restored'})

@app.route('/api/sc/takes/<int:entry_id>/remove', methods=['DELETE'])
def sc_remove_take(entry_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM sc_takes WHERE id = ?', (entry_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Log entry removed'})

@app.route('/api/sc/adds/<int:entry_id>', methods=['DELETE'])
def sc_delete_add(entry_id):
    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT * FROM sc_adds WHERE id = ?', (entry_id,)).fetchone()
    if row:
        c.execute('UPDATE sc_items SET qty = MAX(0, qty - ?) WHERE id = ?', (row['qty_added'], row['item_id']))
        c.execute('DELETE FROM sc_adds WHERE id = ?', (entry_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Log entry removed and stock adjusted'})

@app.route('/api/sc/adds/<int:entry_id>/remove', methods=['DELETE'])
def sc_remove_add(entry_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM sc_adds WHERE id = ?', (entry_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Log entry removed'})

@app.route('/api/sc/archived', methods=['GET'])
def sc_get_archived():
    conn = get_db()
    c = conn.cursor()
    rows = c.execute('SELECT * FROM sc_items WHERE is_hidden = 1 ORDER BY name ASC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/sc/items/<int:item_id>/restore', methods=['POST'])
def sc_restore_item(item_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE sc_items SET is_hidden = 0 WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Item restored'})

@app.route('/api/sc/add', methods=['POST'])
def sc_add_stock():
    data = request.get_json()
    item_id = data.get('item_id')
    qty = int(data.get('qty', 0))
    if not item_id or qty <= 0:
        return jsonify({'error': 'Invalid item_id or qty'}), 400
    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT * FROM sc_items WHERE id = ?', (item_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Item not found'}), 404
    unit_price = row['price']
    total_price = unit_price * qty
    c.execute('UPDATE sc_items SET qty = qty + ? WHERE id = ?', (qty, item_id))
    c.execute('INSERT INTO sc_adds (item_id, item_name, item_size, qty_added, unit_price, total_price) VALUES (?, ?, ?, ?, ?, ?)',
              (item_id, row['name'], row['size'], qty, unit_price, total_price))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Stock added', 'total_price': total_price})

@app.route('/api/sc/take', methods=['POST'])
def sc_take_item():
    data = request.get_json()
    item_id = data.get('item_id')
    qty = int(data.get('qty', 0))
    if not item_id or qty <= 0:
        return jsonify({'error': 'Invalid item_id or qty'}), 400
    conn = get_db()
    c = conn.cursor()
    row = c.execute('SELECT * FROM sc_items WHERE id = ?', (item_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'Item not found'}), 404
    if row['qty'] < qty:
        conn.close()
        return jsonify({'error': 'Insufficient quantity'}), 400
    unit_price = row['price']
    total_price = unit_price * qty
    c.execute('UPDATE sc_items SET qty = qty - ? WHERE id = ?', (qty, item_id))
    c.execute('INSERT INTO sc_takes (item_id, item_name, item_size, qty_taken, unit_price, total_price) VALUES (?, ?, ?, ?, ?, ?)',
              (item_id, row['name'], row['size'], qty, unit_price, total_price))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Items taken', 'total_price': total_price})

@app.route('/api/sc/takes', methods=['GET'])
def sc_get_takes():
    conn = get_db()
    c = conn.cursor()
    takes = c.execute('SELECT id, item_name, item_size, qty_taken AS qty, unit_price, total_price, taken_at AS event_at, "take" AS type FROM sc_takes').fetchall()
    adds = c.execute('SELECT id, item_name, item_size, qty_added AS qty, unit_price, total_price, added_at AS event_at, "add" AS type FROM sc_adds').fetchall()
    combined = [dict(r) for r in takes] + [dict(r) for r in adds]
    combined.sort(key=lambda x: x['event_at'], reverse=True)
    conn.close()
    return jsonify(combined)

@app.route('/api/sc/stats', methods=['GET'])
def sc_get_stats():
    conn = get_db()
    c = conn.cursor()
    total_items = c.execute('SELECT COUNT(*) FROM sc_items WHERE is_hidden = 0').fetchone()[0]
    total_qty = c.execute('SELECT COALESCE(SUM(qty), 0) FROM sc_items WHERE is_hidden = 0').fetchone()[0]
    total_value = c.execute('SELECT COALESCE(SUM(qty * price), 0) FROM sc_items WHERE is_hidden = 0').fetchone()[0]
    now = datetime.now()
    month_start = f"{now.year}-{now.month:02d}-01"
    value_taken_month = c.execute(
        "SELECT COALESCE(SUM(total_price), 0) FROM sc_takes WHERE taken_at >= ?", (month_start,)
    ).fetchone()[0]
    conn.close()
    return jsonify({
        'total_items': total_items,
        'total_qty': total_qty,
        'total_value': total_value,
        'value_taken_month': value_taken_month
    })

# ── PRODUCT PRICES API ───────────────────────────────────────────────────────

@app.route('/api/pp/items', methods=['GET'])
def pp_get_items():
    conn = get_db()
    c = conn.cursor()
    search = request.args.get('search', '').strip()
    ptype  = request.args.get('type', '').strip()
    conditions = ['is_hidden = 0']
    params = []
    if search:
        conditions.append('(model LIKE ? OR code LIKE ?)')
        params += [f'%{search}%', f'%{search}%']
    if ptype:
        conditions.append('product_type = ?')
        params.append(ptype)
    where = 'WHERE ' + ' AND '.join(conditions)
    rows = c.execute(f'SELECT * FROM pp_items {where} ORDER BY model ASC', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/pp/types', methods=['GET'])
def pp_get_types():
    conn = get_db()
    c = conn.cursor()
    rows = c.execute("SELECT DISTINCT product_type FROM pp_items WHERE is_hidden=0 AND product_type != '' ORDER BY product_type").fetchall()
    conn.close()
    return jsonify([r[0] for r in rows])

@app.route('/api/pp/items', methods=['POST'])
def pp_create_item():
    data = request.get_json()
    if not data.get('model'):
        return jsonify({'error': 'Model is required'}), 400
    conn = get_db()
    c = conn.cursor()
    from datetime import datetime as dt
    c.execute(
        'INSERT INTO pp_items (code, model, product_type, supplier_price, custom_markup, created_at) VALUES (?,?,?,?,?,?)',
        (data.get('code',''), data['model'], data.get('product_type',''),
         float(data.get('supplier_price', 0)), float(data.get('custom_markup', 35)),
         dt.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
    )
    item_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({'id': item_id, 'message': 'Item created'}), 201

@app.route('/api/pp/items/<int:item_id>', methods=['PUT'])
def pp_update_item(item_id):
    data = request.get_json()
    conn = get_db()
    c = conn.cursor()
    if not c.execute('SELECT id FROM pp_items WHERE id=?', (item_id,)).fetchone():
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    c.execute(
        'UPDATE pp_items SET code=?, model=?, product_type=?, supplier_price=?, custom_markup=? WHERE id=?',
        (data.get('code',''), data['model'], data.get('product_type',''),
         float(data.get('supplier_price', 0)), float(data.get('custom_markup', 35)), item_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'message': 'Item updated'})

@app.route('/api/pp/items/<int:item_id>', methods=['DELETE'])
def pp_hide_item(item_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE pp_items SET is_hidden=1 WHERE id=?', (item_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Item hidden'})

@app.route('/api/pp/archived', methods=['GET'])
def pp_get_archived():
    conn = get_db()
    c = conn.cursor()
    rows = c.execute('SELECT * FROM pp_items WHERE is_hidden=1 ORDER BY model ASC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/pp/items/<int:item_id>/restore', methods=['POST'])
def pp_restore_item(item_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE pp_items SET is_hidden=0 WHERE id=?', (item_id,))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Item restored'})


# ── COMPUTER PERIPHERALS API ─────────────────────────────────────────────────

@app.route('/api/cp/items', methods=['GET'])
def cp_get_items():
    conn = get_db(); c = conn.cursor()
    search = request.args.get('search', '').strip()
    ptype  = request.args.get('type', '').strip()
    conditions = ['is_hidden = 0']
    params = []
    if search:
        conditions.append('(name LIKE ? OR type LIKE ?)')
        params += [f'%{search}%', f'%{search}%']
    if ptype:
        conditions.append('type = ?')
        params.append(ptype)
    where = 'WHERE ' + ' AND '.join(conditions)
    rows = c.execute(f'SELECT * FROM cp_items {where} ORDER BY name ASC', params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/cp/types', methods=['GET'])
def cp_get_types():
    conn = get_db(); c = conn.cursor()
    rows = c.execute("SELECT DISTINCT type FROM cp_items WHERE is_hidden=0 AND type != '' ORDER BY type").fetchall()
    conn.close()
    return jsonify([r[0] for r in rows])

@app.route('/api/cp/items', methods=['POST'])
def cp_create_item():
    data = request.get_json()
    for field in ['name', 'type', 'qty', 'price']:
        if field not in data:
            return jsonify({'error': f'Missing field: {field}'}), 400
    from datetime import datetime as dt
    conn = get_db(); c = conn.cursor()
    c.execute('INSERT INTO cp_items (name, type, qty, price, created_at) VALUES (?,?,?,?,?)',
              (data['name'], data['type'], int(data['qty']), float(data['price']),
               dt.utcnow().strftime('%Y-%m-%d %H:%M:%S')))
    item_id = c.lastrowid; conn.commit(); conn.close()
    return jsonify({'id': item_id, 'message': 'Item created'}), 201

@app.route('/api/cp/items/<int:item_id>', methods=['PUT'])
def cp_update_item(item_id):
    data = request.get_json()
    conn = get_db(); c = conn.cursor()
    if not c.execute('SELECT id FROM cp_items WHERE id = ?', (item_id,)).fetchone():
        conn.close(); return jsonify({'error': 'Not found'}), 404
    c.execute('UPDATE cp_items SET name=?, type=?, price=? WHERE id=?',
              (data['name'], data['type'], float(data['price']), item_id))
    conn.commit(); conn.close()
    return jsonify({'message': 'Item updated'})

@app.route('/api/cp/items/<int:item_id>', methods=['DELETE'])
def cp_hide_item(item_id):
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE cp_items SET is_hidden = 1 WHERE id = ?', (item_id,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Item hidden'})

@app.route('/api/cp/archived', methods=['GET'])
def cp_get_archived():
    conn = get_db(); c = conn.cursor()
    rows = c.execute('SELECT * FROM cp_items WHERE is_hidden = 1 ORDER BY name ASC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/cp/items/<int:item_id>/restore', methods=['POST'])
def cp_restore_item(item_id):
    conn = get_db(); c = conn.cursor()
    c.execute('UPDATE cp_items SET is_hidden = 0 WHERE id = ?', (item_id,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Item restored'})

@app.route('/api/cp/add', methods=['POST'])
def cp_add_stock():
    data = request.get_json()
    item_id = data.get('item_id'); qty = int(data.get('qty', 0))
    if not item_id or qty <= 0: return jsonify({'error': 'Invalid'}), 400
    from datetime import datetime as dt
    conn = get_db(); c = conn.cursor()
    row = c.execute('SELECT * FROM cp_items WHERE id = ?', (item_id,)).fetchone()
    if not row: conn.close(); return jsonify({'error': 'Not found'}), 404
    tp = row['price'] * qty
    c.execute('UPDATE cp_items SET qty = qty + ? WHERE id = ?', (qty, item_id))
    c.execute('INSERT INTO cp_adds (item_id,item_name,item_type,qty_added,unit_price,total_price,added_at) VALUES (?,?,?,?,?,?,?)',
              (item_id, row['name'], row['type'], qty, row['price'], tp, dt.utcnow().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit(); conn.close()
    return jsonify({'message': 'Stock added', 'total_price': tp})

@app.route('/api/cp/take', methods=['POST'])
def cp_take_item():
    data = request.get_json()
    item_id = data.get('item_id'); qty = int(data.get('qty', 0))
    if not item_id or qty <= 0: return jsonify({'error': 'Invalid'}), 400
    from datetime import datetime as dt
    conn = get_db(); c = conn.cursor()
    row = c.execute('SELECT * FROM cp_items WHERE id = ?', (item_id,)).fetchone()
    if not row: conn.close(); return jsonify({'error': 'Not found'}), 404
    if row['qty'] < qty: conn.close(); return jsonify({'error': 'Insufficient quantity'}), 400
    tp = row['price'] * qty
    c.execute('UPDATE cp_items SET qty = qty - ? WHERE id = ?', (qty, item_id))
    c.execute('INSERT INTO cp_takes (item_id,item_name,item_type,qty_taken,unit_price,total_price,taken_at) VALUES (?,?,?,?,?,?,?)',
              (item_id, row['name'], row['type'], qty, row['price'], tp, dt.utcnow().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit(); conn.close()
    return jsonify({'message': 'Items taken', 'total_price': tp})

@app.route('/api/cp/takes', methods=['GET'])
def cp_get_takes():
    conn = get_db(); c = conn.cursor()
    takes = c.execute('SELECT id,item_name,item_type,qty_taken AS qty,unit_price,total_price,taken_at AS event_at,"take" AS type FROM cp_takes').fetchall()
    adds  = c.execute('SELECT id,item_name,item_type,qty_added AS qty,unit_price,total_price,added_at AS event_at,"add" AS type FROM cp_adds').fetchall()
    combined = [dict(r) for r in takes] + [dict(r) for r in adds]
    combined.sort(key=lambda x: x['event_at'] or '', reverse=True)
    conn.close()
    return jsonify(combined)

@app.route('/api/cp/takes/<int:eid>', methods=['DELETE'])
def cp_undo_take(eid):
    conn = get_db(); c = conn.cursor()
    row = c.execute('SELECT * FROM cp_takes WHERE id=?', (eid,)).fetchone()
    if row:
        c.execute('UPDATE cp_items SET qty=qty+? WHERE id=?', (row['qty_taken'], row['item_id']))
        c.execute('DELETE FROM cp_takes WHERE id=?', (eid,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Undone'})

@app.route('/api/cp/takes/<int:eid>/remove', methods=['DELETE'])
def cp_remove_take(eid):
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM cp_takes WHERE id=?', (eid,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Removed'})

@app.route('/api/cp/adds/<int:eid>', methods=['DELETE'])
def cp_undo_add(eid):
    conn = get_db(); c = conn.cursor()
    row = c.execute('SELECT * FROM cp_adds WHERE id=?', (eid,)).fetchone()
    if row:
        c.execute('UPDATE cp_items SET qty=MAX(0,qty-?) WHERE id=?', (row['qty_added'], row['item_id']))
        c.execute('DELETE FROM cp_adds WHERE id=?', (eid,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Undone'})

@app.route('/api/cp/adds/<int:eid>/remove', methods=['DELETE'])
def cp_remove_add(eid):
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM cp_adds WHERE id=?', (eid,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Removed'})

@app.route('/api/cp/stats', methods=['GET'])
def cp_get_stats():
    conn = get_db(); c = conn.cursor()
    ti = c.execute('SELECT COUNT(*) FROM cp_items WHERE is_hidden=0').fetchone()[0]
    tq = c.execute('SELECT COALESCE(SUM(qty),0) FROM cp_items WHERE is_hidden=0').fetchone()[0]
    tv = c.execute('SELECT COALESCE(SUM(qty*price),0) FROM cp_items WHERE is_hidden=0').fetchone()[0]
    now = datetime.now()
    ms = f"{now.year}-{now.month:02d}-01"
    vtm = c.execute("SELECT COALESCE(SUM(total_price),0) FROM cp_takes WHERE taken_at>=?", (ms,)).fetchone()[0]
    conn.close()
    return jsonify({'total_items':ti,'total_qty':tq,'total_value':tv,'value_taken_month':vtm})

# CASH FLOW / TRANSACTIONS API

def date_range_from_request():
    period = request.args.get('period', 'month').strip()
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()
    today_d = date.today()
    if period == 'day':
        target = date_from or today_d.strftime('%Y-%m-%d')
        return target, target
    if period == 'week':
        start = today_d
        if date_from:
            try:
                start = datetime.strptime(date_from, '%Y-%m-%d').date()
            except ValueError:
                start = today_d
        start = start - timedelta(days=start.weekday())
        end = start + timedelta(days=6)
        return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')
    if period == 'custom':
        return date_from or None, date_to or None
    if period == 'all':
        return None, None
    start = date(today_d.year, today_d.month, 1)
    if date_from:
        try:
            picked = datetime.strptime(date_from, '%Y-%m-%d').date()
            start = date(picked.year, picked.month, 1)
        except ValueError:
            pass
    end_day = calendar.monthrange(start.year, start.month)[1]
    return start.strftime('%Y-%m-%d'), date(start.year, start.month, end_day).strftime('%Y-%m-%d')

def filter_by_date(rows, date_key, date_from, date_to):
    filtered = []
    for row in rows:
        d = (row.get(date_key) or '').split(' ')[0].split('T')[0]
        if date_from and d < date_from:
            continue
        if date_to and d > date_to:
            continue
        filtered.append(row)
    return filtered

def cashflow_summary(rows):
    income = sum(float(r['amount']) for r in rows if r['transaction_type'] == 'income')
    expenses = sum(float(r['amount']) for r in rows if r['transaction_type'] == 'expense')
    return {'income': income, 'expenses': expenses, 'net_profit': income - expenses}

def get_cashflow_rows(conn, date_from=None, date_to=None, category=None, source='manual'):
    c = conn.cursor()
    conditions, params = [], []
    if date_from:
        conditions.append('transaction_date >= ?')
        params.append(date_from)
    if date_to:
        conditions.append('transaction_date <= ?')
        params.append(date_to)
    if category:
        conditions.append('category = ?')
        params.append(category)
    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    manual = c.execute(f'''
        SELECT id, transaction_type, amount, category, description,
               transaction_date, created_at, 'manual' AS source
        FROM transactions {where}
    ''', params).fetchall()
    rows = [dict(r) for r in manual]
    rows.sort(key=lambda r: ((r.get('transaction_date') or ''), (r.get('created_at') or '')), reverse=True)
    return rows

@app.route('/api/transaction-categories', methods=['GET'])
def get_transaction_categories():
    conn = get_db(); c = conn.cursor()
    rows = c.execute('SELECT id, name FROM transaction_categories ORDER BY name COLLATE NOCASE ASC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/transaction-categories', methods=['POST'])
def create_transaction_category():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Category name is required.'}), 400
    conn = get_db(); c = conn.cursor()
    existing = c.execute(
        'SELECT id, name FROM transaction_categories WHERE name = ? COLLATE NOCASE', (name,)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({'id': existing['id'], 'name': existing['name'], 'message': 'Category already exists'}), 200
    c.execute('INSERT INTO transaction_categories (name) VALUES (?)', (name,))
    cat_id = c.lastrowid
    conn.commit(); conn.close()
    return jsonify({'id': cat_id, 'name': name, 'message': 'Category added'}), 201

@app.route('/api/transaction-categories/<int:category_id>', methods=['DELETE'])
def delete_transaction_category(category_id):
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM transaction_categories WHERE id = ?', (category_id,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Category removed'})

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    date_from, date_to = date_range_from_request()
    category = request.args.get('category', '').strip()
    conn = get_db()
    rows = get_cashflow_rows(conn, date_from, date_to, category)
    today_s = date.today().strftime('%Y-%m-%d')
    month_s = f"{date.today().year}-{date.today().month:02d}-01"
    daily_rows = get_cashflow_rows(conn, today_s, today_s, category)
    monthly_rows = get_cashflow_rows(conn, month_s, None, category)
    conn.close()
    return jsonify({
        'range': {'from': date_from, 'to': date_to},
        'category': category,
        'summary': cashflow_summary(rows),
        'daily': cashflow_summary(daily_rows),
        'monthly': cashflow_summary(monthly_rows),
        'transactions': rows
    })

@app.route('/api/transactions', methods=['POST'])
def create_transaction():
    data = request.get_json()
    tx_type = data.get('transaction_type')
    amount = float(data.get('amount', 0))
    if tx_type not in ('income', 'expense') or amount <= 0:
        return jsonify({'error': 'Enter a valid income or expense amount.'}), 400
    tx_date = data.get('transaction_date') or date.today().strftime('%Y-%m-%d')
    conn = get_db(); c = conn.cursor()
    c.execute('''
        INSERT INTO transactions (transaction_type, amount, category, description, transaction_date)
        VALUES (?, ?, ?, ?, ?)
    ''', (tx_type, amount, data.get('category', ''), data.get('description', ''), tx_date))
    item_id = c.lastrowid
    conn.commit(); conn.close()
    return jsonify({'id': item_id, 'message': 'Transaction saved'}), 201

@app.route('/api/transactions/<int:transaction_id>', methods=['PUT'])
def update_transaction(transaction_id):
    data = request.get_json()
    tx_type = data.get('transaction_type')
    amount = float(data.get('amount', 0))
    if tx_type not in ('income', 'expense') or amount <= 0:
        return jsonify({'error': 'Enter a valid income or expense amount.'}), 400
    conn = get_db(); c = conn.cursor()
    if not c.execute('SELECT id FROM transactions WHERE id = ?', (transaction_id,)).fetchone():
        conn.close(); return jsonify({'error': 'Not found'}), 404
    c.execute('''
        UPDATE transactions
        SET transaction_type=?, amount=?, category=?, description=?, transaction_date=?
        WHERE id=?
    ''', (tx_type, amount, data.get('category', ''), data.get('description', ''),
          data.get('transaction_date') or date.today().strftime('%Y-%m-%d'), transaction_id))
    conn.commit(); conn.close()
    return jsonify({'message': 'Transaction updated'})

@app.route('/api/transactions/<int:transaction_id>', methods=['DELETE'])
def delete_transaction(transaction_id):
    conn = get_db(); c = conn.cursor()
    c.execute('DELETE FROM transactions WHERE id = ?', (transaction_id,))
    conn.commit(); conn.close()
    return jsonify({'message': 'Transaction deleted'})

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    return send_from_directory('public', 'index.html')

def port_is_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            return True
        except OSError:
            return False


def choose_port():
    """Prefer port 80 (so URLs need no :port at all). If something else is
    already using 80 (e.g. IIS), fall back to 8080 instead of crashing."""
    if port_is_free(80):
        return 80
    return 8080


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


if __name__ == "__main__":
    from waitress import serve
    init_db()
    port = choose_port()
    port_suffix = "" if port == 80 else f":{port}"
    local_url = f"http://localhost{port_suffix}"
    lan_ip = get_lan_ip()

    print("=" * 50)
    print("  WarrantIQ - Warranty Tracker is starting...")
    print(f"  On this computer:  {local_url}")
    if lan_ip:
        print(f"  From other devices on your network: http://{lan_ip}{port_suffix}")
    if port != 80:
        print("  Note: port 80 was already in use on this PC, so the app")
        print("  is using port 8080 instead - just include :8080 above.")
    print("  Your browser will open automatically.")
    print("  To stop the app, just close this window.")
    print("=" * 50)

    threading.Timer(1.2, lambda: webbrowser.open(local_url)).start()
    serve(app, host="0.0.0.0", port=port)
