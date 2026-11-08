import QtQuick

// Live Intelligent EQ gains: one pill per band, growing up (boost) or down (cut).
Row {
    id: root
    property var gains: []
    property real range: 6
    spacing: 8
    height: 96
    Repeater {
        model: 10
        delegate: Item {
            required property int index
            readonly property real g: root.gains[index] || 0
            width: (root.width - root.spacing * 9) / 10; height: root.height
            Rectangle { anchors.centerIn: parent; width: parent.width; height: 2; color: Theme.outlineVariant }
            Rectangle {
                width: Math.min(14, parent.width); radius: width / 2
                anchors.horizontalCenter: parent.horizontalCenter
                height: Math.max(width, Math.abs(g) / root.range * (parent.height / 2 - 12) + width)
                y: g >= 0 ? parent.height / 2 - height + width / 2 : parent.height / 2 - width / 2
                color: g >= 0 ? Theme.primary : Theme.tertiary
                opacity: Math.abs(g) < 0.1 ? 0.35 : 1
                Behavior on height { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
                Behavior on y { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
            }
            Text { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: -18
                   text: ["32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"][index]
                   color: Theme.inkVariant; font.family: Theme.font; font.pixelSize: 10 }
        }
    }
}
