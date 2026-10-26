import json, queue, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import urllib.error
from app_usb import cliente as c

class Response:
    def __init__(self,value): self.value=value
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self): return json.dumps(self.value).encode()

class FlowTests(unittest.TestCase):
    def run_flow(self,install_ok=True,fail_report=False):
        calls=[]
        def request(req,timeout):
            payload=json.loads(req.data); calls.append((req.full_url,payload))
            if req.full_url.endswith('/reserve'):
                return Response({'id':'test-assignment','xml':'<l><ProductKey>AAAAA-BBBBB-CCCCC-DDDDD-EEEEE</ProductKey></l>'})
            if fail_report: raise urllib.error.URLError('offline')
            return Response({'ok':True})
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'config.json').write_text(json.dumps({'servidor':'https://server:8443','token':'secret'}))
            app=c.Client.__new__(c.Client); app.q=queue.Queue(); app.technician_id=1
            with patch.object(c,'BASE',Path(tmp)), patch.object(c,'os',SimpleNamespace(name='nt')), patch.object(c,'ctypes',SimpleNamespace(windll=SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda:True)))), patch.object(c,'info',return_value={'machine':'12345678-1234-1234-1234-123456789ABC','edition':'Professional','info':{'Modelo':'Test','Serial':'SN'}}), patch.object(c,'install',return_value={'ok':install_ok,'before_partial':'ZZZZZ','after_partial':'EEEEE'}), patch.object(c.urllib.request,'build_opener',return_value=SimpleNamespace(open=request)):
                app.work()
            messages=[]
            while not app.q.empty(): messages.append(app.q.get())
            return calls,messages[-1]
    def test_success(self):
        calls,last=self.run_flow()
        self.assertEqual(calls[-1][1]['state'],'usada'); self.assertIn('CORRECTO',last[1])
        self.assertNotIn('AAAAA-BBBBB',last[1])
        self.assertEqual(calls[0][1]['technician_id'],1)
        self.assertNotIn('Tecnico',calls[0][1]['info'])
        self.assertEqual(calls[-1][1]['technician_id'],1)
    def test_install_fail_stays_blocked(self):
        calls,last=self.run_flow(install_ok=False)
        self.assertEqual(calls[-1][1]['state'],'revision'); self.assertIn('bloqueada',last[1])
    def test_report_failure(self):
        calls,last=self.run_flow(fail_report=True)
        self.assertEqual(len(calls),2); self.assertIn('ya tiene la clave instalada',last[1])
class EditionTests(unittest.TestCase):
    def test_detected_windows_edition(self):
        self.assertEqual(c.detected_edition('Professional'), 'Pro')
        self.assertEqual(c.detected_edition('Core'), 'Home')
        self.assertEqual(c.detected_edition('CoreSingleLanguage'), 'Home Single Language')
        self.assertEqual(c.detected_edition('unknown'), '')

    @unittest.skipUnless(c.os.name == 'nt', 'Consulta de solo lectura en Windows.')
    def test_real_powershell_inventory(self):
        data = c.info()
        self.assertIn('edition', data)
        self.assertIn('machine', data)
        self.assertIn('Modelo', data['info'])

if __name__=='__main__': unittest.main()
