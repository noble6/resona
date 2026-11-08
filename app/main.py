#!/usr/bin/env python3
"""Resona: open spatial sound engine for Linux."""
from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase, QGuiApplication, QIcon, QSurfaceFormat  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuick import QQuickWindow  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon  # noqa: E402

from resona.backend import Backend  # noqa: E402

APP_ID = f"resona-{os.getuid()}"


def already_running() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(APP_ID)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return True
    return False


def main() -> int:
    hidden = "--hidden" in sys.argv
    shot_dir = os.environ.get("RESONA_SCREENSHOT")
    QGuiApplication.setDesktopFileName("resona")
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setSamples(4)        # MSAA for smooth geometry-rendered shapes
    fmt.setStencilBufferSize(8)  # clipping inside scaled/animated containers needs a stencil buffer
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)
    app.setApplicationName("Resona")
    app.setOrganizationName("Resona")
    app.setWindowIcon(QIcon(str(HERE / "icons" / "resona.svg")))
    app.setQuitOnLastWindowClosed(False)

    if not shot_dir and already_running():
        return 0
    server = QLocalServer()
    QLocalServer.removeServer(APP_ID)
    server.listen(APP_ID)

    fid = QFontDatabase.addApplicationFont(str(HERE / "fonts" / "RobotoFlex.ttf"))
    family = QFontDatabase.applicationFontFamilies(fid)[0] if fid >= 0 else "sans-serif"
    font = QFont(family, 10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)

    # Distance-field glyphs render heavy variable-font instances wrong; curves look sharper anyway.
    QQuickWindow.setTextRenderType(QQuickWindow.TextRenderType.CurveTextRendering)
    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda ws: [print("qml:", w.toString(), file=sys.stderr) for w in ws])
    engine.rootContext().setContextProperty("audio", backend)
    engine.rootContext().setContextProperty("fontFamily", family)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
    if not engine.rootObjects():
        backend.shutdown()
        return 1
    win = engine.rootObjects()[0]
    if not isinstance(win, QQuickWindow):
        import shiboken6
        win = shiboken6.wrapInstance(shiboken6.getCppPointer(win)[0], QQuickWindow)

    def show():
        win.show()
        win.raise_()
        win.requestActivate()

    def on_conn():
        c = server.nextPendingConnection()
        c.readyRead.connect(show)
    server.newConnection.connect(on_conn)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable() and not shot_dir:
        tray = QSystemTrayIcon(app.windowIcon())
        tray.setToolTip("Resona")
        menu = QMenu()
        menu.addAction("Open Resona", show)
        toggle = menu.addAction("Effects on")
        toggle.setCheckable(True)

        def sync():
            toggle.setChecked(bool(backend.params.get("enable", 1)))
        backend.paramsChanged.connect(sync)
        sync()
        toggle.toggled.connect(lambda on: backend.setEnabled(on))
        prof = menu.addMenu("Sound profile")
        for p in backend.profiles:
            prof.addAction(p["name"], lambda n=p["name"]: backend.applyProfile(n))
        menu.addSeparator()
        menu.addAction("Quit", app.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda r: show() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
    win.setProperty("closeToTray", tray is not None)

    if not hidden or tray is None:
        show()

    app.aboutToQuit.connect(backend.shutdown)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    keepalive = QTimer(interval=250, timeout=lambda: None)  # lets Python see signals
    keepalive.start()

    if shot_dir:
        pages = ["home", "eq", "space", "dynamics", "correction", "hardware", "settings"]
        win.setHeight(int(os.environ.get("RESONA_SCREENSHOT_HEIGHT", win.height())))
        Path(shot_dir).mkdir(parents=True, exist_ok=True)

        def snap(i=0):
            if i >= len(pages):
                app.quit()
                return
            win.setProperty("page", i)
            QTimer.singleShot(1400, lambda: (win.grabWindow().save(f"{shot_dir}/{i}_{pages[i]}.png"),
                                             snap(i + 1)))
        frames = int(os.environ.get("RESONA_FRAMES", "0"))
        if frames:  # animated demo: grab the home page every 70 ms
            def frame(i=0):
                if i >= frames:
                    app.quit()
                    return
                win.grabWindow().save(f"{shot_dir}/frame_{i:03d}.png")
                QTimer.singleShot(70, lambda: frame(i + 1))
            QTimer.singleShot(5000, frame)
        else:
            QTimer.singleShot(2500, snap)

    rc = app.exec()
    del win
    del engine  # destroy QML before the backend its bindings point at
    return rc


if __name__ == "__main__":
    sys.exit(main())
