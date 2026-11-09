"""Exercise the app's IPC handler with real local sockets, without starting audio."""
import ast
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


class IpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QApplication([])

    def test_pending_requests_are_drained_even_if_data_arrived_early(self):
        tree = ast.parse((Path(__file__).resolve().parents[1] / "app/main.py").read_text())
        handler = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "on_conn")
        with tempfile.TemporaryDirectory() as directory:
            server = QLocalServer()
            self.assertTrue(server.listen(str(Path(directory) / "socket")))
            show = Mock()
            scope = {"server": server, "show": show, "QLocalSocket": QLocalSocket}
            exec(compile(ast.Module(body=[handler], type_ignores=[]), "<ipc-handler>", "exec"), scope)
            clients = []
            try:
                for _ in range(3):
                    client = QLocalSocket()
                    client.connectToServer(server.fullServerName())
                    self.assertTrue(client.waitForConnected(1000))
                    client.write(b"show")
                    client.flush()
                    clients.append(client)
                QTest.qWait(30)
                scope["on_conn"]()
                self.assertEqual(show.call_count, 3)
                for client in clients:
                    client.disconnectFromServer()
                QTest.qWait(10)
                self.assertFalse(server.hasPendingConnections())
            finally:
                for client in clients:
                    client.abort()
                server.close()


if __name__ == "__main__":
    unittest.main()
