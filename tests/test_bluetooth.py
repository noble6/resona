"""Bluetooth auto-connect against a fake BlueZ on a private D-Bus (never the real system bus)."""
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from resona import bluetooth  # noqa: E402

HEADPHONES = "/org/bluez/hci0/dev_AA_AA_AA_AA_AA_01"
SPEAKER = "/org/bluez/hci0/dev_AA_AA_AA_AA_AA_02"


def have_tools():
    try:
        import gi  # noqa: F401
        from gi.repository import Gio  # noqa: F401
    except ImportError:
        return False
    return all(subprocess.run(["which", t], capture_output=True).returncode == 0
               for t in ("dbus-daemon", "busctl"))


@unittest.skipUnless(have_tools(), "needs dbus-daemon, busctl and PyGObject")
class FakeBluez(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address"],
                                      stdout=subprocess.PIPE, text=True)
        cls.address = cls.daemon.stdout.readline().strip()
        cls.saved = os.environ.get("DBUS_SYSTEM_BUS_ADDRESS")
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = cls.address   # busctl --system now talks to the fake bus
        cls.fake = None

    @classmethod
    def tearDownClass(cls):
        if cls.fake:
            cls.fake.terminate(); cls.fake.wait()
        cls.daemon.terminate(); cls.daemon.wait()
        if cls.saved is None:
            os.environ.pop("DBUS_SYSTEM_BUS_ADDRESS", None)
        else:
            os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = cls.saved

    def start_fake(self):
        env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=self.address)
        type(self).fake = subprocess.Popen([sys.executable, str(ROOT / "tests/fake_bluez.py")], env=env,
                                           stdout=subprocess.PIPE, text=True)
        self.assertEqual(self.fake.stdout.readline().strip(), "ready")

    def test_1_service_off_is_reported_without_hanging_or_activating(self):
        t = time.monotonic()
        st = bluetooth.status()
        self.assertLess(time.monotonic() - t, 5)
        self.assertFalse(st["service"])
        self.assertEqual(st["devices"], [])
        self.assertEqual(st["error"], bluetooth.SERVICE_OFF)

    def test_2_lists_only_paired_audio_devices(self):
        self.start_fake()
        st = bluetooth.status()
        self.assertTrue(st["service"], st)
        self.assertTrue(st["adapter"]["powered"])
        names = {d["name"]: d for d in st["devices"]}
        self.assertEqual(set(names), {"Test Headphones", "Far Speaker"})   # the mouse is not audio
        self.assertFalse(names["Test Headphones"]["connected"])

    def test_3_connect_success_and_failure(self):
        ok, err = bluetooth.connect(HEADPHONES)
        self.assertTrue(ok, err)
        ok, err = bluetooth.connect(SPEAKER)
        self.assertFalse(ok)
        self.assertIn("Page Timeout", err)
        names = {d["name"]: d["connected"] for d in bluetooth.status()["devices"]}
        self.assertTrue(names["Test Headphones"])
        self.assertFalse(bluetooth.connect("/not/bluez")[0])

    def test_4_disconnect(self):
        self.assertTrue(bluetooth.disconnect(HEADPHONES)[0])
        names = {d["name"]: d["connected"] for d in bluetooth.status()["devices"]}
        self.assertFalse(names["Test Headphones"])


class Policy(unittest.TestCase):
    def dev(self, addr, connected=False):
        return {"address": addr, "connected": connected, "path": "/org/bluez/x", "name": addr}

    def test_backoff_doubles_to_a_cap_and_success_resets(self):
        ac = bluetooth.AutoConnect()
        now = 1000.0
        self.assertEqual(len(ac.due([self.dev("A")], {}, now)), 1)
        delays = []
        for _ in range(8):
            ac.result("A", False, now)
            delays.append(ac.next_try["A"] - now)
        self.assertEqual(delays[:3], [15.0, 30.0, 60.0])
        self.assertEqual(max(delays), ac.MAX_RETRY)
        self.assertEqual(ac.due([self.dev("A")], {}, now + 10), [])
        ac.result("A", True, now)                           # connected: backoff forgotten
        self.assertEqual(ac.due([self.dev("A", connected=True)], {}, now), [])
        self.assertNotIn("A", ac.backoff)

    def test_manual_disconnect_gets_a_quiet_period(self):
        ac = bluetooth.AutoConnect()
        ac.due([self.dev("A", connected=True)], {}, 0)
        self.assertEqual(ac.due([self.dev("A", connected=False)], {}, 10), [])     # just dropped
        self.assertEqual(ac.due([self.dev("A")], {}, 10 + ac.AFTER_DISCONNECT - 1), [])
        self.assertEqual(len(ac.due([self.dev("A")], {}, 10 + ac.AFTER_DISCONNECT + 1)), 1)

    def test_disabled_devices_are_never_dialled(self):
        ac = bluetooth.AutoConnect()
        self.assertEqual(ac.due([self.dev("A"), self.dev("B")], {"A": False}, 0), [self.dev("B")])

    def test_parse_ignores_garbage(self):
        self.assertEqual(bluetooth.parse_objects({"data": [{"/x": "nope"}]}), {"adapter": None, "devices": []})
        self.assertEqual(bluetooth.parse_objects([]), {"adapter": None, "devices": []})


if __name__ == "__main__":
    unittest.main()
