from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import ssl
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid

from certificados import generate
from servidor import Stock, LicenseServer, parse_xml


def machine():
    return str(uuid.uuid4())


class StockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stock = Stock(self.root / 'datos')
        self.files = []
        for i in range(5):
            path = self.root / f'{i}.xml'
            path.write_text(f'<License><ProductKey>AAAAA-BBBBB-CCCCC-DDDDD-{i:05d}</ProductKey></License>')
            self.files.append(path)
        self.stock.import_files(self.files)

    def test_parallel_clients_never_share_license(self):
        machines = [machine() for _ in range(15)]
        with ThreadPoolExecutor(max_workers=15) as pool:
            results = list(pool.map(lambda m: self.stock.reserve({'machine': m}), machines))
        assigned = [r for r in results if r]
        self.assertEqual(len(assigned), 5)
        self.assertEqual(len({r['id'] for r in assigned}), 5)
        for m, row in zip(machines, results):
            if row:
                self.assertEqual(self.stock.reserve({'machine': m})['id'], row['id'])

    def test_parallel_retries_same_machine(self):
        m = machine()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.stock.reserve({'machine': m}), range(8)))
        self.assertEqual(len({r['id'] for r in results}), 1)

    def test_duplicates_and_invalid_xml(self):
        self.assertTrue(all(status == 'duplicado' for _, status in self.stock.import_files(self.files)))
        burn = self.root / 'oldBURN.xml'
        burn.write_text(self.files[0].read_text())
        invalid = self.root / 'bad.xml'
        invalid.write_text('<x><ProductKey>secret-bad-key</ProductKey></x>')
        self.assertTrue(all(status.startswith('error:') for _, status in self.stock.import_files([burn, invalid])))
        self.assertEqual(len(self.stock.inventory()), 5)
        for raw in ['<!DOCTYPE x [<!ENTITY e "test">]><x>&e;</x>', '<x/>']:
            with self.assertRaises(ValueError):
                parse_xml(raw)
        with self.assertRaises(ValueError):
            parse_xml('<!DOCTYPE x><x/>'.encode('utf-16'))

    def test_release_reassign_preserves_audit(self):
        m = machine()
        assigned = self.stock.reserve({'machine': m, 'info': {'Serial': 'TESTSN', 'Tecnico': 'T1'}}, '127.0.0.1')
        self.stock.report({'machine': m, 'id': assigned['id'], 'state': 'usada',
                           'result': {'before_partial': 'ZZZZZ', 'after_partial': '00000'}, 'detail': 'Verificada'})
        self.stock.report({'machine': m, 'id': assigned['id'], 'state': 'usada', 'result': {'before_partial': '00000'}})
        self.assertEqual(json.loads(self.stock.assignments()[0]['result'])['before_partial'], 'ZZZZZ')
        with self.assertRaises(ValueError):
            self.stock.report({'machine': m, 'id': assigned['id'], 'state': 'revision'})
        with self.assertRaises(ValueError):
            self.stock.release(assigned['id'], '   ')
        self.stock.release(assigned['id'], 'Retirada verificada')
        self.assertEqual(len(self.stock.history(assigned['id'])), 4)
        new = self.stock.reserve({'machine': machine()})
        self.assertNotEqual(new['id'], assigned['id'])
        self.assertEqual(len(self.stock.assignments()), 2)
        with self.assertRaises(ValueError):
            self.stock.report({'machine': m, 'id': assigned['id'], 'state': 'usada'})

    def test_withdraw_and_backup(self):
        self.stock.toggle(1, False)
        assigned = self.stock.reserve({'machine': machine()})
        self.assertEqual(next(r for r in self.stock.inventory() if r['assignment'] == assigned['id'])['id'], 2)
        with self.assertRaises(ValueError):
            self.stock.toggle(2, False)
        self.stock.toggle(1, True)
        target = self.root / 'backup.db'
        self.stock.backup(target)
        with sqlite3.connect(target) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM licenses').fetchone()[0], 5)
        with self.assertRaises(ValueError):
            self.stock.backup(target)
        self.assertNotIn('xml', self.stock.inventory()[0])
        self.assertNotIn('client_token', self.stock.inventory()[0])

    def test_invalid_uuid_and_redact_full_key(self):
        for value in ('bad', str(uuid.UUID(int=0)), str(uuid.UUID(int=2**128 - 1))):
            with self.assertRaises(ValueError):
                self.stock.reserve({'machine': value})
        m = machine()
        assigned = self.stock.reserve({'machine': m})
        self.stock.report({'machine': m, 'id': assigned['id'], 'state': 'revision',
                           'detail': 'AAAAA-BBBBB-CCCCC-DDDDD-00000'})
        self.assertNotIn('AAAAA-BBBBB', self.stock.assignments()[0]['detail'])

    def test_migration_v01(self):
        old = self.root / 'v01'
        old.mkdir()
        with sqlite3.connect(old / 'licencias.db') as c:
            c.executescript('''CREATE TABLE licenses(id INTEGER PRIMARY KEY,name TEXT NOT NULL,xml TEXT NOT NULL,fingerprint TEXT UNIQUE NOT NULL);
                CREATE TABLE assignments(id TEXT PRIMARY KEY,license_id INTEGER NOT NULL REFERENCES licenses(id),machine TEXT NOT NULL,
                info TEXT NOT NULL,state TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '');''')
            c.execute('INSERT INTO licenses VALUES(1,?,?,?)', ('old.xml', self.files[0].read_text(), 'testhash'))
        (old / 'servidor.json').write_text(json.dumps({'client_token': 'old-token'}))
        upgraded = Stock(old)
        self.assertEqual(upgraded.inventory()[0]['suffix'], '00000')
        self.assertEqual(upgraded.config()['client_token'], 'old-token')
        self.assertEqual(upgraded.config()['port'], 8443)


class HttpsTests(unittest.TestCase):
    setUp = StockTests.setUp
    def test_https_end_to_end(self):
        certs = generate(self.root, 'localhost')
        server = LicenseServer(self.stock, '127.0.0.1', 0, certs['cert'], certs['key'])
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        context = ssl.create_default_context(cafile=certs['ca'])
        url = f'https://localhost:{server.server_port}'
        token = self.stock.config()['client_token']
        def post(route, data, credential=token):
            req = urllib.request.Request(url + route, data=json.dumps(data).encode(), method='POST',
                                         headers={'Authorization': 'Bearer ' + credential, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, context=context, timeout=5) as response:
                return json.load(response)
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            post('/reserve', {'machine': machine()}, credential='wrong')
        self.assertEqual(rejected.exception.code, 401)
        m = machine()
        assigned = post('/reserve', {'machine': m, 'info': {'Serial': 'SERIAL-TEST'}})
        self.assertIn('<ProductKey>', assigned['xml'])
        self.assertEqual(post('/reserve', {'machine': m})['id'], assigned['id'])
        self.assertTrue(post('/report', {'machine': m, 'id': assigned['id'], 'state': 'usada'})['ok'])
        row = self.stock.assignments()[0]
        self.assertEqual(row['state'], 'usada')
        self.assertEqual(json.loads(row['info'])['IP'], '127.0.0.1')
        wrong_context = ssl.create_default_context()
        with self.assertRaises(urllib.error.URLError):
            urllib.request.urlopen(url, context=wrong_context, timeout=5)


if __name__ == '__main__':
    unittest.main()
