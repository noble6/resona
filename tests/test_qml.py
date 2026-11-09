"""Headless keyboard regressions for the custom controls."""
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

COMPONENTS = (Path(__file__).resolve().parents[1] / "app/qml/components").as_uri()


class KeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def load(self, control):
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("audio", None)
        self.engine.rootContext().setContextProperty("fontFamily", "sans-serif")
        self.engine.loadData(f'''
            import QtQuick
            import "{COMPONENTS}"
            Window {{
                id: win; width: 400; height: 200; visible: true
                property int activations: 0
                property int shortcutActivations: 0
                Shortcut {{ sequence: "Space"; onActivated: win.shortcutActivations++ }}
                {control}
            }}
        '''.encode())
        self.assertTrue(self.engine.rootObjects())
        self.window = self.engine.rootObjects()[0]
        item = self.window.findChild(QQuickItem, "control")
        self.assertIsNotNone(item)
        item.forceActiveFocus()
        QTest.qWait(10)
        return item

    def tearDown(self):
        if hasattr(self, "window"):
            self.window.close()
        if hasattr(self, "engine"):
            del self.engine

    def test_button_activates_with_space_and_enter(self):
        self.load('Btn { objectName: "control"; text: "Test"; onClicked: win.activations++ }')
        QTest.keyClick(self.window, Qt.Key.Key_Space)
        QTest.keyClick(self.window, Qt.Key.Key_Return)
        self.assertEqual(self.window.property("activations"), 2)

    def test_switch_toggles_with_keyboard(self):
        item = self.load('M3Switch { objectName: "control"; onToggled: (on) => { checked = on; win.activations++ } }')
        QTest.keyClick(self.window, Qt.Key.Key_Space)
        self.assertTrue(item.property("checked"))
        QTest.keyClick(self.window, Qt.Key.Key_Return)
        self.assertFalse(item.property("checked"))
        self.assertEqual(self.window.property("activations"), 2)

    def test_chip_activates_with_keyboard(self):
        self.load('Chip { objectName: "control"; text: "Music"; onClicked: win.activations++ }')
        QTest.keyClick(self.window, Qt.Key.Key_Space)
        self.assertEqual(self.window.property("activations"), 1)

    def test_selection_menu_works_with_keyboard(self):
        item = self.load('SelectButton { objectName: "control"; options: ["One", "Two"]; current: "One"; '
                         'onPicked: (value) => { current = value; win.activations++ } }')
        QTest.keyClick(self.window, Qt.Key.Key_Space)
        QTest.qWait(20)
        QTest.keyClick(self.window, Qt.Key.Key_Down)
        QTest.keyClick(self.window, Qt.Key.Key_Return)
        self.assertEqual(item.property("current"), "Two")
        self.assertEqual(self.window.property("activations"), 1)

    def test_slider_arrows_and_range_keys(self):
        item = self.load('WavySlider { objectName: "control"; stepSize: 0.1; '
                         'onMoved: (next) => value = next }')
        QTest.keyClick(self.window, Qt.Key.Key_Right)
        self.assertAlmostEqual(item.property("value"), 0.6)
        QTest.keyClick(self.window, Qt.Key.Key_Home)
        self.assertEqual(item.property("value"), 0)
        QTest.keyClick(self.window, Qt.Key.Key_Left)
        self.assertEqual(item.property("value"), 0)
        QTest.keyClick(self.window, Qt.Key.Key_End)
        self.assertEqual(item.property("value"), 1)


if __name__ == "__main__":
    unittest.main()
