import QtQuick
import QtQuick.Controls.Basic as T

// Compact pill that opens an M3 menu of options.
Rectangle {
    id: root
    property var options: []          // strings
    property string current: ""
    property string placeholder: "Choose"
    signal picked(string value)
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
    T.Popup {
        id: menu
        y: root.height + 4
        padding: 8
        background: Rectangle { color: Theme.surfaceContainerHigh; radius: 16; border.width: 1; border.color: Theme.outlineVariant }
        contentItem: Column {
            spacing: 2
            Repeater {
                model: root.options
                delegate: Rectangle {
                    required property string modelData
                    width: Math.max(180, t.implicitWidth + 32); height: 40; radius: 12
                    color: ma.containsMouse ? Theme.alpha(Theme.ink, 0.08) : (modelData === root.current ? Theme.secondaryContainer : "transparent")
                    Label { id: t; text: modelData || "None"; anchors.verticalCenter: parent.verticalCenter; x: 16; role: "bodyL" }
                    MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: { menu.close(); root.picked(parent.modelData) } }
                }
            }
        }
    }
}
