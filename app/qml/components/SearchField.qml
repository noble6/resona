import QtQuick

// M3 search bar: full pill, leading icon, trailing clear.
Rectangle {
    id: root
    property alias text: input.text
    property string placeholder: "Search"
    property bool busy: false
    property string icon: "search"
    signal accepted(string text)
    signal edited(string text)
    height: 56; radius: 28
    color: input.activeFocus ? Theme.surfaceContainerHighest : Theme.surfaceContainerHigh
    border.width: input.activeFocus ? 2 : 0
    border.color: Theme.primary
    Behavior on color { ColorAnimation { duration: Theme.fast } }
    Icon { id: ic; name: root.icon; size: 24; color: Theme.inkVariant; x: 18; anchors.verticalCenter: parent.verticalCenter }
    TextInput {
        id: input
        anchors.left: ic.right; anchors.leftMargin: 14
        anchors.right: clear.left; anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.ink
        font.family: Theme.font; font.pixelSize: 16
        selectionColor: Theme.primary; selectedTextColor: Theme.inkPrimary
        clip: true
        onAccepted: root.accepted(text)
        onTextEdited: root.edited(text)
        Text { visible: !input.text && !input.activeFocus; text: root.placeholder; color: Theme.inkVariant
               font: input.font; anchors.verticalCenter: parent.verticalCenter }
    }
    MorphShape {
        id: spinner
        visible: root.busy
        width: 24; height: 24; shape: "cookie9"; spinning: true; spinDuration: 1200
        color: Theme.primary
        anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter
    }
    Icon {
        id: clear
        name: "close"; size: 22; color: Theme.inkVariant
        visible: input.text !== "" && !root.busy
        anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter
        MouseArea { anchors.fill: parent; anchors.margins: -8; cursorShape: Qt.PointingHandCursor
                    onClicked: { input.text = ""; root.edited("") } }
    }
    MouseArea { anchors.fill: parent; z: -1; onClicked: input.forceActiveFocus(); cursorShape: Qt.IBeamCursor }
}
