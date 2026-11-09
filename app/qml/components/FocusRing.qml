import QtQuick

Rectangle {
    anchors.fill: parent
    anchors.margins: -3
    radius: 12
    color: "transparent"
    border.width: 2
    border.color: Theme.primary
    visible: parent.activeFocus
    Accessible.ignored: true
}
