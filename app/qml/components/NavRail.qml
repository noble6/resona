import QtQuick

// M3 Expressive navigation rail with a stretching active indicator.
Item {
    id: root
    property int current: 0
    property var items: []
    signal picked(int index)
    width: 96

    Column {
        id: col
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 28
        spacing: 6

        MorphShape {
            id: logo
            anchors.horizontalCenter: parent.horizontalCenter
            width: 56; height: 56
            shape: audio.params.enable ? "cookie12" : "circle"
            color: Theme.primary; color2: Theme.tertiary
            spinning: audio.processing && audio.params.enable
            spinDuration: 9000
            Icon { anchors.centerIn: parent; name: "waves"; size: 26; color: Theme.inkPrimary }
        }
        Item { width: 1; height: 26 }

        Repeater {
            model: root.items
            delegate: Item {
                id: it
                required property var modelData
                required property int index
                readonly property bool sel: root.current === index
                activeFocusOnTab: true
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData.label
                Accessible.selected: sel
                Accessible.onPressAction: root.picked(index)
                Keys.onShortcutOverride: (event) => { if (event.key === Qt.Key_Space) event.accepted = true }
                Keys.onPressed: (event) => {
                    if ([Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter].indexOf(event.key) < 0) return
                    event.accepted = true
                    if (!event.isAutoRepeat) root.picked(index)
                }
                FocusRing {}
                width: 80; height: 68
                Rectangle {
                    id: pill
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 4
                    height: 32
                    width: it.sel ? 56 : (ma.containsMouse ? 56 : 24)
                    radius: 16
                    color: it.sel ? Theme.secondaryContainer : Theme.alpha(Theme.ink, ma.containsMouse ? 0.08 : 0)
                    Behavior on width { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack; easing.overshoot: 2 } }
                    Behavior on color { ColorAnimation { duration: Theme.fast } }
                    Icon { anchors.centerIn: parent; name: it.modelData.icon; size: 24
                           color: it.sel ? Theme.inkSecondaryContainer : Theme.inkVariant
                           scale: it.sel ? 1.08 : 1; Behavior on scale { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } } }
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: pill.bottom; anchors.topMargin: 4
                    text: it.modelData.label
                    color: it.sel ? Theme.ink : Theme.inkVariant
                    font.family: Theme.font; font.pixelSize: 12
                    font.weight: it.sel ? Font.Bold : Font.Medium
                }
                MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: root.picked(it.index) }
            }
        }
    }
}
