import json
from pathlib import Path
import tempfile
import unittest
import uuid

from servidor import Stock
from app_usb.cliente import validate_stock


class AvailabilityTests(unittest.TestCase):
    def test_classification_states_release_and_readonly_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            stock=Stock(root/'datos')
            technician=stock.add_technician('Técnico de prueba')
            self.assertEqual(stock.availability()['available'],0)
            for i,(edition,channel) in enumerate([('Pro','CMAR'),('Pro','CMAR'),('Home','OEM'),('Pro','OEM'),('','')]):
                file=root/f'{i}.xml'
                file.write_text(f'<Key><ProductKey>AAAAA-BBBBB-CCCCC-DDDDD-{i:05d}</ProductKey><Edition>{edition}</Edition><Channel>{channel}</Channel></Key>')
                stock.import_files([file])
            stock.toggle(4,False)
            first=stock.availability()
            self.assertEqual(first['available'],3)
            self.assertEqual({(r['edition'],r['channel']):r['available'] for r in first['groups']},{('Pro','CMAR'):2,('Home','OEM'):1,('Pro','OEM'):0})
            self.assertEqual(stock.assignments(),[])
            self.assertNotIn('AAAAA-BBBBB',json.dumps(first))
            m=str(uuid.uuid4())
            assigned=stock.reserve({'machine':m,'technician_id':technician,'edition':'Pro','channel':'CMAR'})
            self.assertEqual(stock.availability()['available'],2)
            stock.report({'machine':m,'id':assigned['id'],'state':'revision'})
            self.assertEqual(stock.availability()['available'],2)
            stock.report({'machine':m,'id':assigned['id'],'state':'usada'})
            self.assertEqual(stock.availability()['available'],2)
            stock.release(assigned['id'],'Retirada verificada')
            self.assertEqual(stock.availability()['available'],3)
            stock.toggle(4,True)
            self.assertEqual(stock.availability()['available'],4)

    def test_empty_and_invalid_api_summaries(self):
        self.assertEqual(validate_stock({'available':0,'groups':[]})['available'],0)
        for invalid in ({}, {'available':True,'groups':[]}, {'available':1,'groups':[]},
                        {'available':-1,'groups':[]}, {'available':0,'groups':[{'edition':'Pro','channel':'CMAR','available':-1}]},
                        {'available':2,'groups':[{'edition':'Pro','channel':'CMAR','available':1}]*2}):
            with self.subTest(invalid=invalid),self.assertRaises(RuntimeError):
                validate_stock(invalid)


if __name__=='__main__':unittest.main()
