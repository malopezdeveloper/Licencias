"""PULSIA Licencias: stock local, API HTTPS y administración transaccional."""
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import ssl
import sys
import uuid
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import PurePosixPath

from clasificacion import UNKNOWN, EDITIONS, CHANNELS, metadata, normalize_reference, edition_from_text

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('PULSIA_LICENSE_DATA', str(ROOT / 'datos'))).resolve()
KEY_PATTERN = re.compile(r'[A-Z0-9]{5}(?:-[A-Z0-9]{5}){4}')
ACTIVE_STATES = ('pendiente', 'usada', 'revision')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def parse_xml(raw):
    if len(raw) > 1048576:
        raise ValueError('XML demasiado grande (máximo 1 MiB).')
    # ElementTree no resuelve entidades externas. Rechazar también DTD internos,
    # incluidos documentos UTF-16, antes de parsear.
    text = raw.decode('utf-8-sig') if isinstance(raw, bytes) and not raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw
    if isinstance(text, bytes):
        text = text.decode('utf-16')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('No se admiten DTD ni entidades XML.')
    root = ET.fromstring(text)
    keys = [(n.text or '').strip().upper() for n in root.iter() if n.tag.split('}')[-1] == 'ProductKey']
    if len(keys) != 1 or not KEY_PATTERN.fullmatch(keys[0]):
        raise ValueError('El XML debe contener una única ProductKey válida.')
    return ET.tostring(root, encoding='unicode'), keys[0]


def validate_machine(value):
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('UUID del equipo no válido.') from None
    if parsed.int in (0, 2**128 - 1):
        raise ValueError('UUID genérico no admitido.')
    return str(parsed).upper()


class TechnicianError(ValueError):
    pass


class Stock:
    def __init__(self, directory=DATA):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / 'licencias.db'
        self.config_path = self.directory / 'servidor.json'
        with self.connection() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS licenses (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, xml TEXT NOT NULL,
                fingerprint TEXT UNIQUE NOT NULL, suffix TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS technicians (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT UNIQUE NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY, license_id INTEGER NOT NULL REFERENCES licenses(id),
                machine TEXT NOT NULL, info TEXT NOT NULL, state TEXT NOT NULL,
                created TEXT NOT NULL, updated TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '{}', technician_id INTEGER REFERENCES technicians(id));
            CREATE UNIQUE INDEX IF NOT EXISTS active_license ON assignments(license_id) WHERE state!='baja';
            CREATE UNIQUE INDEX IF NOT EXISTS active_machine ON assignments(machine) WHERE state!='baja';
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, date TEXT, assignment TEXT, action TEXT, detail TEXT);
            ''')
            # Compatibilidad con la base v0.1: copiarla a datos antes del primer arranque.
            existing = {r['name'] for r in c.execute('PRAGMA table_info(licenses)')}
            for name, definition in [('suffix', "TEXT NOT NULL DEFAULT ''"), ('enabled', 'INTEGER NOT NULL DEFAULT 1'), ('created', "TEXT NOT NULL DEFAULT ''")]:
                if name not in existing:
                    c.execute(f'ALTER TABLE licenses ADD COLUMN {name} {definition}')
            c.execute('CREATE TABLE IF NOT EXISTS classification_rules (reference TEXT PRIMARY KEY, edition TEXT NOT NULL, channel TEXT NOT NULL, updated TEXT NOT NULL)')
            for name in ('edition', 'channel', 'reference', 'classification_source'):
                if name not in existing:
                    c.execute(f"ALTER TABLE licenses ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            for row in c.execute("SELECT id,xml FROM licenses WHERE classification_source='' ").fetchall():
                values = self.classify(c, row['xml'])
                c.execute('UPDATE licenses SET edition=?,channel=?,reference=?,classification_source=? WHERE id=?',
                          (values['edition'], values['channel'], values['reference'], values['classification_source'], row['id']))
            if 'technician_id' not in {r['name'] for r in c.execute('PRAGMA table_info(assignments)')}:
                c.execute('ALTER TABLE assignments ADD COLUMN technician_id INTEGER REFERENCES technicians(id)')
            if 'result' not in {r['name'] for r in c.execute('PRAGMA table_info(assignments)')}:
                c.execute("ALTER TABLE assignments ADD COLUMN result TEXT NOT NULL DEFAULT '{}'")
            for row in c.execute("SELECT id,xml FROM licenses WHERE suffix='' ").fetchall():
                _, key = parse_xml(row['xml'])
                c.execute('UPDATE licenses SET suffix=? WHERE id=?', (key[-5:], row['id']))
        if not self.config_path.exists():
            # x evita sobrescribir credenciales si dos procesos arrancan a la vez.
            try:
                with self.config_path.open('x', encoding='utf-8') as f:
                    json.dump({'client_token': secrets.token_urlsafe(32), 'host': '0.0.0.0',
                               'port': 8443, 'url': 'https://almacen:8443',
                               'cert': '', 'key': ''}, f, indent=2)
                self.config_path.chmod(0o600)
            except FileExistsError:
                pass

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:
                yield c
        finally:
            c.close()

    def config(self):
        return {'host': '0.0.0.0', 'port': 8443, 'url': 'https://almacen:8443', 'cert': '', 'key': '', 'ca': '',
                **json.loads(self.config_path.read_text(encoding='utf-8-sig'))}

    def save_config(self, config):
        if not 1 <= int(config['port']) <= 65535:
            raise ValueError('Puerto fuera de rango.')
        target = self.config_path.with_suffix('.tmp')
        with target.open('w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        target.chmod(0o600)
        target.replace(self.config_path)

    @staticmethod
    def event(c, assignment, action, detail=''):
        c.execute('INSERT INTO events(date,assignment,action,detail) VALUES(?,?,?,?)',
                  (now(), assignment, action, detail))

    @staticmethod
    def classify(c, xml):
        values = metadata(xml)
        rule = c.execute('SELECT edition,channel FROM classification_rules WHERE reference=?', (values['reference'],)).fetchone()
        if rule:
            values.update(dict(rule))
            values['classification_source'] = 'Regla por referencia'
        return values

    def import_files(self, paths):
        """Mezcla de XML/ZIP/carpetas; límites al descomprimir, sin extraer al disco."""
        results = []
        count = 0
        total_bytes = 0
        seen_directories = set()

        def error(name, message):
            results.append((str(name), 'error: ' + message))

        def import_one(name, raw):
            nonlocal count, total_bytes
            count += 1
            total_bytes += len(raw)
            if count > 10000 or total_bytes > 256 * 1024 * 1024:
                raise ValueError('Límite de importación: 10.000 XML o 256 MiB descomprimidos. Divida el lote.')
            try:
                if Path(name).stem.upper().endswith('BURN'):
                    raise ValueError('BURN omitido: la licencia figura como consumida.')
                xml, key = parse_xml(raw)
                with self.connection() as c:
                    values = self.classify(c, xml)
                    cur = c.execute('INSERT OR IGNORE INTO licenses(name,xml,fingerprint,suffix,created,edition,channel,reference,classification_source) VALUES(?,?,?,?,?,?,?,?,?)',
                                    (Path(name).name, xml, hashlib.sha256(key.encode()).hexdigest(), key[-5:], now(),
                                     values['edition'], values['channel'], values['reference'], values['classification_source']))
                    if cur.rowcount:
                        self.event(c, '', 'importacion', f"Licencia #{cur.lastrowid}; {values['edition']} / {values['channel']}")
                    results.append((str(name), 'importado' if cur.rowcount else 'duplicado'))
            except (ValueError, ET.ParseError) as e:
                error(name, str(e) if isinstance(e, ValueError) and not isinstance(e, UnicodeError) else 'XML no válido.')

        def visit(path):
            if path.is_symlink():
                error(path.name, 'No se siguen enlaces simbólicos.')
                return
            if path.is_dir():
                resolved = path.resolve()
                if resolved in seen_directories:
                    return
                seen_directories.add(resolved)
                try:
                    for child in sorted(path.iterdir()):
                        visit(child)
                except OSError:
                    error(path.name, 'No se pudo leer la carpeta.')
            elif path.suffix.lower() == '.xml':
                try:
                    with path.open('rb') as f:
                        import_one(path.name, f.read(1048577))
                except OSError:
                    error(path.name, 'No se pudo leer el archivo.')
            elif path.suffix.lower() == '.zip':
                try:
                    with zipfile.ZipFile(path) as archive:
                        members = archive.infolist()
                        if len(members) > 20000:
                            raise ValueError('ZIP con demasiadas entradas (máximo 20.000).')
                        for member in members:
                            name = member.filename.replace('\\', '/')
                            parts = PurePosixPath(name)
                            if member.is_dir() or parts.suffix.lower() != '.xml':
                                continue
                            if parts.is_absolute() or '..' in parts.parts or ':' in name or ((member.external_attr >> 16) & 0o170000) == 0o120000:
                                error(path.name + '/' + name, 'Ruta ZIP no admitida.')
                                continue
                            if member.flag_bits & 1 or member.file_size > 1048576:
                                error(path.name + '/' + name, 'XML cifrado o demasiado grande.')
                                continue
                            try:
                                with archive.open(member) as f:
                                    import_one(path.name + '/' + name, f.read(1048577))
                            except (OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
                                error(path.name + '/' + name, 'No se pudo leer esta entrada del ZIP.')
                except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as e:
                    if isinstance(e, ValueError) and str(e).startswith('Límite de importación'):
                        raise
                    error(path.name, 'ZIP no válido o no admitido.')
            # Otros archivos y ZIP anidados dentro de ZIP no se importan.

        try:
            for item in paths:
                visit(Path(item))
        except ValueError as e:
            error('Lote', str(e))
        return results

    def set_classification(self, license_id, edition, channel, apply_reference=False):
        if edition not in EDITIONS or channel not in CHANNELS:
            raise ValueError('Edición o tipo no válido.')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT reference FROM licenses WHERE id=?', (license_id,)).fetchone()
            if not row:
                raise ValueError('Licencia inexistente.')
            if apply_reference:
                if not row['reference']:
                    raise ValueError('El XML no tiene referencia; clasifique esta licencia individualmente.')
                c.execute('INSERT INTO classification_rules(reference,edition,channel,updated) VALUES(?,?,?,?) ON CONFLICT(reference) DO UPDATE SET edition=excluded.edition,channel=excluded.channel,updated=excluded.updated',
                          (row['reference'], edition, channel, now()))
                cur = c.execute("UPDATE licenses SET edition=?,channel=?,classification_source='Regla por referencia' WHERE reference=?",
                                (edition, channel, row['reference']))
            else:
                cur = c.execute("UPDATE licenses SET edition=?,channel=?,classification_source='Manual' WHERE id=?", (edition, channel, license_id))
            self.event(c, '', 'clasificacion', f"Licencia #{license_id}; {edition} / {channel}; actualizadas: {cur.rowcount}")
            return cur.rowcount

    def license_details(self, license_id):
        with self.connection() as c:
            row = c.execute('SELECT * FROM licenses WHERE id=?', (license_id,)).fetchone()
            if not row:
                raise ValueError('Licencia inexistente.')
            result = dict(row)
            result['xml_state'] = metadata(result.pop('xml'))['xml_state']
            result.pop('fingerprint', None)
            return result

    def inventory(self):
        with self.connection() as c:
            return [dict(r) for r in c.execute('''SELECT l.id,l.name,l.suffix,l.enabled,l.created,l.edition,l.channel,l.reference,l.classification_source,
                a.id AS assignment,a.machine,a.info,a.updated,
                CASE WHEN a.id IS NOT NULL THEN a.state WHEN l.enabled=0 THEN 'retirada' WHEN l.edition='Sin identificar' OR l.channel='Sin identificar' THEN 'sin identificar' ELSE 'disponible' END AS state
                FROM licenses l LEFT JOIN assignments a ON a.license_id=l.id AND a.state!='baja' ORDER BY l.id''')]

    def availability(self):
        """Resumen sin claves ni datos de equipos; una única consulta consistente."""
        with self.connection() as c:
            groups = [dict(row) for row in c.execute("""
                SELECT l.edition,l.channel,
                    SUM(CASE WHEN l.enabled=1 AND a.id IS NULL THEN 1 ELSE 0 END) AS available
                FROM licenses l LEFT JOIN assignments a ON a.license_id=l.id AND a.state!='baja'
                WHERE l.edition!=? AND l.channel!=?
                GROUP BY l.edition,l.channel ORDER BY l.edition,l.channel
            """, (UNKNOWN, UNKNOWN))]
        return {'available': sum(row['available'] for row in groups), 'groups': groups, 'updated': now()}

    def assignments(self):
        with self.connection() as c:
            return [dict(r) for r in c.execute('''SELECT a.*,l.name,l.suffix,l.edition,l.channel,l.reference FROM assignments a
                JOIN licenses l ON l.id=a.license_id ORDER BY a.created DESC,a.id''')]

    def history(self, assignment=None):
        with self.connection() as c:
            rows = c.execute('SELECT * FROM events WHERE assignment=? ORDER BY id DESC', (assignment,)) if assignment else c.execute('SELECT * FROM events ORDER BY id DESC')
            return [dict(r) for r in rows]

    def toggle(self, license_id, enabled):
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT id FROM licenses WHERE id=?', (license_id,)).fetchone()
            if not row:
                raise ValueError('Licencia inexistente.')
            if c.execute("SELECT 1 FROM assignments WHERE license_id=? AND state!='baja'", (license_id,)).fetchone():
                raise ValueError('Primero dé de baja su asignación activa.')
            c.execute('UPDATE licenses SET enabled=? WHERE id=?', (int(enabled), license_id))
            self.event(c, '', 'stock', f'Licencia #{license_id}: ' + ('habilitada' if enabled else 'retirada'))

    @staticmethod
    def technician_name(value):
        if not isinstance(value, str) or any(unicodedata.category(ch).startswith('C') for ch in value):
            raise ValueError('Nombre de usuario no válido.')
        name = ' '.join(unicodedata.normalize('NFC', value).split())
        if not 1 <= len(name) <= 120:
            raise ValueError('El nombre debe tener entre 1 y 120 caracteres.')
        return name, name.casefold()

    def technicians(self, active_only=False):
        with self.connection() as c:
            query = "SELECT t.id,t.name,t.active,t.created,t.updated,count(a.id) AS installations FROM technicians t LEFT JOIN assignments a ON a.technician_id=t.id"
            if active_only:
                query += ' WHERE t.active=1'
            return [dict(r) for r in c.execute(query + ' GROUP BY t.id ORDER BY t.normalized_name,t.id')]

    def add_technician(self, name):
        name, normalized = self.technician_name(name)
        try:
            with self.connection() as c:
                cur = c.execute('INSERT INTO technicians(name,normalized_name,created,updated) VALUES(?,?,?,?)', (name, normalized, now(), now()))
                self.event(c, '', 'usuario_alta', f'Usuario #{cur.lastrowid}: {name}')
                return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError('Ya existe un usuario con ese nombre, incluso si está desactivado.') from None

    def edit_technician(self, technician_id, name=None, active=None):
        if name is None and active is None:
            return
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM technicians WHERE id=?', (technician_id,)).fetchone()
            if not old:
                raise ValueError('Usuario inexistente.')
            new_name, normalized = self.technician_name(name if name is not None else old['name'])
            enabled = old['active'] if active is None else int(bool(active))
            try:
                c.execute('UPDATE technicians SET name=?,normalized_name=?,active=?,updated=? WHERE id=?',
                          (new_name, normalized, enabled, now(), technician_id))
            except sqlite3.IntegrityError:
                raise ValueError('Ya existe otro usuario con ese nombre.') from None
            self.event(c, '', 'usuario_modificado', f"Usuario #{technician_id}: {old['name']} → {new_name}; {'activo' if enabled else 'inactivo'}")

    @staticmethod
    def require_technician(c, technician_id, active=True):
        if type(technician_id) is not int:
            raise TechnicianError('Seleccione un técnico de la lista del servidor. Actualice el cliente USB.')
        row = c.execute('SELECT id,name,active FROM technicians WHERE id=?', (technician_id,)).fetchone()
        if not row or (active and not row['active']):
            raise TechnicianError('El técnico ya no está disponible. Actualice la lista y seleccione uno activo.')
        return row

    def reserve(self, data, ip=''):
        machine = validate_machine(data.get('machine'))
        raw_info = data.get('info', {})
        if not isinstance(raw_info, dict):
            raise ValueError('Datos del equipo no válidos.')
        info = {k: str(raw_info.get(k, ''))[:300] for k in ('Serial', 'Fabricante', 'Modelo', 'Windows', 'Version', 'Build')}
        info['IP'] = ip
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            technician = self.require_technician(c, data.get('technician_id'))
            info['Tecnico'] = technician['name']
            info['TecnicoID'] = technician['id']
            row = c.execute("SELECT a.id,a.state,a.info,l.xml,l.name,l.edition,l.channel FROM assignments a JOIN licenses l ON l.id=a.license_id WHERE a.machine=? AND a.state!='baja'", (machine,)).fetchone()
            if row:
                if row['edition'] == UNKNOWN or row['channel'] == UNKNOWN:
                    raise ValueError('Clasifique primero la licencia ya asignada a este equipo.')
                if data.get('edition') not in (None, row['edition']) or data.get('channel') not in (None, row['channel']):
                    raise ValueError('El equipo ya tiene otra asignación activa. Revísela antes de cambiar de edición o tipo.')
                if row['state'] != 'usada':
                    snapshot = json.loads(row['info'])
                    snapshot.update({'Tecnico': technician['name'], 'TecnicoID': technician['id']})
                    c.execute('UPDATE assignments SET info=?,technician_id=?,updated=? WHERE id=?',
                              (json.dumps(snapshot, ensure_ascii=False), technician['id'], now(), row['id']))
                self.event(c, row['id'], 'reintento', f"Usuario #{technician['id']}: {technician['name']}")
                return dict(row)
            edition = data.get('edition')
            if edition is not None and edition not in EDITIONS[:-1]:
                raise ValueError('Seleccione una edición identificada.')
            if not edition:
                edition = edition_from_text(raw_info.get('Windows', ''))
            if not edition or edition == UNKNOWN:
                editions = [r[0] for r in c.execute("SELECT DISTINCT edition FROM licenses WHERE enabled=1 AND edition!=?", (UNKNOWN,))]
                if len(editions) != 1:
                    raise ValueError('Indique la edición solicitada; clasifique antes el stock sin identificar.')
                edition = editions[0]
            channel = data.get('channel')
            if channel is not None and channel not in CHANNELS[:-1]:
                raise ValueError('Tipo de licencia no válido.')
            query = "SELECT id,name,xml,edition,channel FROM licenses WHERE enabled=1 AND edition=? AND channel!=? AND id NOT IN (SELECT license_id FROM assignments WHERE state!='baja')"
            params = [edition, UNKNOWN]
            if channel:
                query += ' AND channel=?'
                params.append(channel)
            lic = c.execute(query + ' ORDER BY id LIMIT 1', params).fetchone()
            if not lic:
                return None
            aid = secrets.token_hex(24)
            c.execute('INSERT INTO assignments(id,license_id,machine,info,state,created,updated,technician_id) VALUES(?,?,?,?,?,?,?,?)',
                      (aid, lic['id'], machine, json.dumps(info, ensure_ascii=False), 'pendiente', now(), now(), technician['id']))
            self.event(c, aid, 'asignada', f"Equipo {machine}; IP {ip}; usuario #{technician['id']}: {technician['name']}")
            return {'id': aid, 'state': 'pendiente', 'xml': lic['xml'], 'name': lic['name'], 'edition': lic['edition'], 'channel': lic['channel']}

    def report(self, data):
        machine = validate_machine(data.get('machine'))
        state = data.get('state')
        if state not in ('usada', 'revision'):
            raise ValueError('Estado no válido.')
        detail = str(data.get('detail', ''))[:2000]
        # Las claves completas nunca se admiten como datos de auditoría.
        detail = KEY_PATTERN.sub('[CLAVE OCULTA]', detail)
        result = data.get('result', {})
        if not isinstance(result, dict):
            raise ValueError('Resultado no válido.')
        result = {k: str(result[k])[:200] for k in ('before_partial', 'after_partial', 'license_status', 'code', 'error') if k in result}
        result = {k: KEY_PATTERN.sub('[CLAVE OCULTA]', v) for k, v in result.items()}
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM assignments WHERE id=? AND machine=?', (data.get('id'), machine)).fetchone()
            if not row or row['state'] == 'baja':
                raise ValueError('Asignación inexistente o dada de baja.')
            if row['state'] == 'usada' and state != 'usada':
                raise ValueError('Una licencia usada no se puede degradar.')
            actor = self.require_technician(c, data['technician_id'], active=False) if 'technician_id' in data else None
            stored = json.loads(row['result'])
            # Conservar el estado anterior de la PRIMERA instalación al reintentar.
            for k, v in result.items():
                if k != 'before_partial' or k not in stored:
                    stored[k] = v
            c.execute('UPDATE assignments SET state=?,detail=?,result=?,updated=? WHERE id=?',
                      (state, detail, json.dumps(stored), now(), row['id']))
            audit = detail + (f" · Usuario #{actor['id']}: {actor['name']}" if actor else '')
            self.event(c, row['id'], state, audit)
        return {'ok': True}

    def release(self, assignment, reason):
        reason = reason.strip()
        if not reason:
            raise ValueError('Escriba un motivo para la baja.')
        with self.connection() as c:
            c.execute('BEGIN IMMEDIATE')
            cur = c.execute("UPDATE assignments SET state='baja',updated=?,detail=? WHERE id=? AND state!='baja'",
                            (now(), reason[:2000], assignment))
            if cur.rowcount != 1:
                raise ValueError('La asignación ya está de baja o no existe.')
            self.event(c, assignment, 'baja', reason[:2000])

    def backup(self, target):
        target = Path(target)
        if target.exists():
            raise ValueError('El archivo de destino ya existe; elija otro nombre.')
        # Crear de forma exclusiva: nunca sobrescribir la base ni una copia existente.
        with target.open('xb'):
            pass
        try:
            with self.connection() as source:
                dest = sqlite3.connect(target)
                try:
                    source.backup(dest)
                finally:
                    dest.close()
        except Exception:
            target.unlink(missing_ok=True)
            raise


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, fmt, *args):
        pass

    def reply(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        token = self.server.client_token
        auth = self.headers.get('Authorization', '')
        if not hmac.compare_digest(auth.encode(), ('Bearer ' + token).encode()):
            return self.reply(401, {'error': 'No autorizado'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                raise ValueError('Tamaño de solicitud no válido.')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('JSON no válido.')
            if self.path == '/reserve':
                result = self.server.stock.reserve(data, self.client_address[0])
                self.reply(200 if result else 409, result or {'error': 'Stock agotado'})
            elif self.path == '/stock':
                self.reply(200, self.server.stock.availability())
            elif self.path == '/technicians':
                self.reply(200, {'technicians': [{'id': r['id'], 'name': r['name']} for r in self.server.stock.technicians(active_only=True)]})
            elif self.path == '/report':
                self.reply(200, self.server.stock.report(data))
            else:
                self.reply(404, {'error': 'Ruta desconocida'})
        except TechnicianError as e:
            self.reply(422, {'error': str(e)})
        except (ValueError, TypeError):
            self.reply(400, {'error': 'Solicitud no válida'})
        except (OSError, TimeoutError):
            pass  # El cliente puede haberse desconectado tras confirmar la transacción.
        except Exception:
            self.reply(500, {'error': 'Error interno; reintente desde el mismo equipo.'})


class LicenseServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, stock, host, port, cert, key):
        self.stock = stock
        self.client_token = stock.config()['client_token']
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_cert_chain(cert, key)
        super().__init__((host, int(port)), Handler)

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ssl.SSLError, ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(5)
        # Negociar TLS en el hilo de la solicitud, no bloquear nuevos clientes.
        try:
            return self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), address
        except Exception:
            sock.close()
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--datos', type=Path, default=DATA)
    parser.add_argument('--servir', action='store_true')
    args = parser.parse_args()
    stock = Stock(args.datos)
    if not args.servir:
        print('Inicie servidor_gui.py para administrar el servidor.')
        return
    cfg = stock.config()
    server = LicenseServer(stock, cfg['host'], cfg['port'], cfg['cert'], cfg['key'])
    print(f"Servidor HTTPS en {cfg['host']}:{cfg['port']}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
