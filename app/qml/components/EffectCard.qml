import QtQuick
import QtQuick.Layouts

// Card for one DSP block: shape-icon, title, subtitle, switch, controls.
Card {
    id: root
    property string title
    property string subtitle
    property string icon: "sparkle"
    property string shape: "cookie9"
    property string toggleKey: ""
    readonly property bool on: toggleKey === "" || !!audio.params[toggleKey]
    default property alias content: body.data
    implicitHeight: col.implicitHeight + 2 * pad
    color: on ? Theme.surfaceContainer : Theme.surfaceContainerLow

    ColumnLayout {
        id: col
        anchors.fill: parent
        anchors.margins: root.pad
        spacing: 18
        RowLayout {
            spacing: 16
            Layout.fillWidth: true
            MorphShape {
                width: 52; height: 52
                Layout.preferredWidth: 52; Layout.preferredHeight: 52
                shape: root.on ? root.shape : "circle"
                color: root.on ? Theme.primaryContainer : Theme.surfaceContainerHighest
                color2: root.on ? Theme.tertiaryContainer : Theme.surfaceContainerHighest
                spinning: root.on && audio.processing
                spinDuration: 16000
                Icon { anchors.centerIn: parent; name: root.icon; size: 24
                       color: root.on ? Theme.inkPrimaryContainer : Theme.inkVariant }
            }
            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true
                Label { text: root.title; role: "titleL"; emphasized: true }
                Label { text: root.subtitle; role: "body"; color: Theme.inkVariant
                        Layout.fillWidth: true; elide: Text.ElideRight }
            }
            M3Switch {
                Accessible.name: root.title
                visible: root.toggleKey !== ""
                checked: root.on
                onToggled: (v) => audio.setParam(root.toggleKey, v ? 1 : 0)
            }
        }
        ColumnLayout {
            id: body
            Layout.fillWidth: true
            spacing: 14
            enabled: root.on
            opacity: root.on ? 1 : 0.5
            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
        }
    }
}
