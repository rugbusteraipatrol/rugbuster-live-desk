import threading
import unittest
from unittest.mock import Mock
from desktop import TrayController

class TrayLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.window=Mock()
        self.stop=threading.Event()
        self.controller=TrayController(self.window,self.stop)
        self.controller.tray=Mock()
    def test_close_hides_instead_of_terminating(self):
        self.assertFalse(self.controller.closing())
        self.window.hide.assert_called_once()
        self.window.destroy.assert_not_called()
        self.assertFalse(self.stop.is_set())
    def test_tray_reopens_hidden_window(self):
        self.controller.closing()
        self.controller.show()
        self.window.show.assert_called_once()
        self.window.restore.assert_called_once()
    def test_quit_stops_once_and_permits_close(self):
        self.controller.quit();self.controller.quit()
        self.assertTrue(self.controller.closing())
        self.controller.tray.stop.assert_called_once()
        self.window.destroy.assert_called_once()
        self.controller.show()
        self.window.show.assert_not_called()

if __name__=='__main__':unittest.main()
