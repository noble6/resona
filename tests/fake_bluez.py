"""A tiny stand-in for BlueZ on a private D-Bus, for tests/test_bluetooth.py.

Exports an adapter, paired headphones that connect, a paired speaker that is out of
range (Connect fails), and a paired mouse that is not an audio device.
Usage: python3 fake_bluez.py  (with DBUS_SESSION_BUS_ADDRESS set to the private bus)
"""
import sys

from gi.repository import Gio, GLib

XML = """
<node>
  <interface name="org.freedesktop.DBus.ObjectManager">
    <method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method>
  </interface>
  <interface name="org.bluez.Device1">
    <method name="Connect"/>
    <method name="Disconnect"/>
  </interface>
</node>"""
A2DP = "0000110b-0000-1000-8000-00805f9b34fb"
HID = "00001124-0000-1000-8000-00805f9b34fb"
DEVICES = {
    "/org/bluez/hci0/dev_AA_AA_AA_AA_AA_01": dict(Address="AA:AA:AA:AA:AA:01", Alias="Test Headphones",
                                                   Icon="audio-headphones", UUIDs=[A2DP], ok=True),
    "/org/bluez/hci0/dev_AA_AA_AA_AA_AA_02": dict(Address="AA:AA:AA:AA:AA:02", Alias="Far Speaker",
                                                   Icon="audio-card", UUIDs=[A2DP], ok=False),
    "/org/bluez/hci0/dev_AA_AA_AA_AA_AA_03": dict(Address="AA:AA:AA:AA:AA:03", Alias="Mouse",
                                                   Icon="input-mouse", UUIDs=[HID], ok=True),
}
connected = {path: False for path in DEVICES}
calls = []


def managed():
    objs = {"/org/bluez/hci0": {"org.bluez.Adapter1": {
        "Address": GLib.Variant("s", "00:11:22:33:44:55"), "Alias": GLib.Variant("s", "test-adapter"),
        "Powered": GLib.Variant("b", True)}}}
    for path, d in DEVICES.items():
        objs[path] = {"org.bluez.Device1": {
            "Address": GLib.Variant("s", d["Address"]), "Alias": GLib.Variant("s", d["Alias"]),
            "Icon": GLib.Variant("s", d["Icon"]), "UUIDs": GLib.Variant("as", d["UUIDs"]),
            "Paired": GLib.Variant("b", True), "Trusted": GLib.Variant("b", True),
            "Connected": GLib.Variant("b", connected[path])}}
    return GLib.Variant("(a{oa{sa{sv}}})", (objs,))


def handle(conn, sender, path, iface, method, params, invocation):
    calls.append((path, method))
    print(f"call {method} {path}", flush=True)
    if method == "GetManagedObjects":
        invocation.return_value(managed())
    elif method == "Connect":
        if DEVICES[path]["ok"]:
            connected[path] = True
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.bluez.Error.Failed", "Page Timeout")
    elif method == "Disconnect":
        connected[path] = False
        invocation.return_value(None)


def main():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    node = Gio.DBusNodeInfo.new_for_xml(XML)
    bus.register_object("/", node.interfaces[0], handle, None, None)
    for path in DEVICES:
        bus.register_object(path, node.interfaces[1], handle, None, None)
    Gio.bus_own_name_on_connection(bus, "org.bluez", Gio.BusNameOwnerFlags.NONE,
                                   lambda *a: print("ready", flush=True), None)
    GLib.MainLoop().run()


if __name__ == "__main__":
    sys.exit(main())
