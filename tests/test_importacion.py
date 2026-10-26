"""Fixtures sintéticas: nunca incluir XML, claves ni referencias reales."""
from pathlib import Path
import tempfile
import unittest
import uuid
import zipfile

from clasificacion import metadata, UNKNOWN
from servidor import Stock


def xml(number, edition='', channel='', reference='REF-DEMO'):
    return f'<Key><ProductKey>AAAAA-BBBBB-CCCCC-DDDDD-{number:05d}</ProductKey><ProductKeyID>DEMO</ProductKeyID><ProductKeyState>2</ProductKeyState><ProductKeyPartNumber>{reference}</ProductKeyPartNumber><Edition>{edition}</Edition><Channel>{channel}</Channel></Key>'


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stock = Stock(self.root / 'db')
        self.technician_id = self.stock.add_technician('Técnico de prueba')

    def write(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw)
        return path

    def test_reference_does_not_invent_edition_or_channel(self):
        values = metadata(xml(1))
        self.assertEqual(values['edition'], UNKNOWN)
        self.assertEqual(values['channel'], UNKNOWN)
        path = self.write('one.xml', xml(1))
        self.stock.import_files([path])
        row = self.stock.inventory()[0]
        self.assertEqual(row['state'], 'sin identificar')
        with self.assertRaises(ValueError):
            self.stock.reserve({'technician_id': self.technician_id, 'machine': str(uuid.uuid4())})
        self.assertIsNone(self.stock.reserve({'technician_id': self.technician_id, 'machine': str(uuid.uuid4()), 'edition': 'Pro'}))

    def test_reference_rule_reclassifies_existing_and_future(self):
        self.stock.import_files([self.write('1.xml', xml(1)), self.write('2.xml', xml(2))])
        self.assertEqual(self.stock.set_classification(1, 'Pro', 'CMAR', True), 2)
        self.stock.import_files([self.write('3.xml', xml(3))])
        self.assertEqual({(r['edition'], r['channel']) for r in self.stock.inventory()}, {('Pro', 'CMAR')})
        self.assertEqual({r['state'] for r in self.stock.inventory()}, {'disponible'})
        assigned = self.stock.reserve({'technician_id': self.technician_id, 'machine': str(uuid.uuid4()), 'edition': 'Pro', 'channel': 'CMAR'})
        self.assertEqual((assigned['edition'], assigned['channel']), ('Pro', 'CMAR'))
        self.stock.set_classification(1, 'Home', 'Retail', False)
        self.stock = Stock(self.root / 'db')
        self.assertEqual(self.stock.inventory()[0]['edition'], 'Home')
        self.assertNotIn('xml', self.stock.license_details(1))
        self.assertEqual(self.stock.license_details(1)['xml_state'], '2')

    def test_mixed_zip_folder_files_duplicate_and_broken_entry(self):
        folder = self.root / 'folder'
        self.write('folder/sub/one.XML', xml(1, 'Pro', 'CMAR'))
        self.write('folder/sub/broken.xml', '<broken')
        archive = self.root / 'batch.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('nested/two.xml', xml(2, 'Home', 'OEM'))
            z.writestr('dupe.xml', xml(1, 'Pro', 'CMAR'))
            z.writestr('ignore.txt', 'not a license')
            z.writestr('../unsafe.xml', xml(3))
            z.writestr('oldBURN.xml', xml(4))
            z.writestr('oversized.xml', b'x' * 1048577)
            z.writestr('no-reference.xml', xml(5, 'Pro', 'Retail', ''))
        loose = self.write('single.xml', xml(6, 'Pro', 'OEM'))
        results = self.stock.import_files([folder, archive, loose])
        self.assertEqual(sum(status == 'importado' for _, status in results), 4)
        self.assertEqual(sum(status == 'duplicado' for _, status in results), 1)
        self.assertEqual(sum(status.startswith('error:') for _, status in results), 4)
        self.assertFalse((self.root.parent / 'unsafe.xml').exists())
        self.assertEqual(len(self.stock.inventory()), 4)

    def test_edition_channel_selection_never_falls_back_to_other_stock(self):
        self.stock.import_files([self.write('home.xml', xml(1, 'Home', 'OEM')),
                                 self.write('pro.xml', xml(2, 'Pro', 'CMAR'))])
        self.assertIsNone(self.stock.reserve({'technician_id': self.technician_id, 'machine': str(uuid.uuid4()), 'edition': 'Pro', 'channel': 'OEM'}))
        m = str(uuid.uuid4())
        assigned = self.stock.reserve({'technician_id': self.technician_id, 'machine': m, 'edition': 'Pro', 'channel': 'CMAR'})
        self.assertEqual(assigned['edition'], 'Pro')
        with self.assertRaises(ValueError):
            self.stock.reserve({'technician_id': self.technician_id, 'machine': m, 'edition': 'Home', 'channel': 'OEM'})
        self.assertIsNone(self.stock.reserve({'technician_id': self.technician_id, 'machine': str(uuid.uuid4()), 'edition': 'Pro', 'channel': 'CMAR'}))
        self.assertEqual(sum(r['state'] == 'disponible' for r in self.stock.inventory()), 1)

    def test_utf16_namespaces_and_conflicting_metadata(self):
        from servidor import parse_xml
        text = xml(1, 'Windows 11 Pro', 'CMAR').replace('<Key>', '<Key xmlns="urn:demo">')
        parsed, _ = parse_xml(text.encode('utf-16'))
        self.assertEqual(metadata(parsed)['edition'], 'Pro')
        self.assertEqual(metadata(parsed)['channel'], 'CMAR')
        contradictory = xml(2, 'Home', 'OEM').replace('</Key>', '<Edition>Pro</Edition></Key>')
        self.assertEqual(metadata(contradictory)['edition'], UNKNOWN)

    def test_invalid_zip_does_not_abort_following_files(self):
        invalid = self.write('invalid.zip', 'not a zip')
        results = self.stock.import_files([invalid, self.write('good.xml', xml(1, 'Pro', 'CMAR'))])
        self.assertTrue(results[0][1].startswith('error:'))
        self.assertEqual(results[1][1], 'importado')


if __name__ == '__main__':
    unittest.main()
