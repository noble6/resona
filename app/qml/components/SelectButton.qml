import QtQuick
import QtQuick.Controls.Basic as T

// Compact pill that opens an M3 menu of options.
Rectangle {
    id: root
    property var options: []          // strings
    property string current: ""
    property string placeholder: "Choose"
    signal picked(string value)
    activeFocusOnTab: true
    Accessible.role: Accessible.ComboBox
    Accessible.name: placeholder
    Accessible.description: current
    Accessible.expandable: true
    Accessible.expanded: menu.opened
    Accessible.onPressAction: menu.open()
    Keys.onShortcutOverride: (event) => { if (event.key === Qt.Key_Space) event.accepted = true }
    Keys.onPressed: (event) => {
        if ([Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Down].indexOf(event.key) < 0) return
        event.accepted = true
        if (!event.isAutoRepeat) menu.open()
    }
    FocusRing { radius: 21 }
    height: 36; radius: 18
    width: row.implicitWidth + 28
    color: current ? Theme.secondaryContainer : Theme.surfaceContainerHighest
    Row {
        id: row
        anchors.centerIn: parent; spacing: 4
        Label { text: root.current || root.placeholder; role: "labelL"
                color: root.current ? Theme.inkSecondaryContainer : Theme.inkVariant; anchors.verticalCenter: parent.verticalCenter }
        Icon { name: "expand"; size: 18; color: Theme.inkVariant; anchors.verticalCenter: parent.verticalCenter }
    }
    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: menu.open() }
    T.Menu {
        id: menu
        y: root.height + 4
        padding: 8
        width: Math.max(200, root.width)
        height: Math.min(implicitHeight, 320)
        focus: true
        onAboutToShow: currentIndex = Math.max(0, root.options.indexOf(root.current))
        background: Rectangle { color: Theme.surfaceContainerHigh; radius: 16; border.width: 1; border.color: Theme.outlineVariant }
        Instantiator {
            model: root.options
            delegate: T.MenuItem {
                required property string modelData
                text: modelData || "None"
                implicitHeight: 40
                onTriggered: { menu.close(); root.picked(modelData) }
                contentItem: Label { text: parent.text; role: "bodyL"; elide: Text.ElideRight }
                background: Rectangle {
                    radius: 12
                    color: parent.highlighted ? Theme.alpha(Theme.ink, 0.08)
                           : (parent.modelData === root.current ? Theme.secondaryContainer : "transparent")
                }
            }
            onObjectAdded: (index, object) => menu.insertItem(index, object)
            onObjectRemoved: (index, object) => menu.removeItem(object)
        }
    }
}
