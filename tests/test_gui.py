"""Smoke test real de Tk; se ejecuta en Windows CI o bajo Xvfb en Linux."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import json

from app_usb import cliente

from servidor import Stock
from servidor_gui import ServerApp, safe_cell


class CsvTests(unittest.TestCase):
    def test_formula_escape(self):
        self.assertEqual(safe_cell('=1+1'), "'=1+1")
        self.assertEqual(safe_cell('SN123'), 'SN123')


class GuiTests(unittest.TestCase):
    def test_tabs_inventory_search_and_details(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('Requiere escritorio o Xvfb.')
        self.addCleanup(root.destroy)
        root.withdraw()
        with tempfile.TemporaryDirectory() as tmp:
            stock = Stock(Path(tmp) / 'datos')
            xml = Path(tmp) / 'test.xml'
            xml.write_text('<l><ProductKey>AAAAA-BBBBB-CCCCC-DDDDD-EEEEE</ProductKey><Edition>Pro</Edition><Channel>OEM</Channel></l>')
            stock.import_files([xml])
            app = ServerApp(root, stock)
            root.update_idletasks()
            self.assertEqual(len(app.tabs.tabs()), 5)
            self.assertEqual(len(app.stock_tree.get_children()), 1)
            app.stock_search.set('missing')
            self.assertEqual(len(app.stock_tree.get_children()), 0)
            app.stock_search.set('test.xml')
            self.assertEqual(len(app.stock_tree.get_children()), 1)
            assigned = stock.reserve({'machine': '12345678-1234-1234-1234-123456789ABC', 'info': {'Serial': 'GUI-TEST'}})
            app.refresh()
            self.assertEqual(len(app.install_tree.get_children()), 1)
            self.assertEqual(len(app.types_tree.get_children()), 1)
            app.types_tree.selection_set('0')
            app.filter_type()
            self.assertEqual(app.stock_edition.get(), 'Pro')
            self.assertEqual(app.stock_channel.get(), 'OEM')
            app.stock_tree.selection_set('1')
            app.classify_license()
            app.show_assignment(assigned['id'])
            self.assertGreaterEqual(len(root.winfo_children()), 2)
            app.closing = True


class ResponsiveGuiTests(unittest.TestCase):
    def create_root(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('Requiere escritorio o Xvfb.')
        self.addCleanup(root.destroy)
        return root

    def test_client_scroll_resize_and_saved_address(self):
        root = self.create_root()
        with tempfile.TemporaryDirectory() as tmp, patch.object(cliente, 'BASE', Path(tmp)):
            (Path(tmp) / 'config.json').write_text(json.dumps({'servidor':'https://192.168.1.139:8443','token':'test-token','servidor_confirmado':True}))
            app = cliente.Client(root)
            root.geometry('560x400')
            root.update()
            self.assertEqual(app.server_address.get(), 'https://192.168.1.139:8443')
            self.assertLess(app.viewport.canvas.xview()[1], 1)
            self.assertLess(app.viewport.canvas.yview()[1], 1)
            self.assertTrue(app.log.cget('xscrollcommand'))
            self.assertTrue(app.log.cget('yscrollcommand'))
            with patch.object(cliente.simpledialog, 'askstring', return_value='192.168.1.140:9443'):
                app.change_server()
            self.assertEqual(app.server_address.get(), 'https://192.168.1.140:9443')
            self.assertEqual(cliente.load_config()['token'], 'test-token')
            old_width, old_height = app.log.winfo_width(), app.log.winfo_height()
            root.geometry('1500x1000')
            root.update()
            self.assertGreater(app.log.winfo_width(), old_width)
            self.assertGreater(app.log.winfo_height(), old_height)
            self.assertAlmostEqual(app.viewport.canvas.xview()[1], 1, places=2)
            self.assertAlmostEqual(app.viewport.canvas.yview()[1], 1, places=2)

    def test_server_scroll_resize_and_log_bars(self):
        root = self.create_root()
        with tempfile.TemporaryDirectory() as tmp:
            app = ServerApp(root, Stock(Path(tmp) / 'datos'))
            app.tabs.select(app.config_tab)
            root.geometry('660x460')
            root.update()
            self.assertLess(app.viewport.canvas.xview()[1], 1)
            self.assertLess(app.viewport.canvas.yview()[1], 1)
            self.assertTrue(app.console.cget('xscrollcommand'))
            self.assertTrue(app.console.cget('yscrollcommand'))
            old_width = app.console.winfo_width()
            root.geometry('1650x1100')
            root.update()
            self.assertGreater(app.console.winfo_width(), old_width)
            self.assertAlmostEqual(app.viewport.canvas.xview()[1], 1, places=2)
            self.assertEqual(app.card_columns, 7 if app.card_labels[0].master.winfo_width() >= 1365 else 4)
            app.closing = True


if __name__ == '__main__':
    unittest.main()
