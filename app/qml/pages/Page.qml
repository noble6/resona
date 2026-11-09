import QtQuick
import QtQuick.Window
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

    function revealFocus() {
        const window = root.Window.window
        const item = window ? window.activeFocusItem : null
        if (!item || !root.visible || root.height <= 0) return
        let ancestor = item
        while (ancestor && ancestor !== root.contentItem) ancestor = ancestor.parent
        if (!ancestor) return
        const top = item.mapToItem(root.contentItem, 0, 0).y
        const bottom = item.mapToItem(root.contentItem, 0, item.height).y
        let next = root.contentY
        if (top < next + 12) next = top - 12
        else if (bottom > next + root.height - 12) next = bottom - root.height + 12
        next = Math.max(root.originY, Math.min(root.originY + Math.max(0, root.contentHeight - root.height), next))
        if (next !== root.contentY) {
            root.cancelFlick()
            root.contentY = next
        }
    }
    Connections {
        target: root.Window.window
        function onActiveFocusItemChanged() { Qt.callLater(root.revealFocus) }
    }
    onHeightChanged: Qt.callLater(root.revealFocus)

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
