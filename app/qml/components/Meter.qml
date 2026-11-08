import QtQuick

Item {
    id: root
    property real value: 0          // 0..1
    property string label: ""
    property bool vertical: true
    implicitWidth: vertical ? 28 : 200
    implicitHeight: vertical ? 160 : 12
    property real peak: 0
    onValueChanged: if (value > peak) peak = value
    Timer { interval: 50; running: root.peak > 0; repeat: true; onTriggered: root.peak = Math.max(root.value, root.peak - 0.012) }

    Rectangle {
        id: bg
        anchors.fill: parent
        radius: root.vertical ? width / 2 : height / 2
        color: Theme.surfaceContainerHighest
        clip: true
        Rectangle {
            radius: bg.radius
            width: root.vertical ? parent.width : Math.max(parent.height, parent.width * root.value)
            height: root.vertical ? Math.max(parent.width, parent.height * root.value) : parent.height
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            visible: root.value > 0.005
            gradient: Gradient {
                orientation: root.vertical ? Gradient.Vertical : Gradient.Horizontal
                GradientStop { position: 0; color: root.vertical ? Theme.tertiary : Theme.primary }
                GradientStop { position: 1; color: root.vertical ? Theme.primary : Theme.tertiary }
            }
            Behavior on height { NumberAnimation { duration: 60 } }
            Behavior on width { NumberAnimation { duration: 60 } }
        }
        Rectangle {
            visible: root.peak > 0.01
            color: Theme.ink
            radius: 2
            width: root.vertical ? parent.width - 8 : 4
            height: root.vertical ? 4 : parent.height - 4
            x: root.vertical ? 4 : Math.min(parent.width - 6, parent.width * root.peak)
            y: root.vertical ? Math.max(2, parent.height * (1 - root.peak)) : 2
        }
    }
}
