import QtQuick
import QtQuick.Controls.Basic
import "../components"

// Scrollable page scaffold with an expressive header.
Flickable {
    id: root
    property string title
    property string subtitle
    property alias headerRight: right.data
    default property alias content: body.data
    contentHeight: body.y + body.implicitHeight + 40
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    Item {
        id: header
        x: 40; y: 28
        width: root.width - 80; height: 84
        Column {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, parent.width - right.width - 24)
            Label { width: parent.width; elide: Text.ElideRight; text: root.title; role: "displayS"; emphasized: true; font.variableAxes: { "wdth": 118 } }
            Label { width: parent.width; elide: Text.ElideRight; text: root.subtitle; role: "bodyL"; color: Theme.inkVariant; visible: text !== "" }
        }
        Row { id: right; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 12 }
    }
    Column {
        id: body
        x: 40; y: header.y + header.height + 20
        width: root.width - 80
        spacing: 20
    }
}
