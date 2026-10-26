"""Memoria de dirección del USB: sin claves ni conexión a un servidor real."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_usb import cliente as c


class ServerAddressTests(unittest.TestCase):
    def test_ip_hostname_ipv6_and_ports(self):
        for value, expected in [
            ('192.168.1.139', 'https://192.168.1.139:8443'),
            ('192.168.1.139:9443', 'https://192.168.1.139:9443'),
            ('almacen', 'https://almacen:8443'),
            ('https://Almacen:443/', 'https://almacen:443'),
            ('::1', 'https://[::1]:8443'),
            ('[::1]:9443', 'https://[::1]:9443')]:
            with self.subTest(value=value):
                self.assertEqual(c.normalize_server(value), expected)

    def test_invalid_addresses(self):
        for value in ('', 'http://server', 'https://user:password@server', 'https://server/path',
                      'https://server?key=value', 'https://server#fragment', 'server:70000',
                      'server:0', 'not a server', '999.999.999.999', 'server:abc'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.normalize_server(value)

    def test_remember_and_change_without_losing_token(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(c, 'BASE', Path(tmp)):
            path = Path(tmp) / 'config.json'
            path.write_text(json.dumps({'token': 'fake-test-token', 'otro': 'conservar'}))
            self.assertEqual(c.save_server('192.168.1.139'), 'https://192.168.1.139:8443')
            saved = c.load_config()
            self.assertTrue(saved['servidor_confirmado'])
            self.assertEqual(saved['token'], 'fake-test-token')
            c.save_server('192.168.1.140:9443')
            saved = c.load_config()
            self.assertEqual(saved['servidor'], 'https://192.168.1.140:9443')
            self.assertEqual(saved['otro'], 'conservar')
            self.assertEqual(saved['token'], 'fake-test-token')
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])

    def test_failed_write_preserves_old_address(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(c, 'BASE', Path(tmp)):
            c.save_server('192.168.1.139')
            with patch.object(c.tempfile, 'NamedTemporaryFile', side_effect=PermissionError('Solo lectura')):
                with self.assertRaises(PermissionError):
                    c.save_server('192.168.1.140')
            self.assertEqual(c.load_config()['servidor'], 'https://192.168.1.139:8443')


if __name__ == '__main__':
    unittest.main()
