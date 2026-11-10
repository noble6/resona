"""Headless keyboard regressions for the custom controls."""
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Property, QCoreApplication, QObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

COMPONENTS = (Path(__file__).resolve().parents[1] / "app/qml/components").as_uri()
PAGES = (Path(__file__).resolve().parents[1] / "app/qml/pages").as_uri()


class KeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = QCoreApplication.instance()
        if app is not None and not isinstance(app, QGuiApplication):
            raise RuntimeError("QML tests need a GUI application; run them in a separate process")
        cls.app = app or QApplication([])

    def load(self, control, audio=None, width=400, height=200):
        self.engine = QQmlApplicationEngine()
        self.audio = audio
        self.engine.rootContext().setContextProperty("audio", audio)
        self.engine.rootContext().setContextProperty("fontFamily", "sans-serif")
        self.engine.loadData(f'''
            import QtQuick
            import "{COMPONENTS}"
            import "{PAGES}" as Pages
            Window {{
                id: win; width: {width}; height: {height}; visible: true
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

    def test_settings_page_reveals_tab_focus_in_both_directions(self):
        values = dict(
            follow=True, sinks=[], output="", userPresets=[], captureAll=True,
            perDevice=True, appAuto=True, autoApp="", apps=[], profiles=[],
            dark=True, reducedMotion=True, accents=["#8B5CF6"], accent="#8B5CF6",
            updateInfo=dict(state="idle", freq="weekly", kind="user", auto=False,
                            notes="", message="", last=0),
            autostart=False, version="test", sampleRate=48000, outputLayout={"name": "Stereo"},
        )
        audio_type = type("SettingsAudio", (QObject,), {
            key: Property("QVariant", lambda self, key=key: values[key], constant=True)
            for key in values
        })
        audio = audio_type()
        page = self.load('Pages.SettingsPage { objectName: "control"; anchors.fill: parent }',
                         audio=audio, width=1040, height=760)
        self.assertGreater(page.property("contentHeight"), page.height())
        for modifiers in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier):
            scrolled = False
            visited = 0
            for _ in range(30):
                QTest.keyClick(self.window, Qt.Key.Key_Tab, modifiers)
                QTest.qWait(10)
                focus = self.window.activeFocusItem()
                ancestor = focus
                while ancestor is not None and ancestor != page:
                    ancestor = ancestor.parentItem()
                if focus is None or focus == page or ancestor is None:
                    continue
                visited += 1
                top = focus.mapToItem(page, QPointF(0, 0)).y()
                bottom = focus.mapToItem(page, QPointF(0, focus.height())).y()
                self.assertGreaterEqual(top, -1, f"focused control hidden above page: {top}")
                self.assertLessEqual(bottom, page.height() + 1, f"focused control hidden below page: {bottom}")
                scrolled |= page.property("contentY") > 0
            self.assertGreater(visited, 10)
            self.assertTrue(scrolled, "test must reach controls below the initial viewport")


if __name__ == "__main__":
    unittest.main()
