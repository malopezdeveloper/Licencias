import json
from pathlib import Path
import queue
import tempfile
import unittest
import uuid
from unittest.mock import patch

from servidor import Stock, TechnicianError
from app_usb import cliente


class TechnicianTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stock = Stock(self.root / 'datos')
        path = self.root / 'demo.xml'
        path.write_text('<Key><ProductKey>AAAAA-BBBBB-CCCCC-DDDDD-EEEEE</ProductKey><Edition>Pro</Edition><Channel>OEM</Channel></Key>')
        self.stock.import_files([path])

    def test_manage_names_duplicates_and_active_list(self):
        first = self.stock.add_technician('  Técnico   Uno  ')
        second = self.stock.add_technician('Técnico Dos')
        with self.assertRaises(ValueError):
            self.stock.add_technician('TÉCNICO UNO')
        with self.assertRaises(ValueError):
            self.stock.add_technician('  ')
        with self.assertRaises(ValueError):
            self.stock.add_technician('Nombre\nno válido')
        self.stock.edit_technician(first, name='Primer técnico')
        self.stock.edit_technician(second, active=False)
        self.assertEqual([r['id'] for r in self.stock.technicians(active_only=True)], [first])
        self.assertEqual(len(self.stock.technicians()), 2)
        self.stock.edit_technician(second, active=True)
        self.assertEqual(len(self.stock.technicians(active_only=True)), 2)

    def test_free_text_unknown_inactive_and_missing_technician_rejected(self):
        iid = self.stock.add_technician('Técnico válido')
        m = str(uuid.uuid4())
        for payload in ({'info': {'Tecnico': 'Inventado'}}, {'technician_id': 999}, {'technician_id': True}, {'technician_id': str(iid)}):
            with self.subTest(payload=payload), self.assertRaises(TechnicianError):
                self.stock.reserve({'machine': m, **payload})
        self.stock.edit_technician(iid, active=False)
        with self.assertRaises(TechnicianError):
            self.stock.reserve({'machine': m, 'technician_id': iid})
        self.assertEqual(self.stock.assignments(), [])

    def test_server_name_snapshot_rename_and_disable_during_install(self):
        iid = self.stock.add_technician('Nombre original')
        m = str(uuid.uuid4())
        assigned = self.stock.reserve({'machine': m, 'technician_id': iid, 'info': {'Tecnico': 'Nombre falso'}})
        self.stock.edit_technician(iid, name='Nombre nuevo', active=False)
        # La operación iniciada puede confirmar aunque el usuario se desactive mientras instala.
        self.stock.report({'machine': m, 'id': assigned['id'], 'state': 'usada', 'technician_id': iid})
        row = self.stock.assignments()[0]
        self.assertEqual(row['technician_id'], iid)
        self.assertEqual(json.loads(row['info'])['Tecnico'], 'Nombre original')
        self.assertEqual(self.stock.technicians()[0]['installations'], 1)
        self.assertEqual(row['state'], 'usada')
        with self.assertRaises(TechnicianError):
            self.stock.reserve({'machine': m, 'technician_id': iid})

    def test_pending_handoff_tracks_operator_without_rewriting_completed_install(self):
        first = self.stock.add_technician('Primero')
        second = self.stock.add_technician('Segundo')
        machine = str(uuid.uuid4())
        assigned = self.stock.reserve({'machine':machine,'technician_id':first})
        self.stock.reserve({'machine':machine,'technician_id':second})
        self.assertEqual(self.stock.assignments()[0]['technician_id'],second)
        self.stock.report({'machine':machine,'id':assigned['id'],'state':'usada','technician_id':second})
        self.stock.reserve({'machine':machine,'technician_id':first})
        self.assertEqual(self.stock.assignments()[0]['technician_id'],second)
        self.assertEqual(json.loads(self.stock.assignments()[0]['info'])['Tecnico'],'Segundo')

    def test_client_only_loads_server_response(self):
        app = cliente.Client.__new__(cliente.Client)
        app.q = queue.Queue()
        with patch.object(cliente, 'create_api', return_value=lambda route, data: {'technicians':[{'id':7,'name':'Servidor'}]}):
            app.users_worker({})
        kind, data = app.q.get_nowait()
        self.assertEqual(kind, 'users')
        self.assertEqual(data['technicians'], [{'id':7,'name':'Servidor'}])
        with patch.object(cliente, 'create_api', side_effect=RuntimeError('Servidor desconectado')):
            app.users_worker({})
        _, data = app.q.get_nowait()
        self.assertEqual(data['technicians'], [])
        self.assertIn('error', data)


if __name__ == '__main__':
    unittest.main()
