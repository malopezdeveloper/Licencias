"""Smoke test real de Tk; se ejecuta en Windows CI o bajo Xvfb en Linux."""
from pathlib import Path
import tempfile
import tkinter as tk
import unittest

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


if __name__ == '__main__':
    unittest.main()
