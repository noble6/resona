import QtQuick
import QtQuick.Window
import "components"
import "pages"

Window {
    id: win
    width: 1340; height: 900
    minimumWidth: 1040; minimumHeight: 760
    title: "Resona"
    color: Theme.surface
    property int page: 0
    property bool closeToTray: false
    Behavior on color { ColorAnimation { duration: Theme.medium } }

    onVisibleChanged: audio.setVisualsActive(visible)
    onClosing: (close) => {
        if (closeToTray) { close.accepted = false; win.hide(); audio.setVisualsActive(false) }
    }

    NavRail {
        id: rail
        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        current: win.page
        items: [{ icon: "home", label: "Sound" }, { icon: "eq", label: "Equalizer" }, { icon: "space", label: "Space" },
                { icon: "speed", label: "Dynamics" }, { icon: "hearing", label: "Correct" },
                { icon: "chip", label: "Hardware" }, { icon: "settings", label: "Settings" }]
        onPicked: (i) => win.page = i
    }

    Rectangle {
        id: stage
        anchors.left: rail.right; anchors.right: parent.right
        anchors.top: parent.top; anchors.bottom: parent.bottom
        anchors.margins: 8; anchors.leftMargin: 0
        radius: 32
        color: Theme.surfaceContainerLowest
        clip: true
        // Render pages into their own texture: shapes can never bleed past the stage,
        // whatever the scene graph does with nested clips.
        layer.enabled: true
        layer.samples: 4
        layer.smooth: true

        component PageSlot: Item {
            id: slot
            property int index
            default property alias content: holder.data
            readonly property bool shown: win.page === index
            anchors.fill: parent
            visible: opacity > 0.01
            opacity: shown ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: shown ? 320 : 120; easing.type: Easing.OutCubic } }
            Item {
                id: holder
                // Shape nodes ignore an invisible ancestor here; hide the page item itself too
                visible: slot.opacity > 0.01
                width: parent.width; height: parent.height
                y: slot.shown ? 0 : 36
                scale: slot.shown ? 1 : 0.985
                Behavior on y { NumberAnimation { duration: 460; easing.type: Easing.OutBack; easing.overshoot: 1.1 } }
                Behavior on scale { NumberAnimation { duration: 460; easing.type: Easing.OutCubic } }
            }
        }
        PageSlot { index: 0; HomePage { anchors.fill: parent } }
        PageSlot { index: 1; EqPage { anchors.fill: parent } }
        PageSlot { index: 2; SpacePage { anchors.fill: parent } }
        PageSlot { index: 3; DynamicsPage { anchors.fill: parent } }
        PageSlot { index: 4; CorrectionPage { anchors.fill: parent } }
        PageSlot { index: 5; HardwarePage { anchors.fill: parent } }
        PageSlot { index: 6; SettingsPage { anchors.fill: parent } }
    }

    // snackbar
    Rectangle {
        id: snack
        property string text
        anchors.horizontalCenter: stage.horizontalCenter
        y: shown ? parent.height - height - 32 : parent.height + 20
        property bool shown: false
        Behavior on y { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
        height: 52; radius: 16
        width: snackText.implicitWidth + 48
        color: Theme.inverseSurface
        Label { id: snackText; anchors.centerIn: parent; text: snack.text; role: "bodyL"; color: Theme.inverseOnSurface }
        Timer { id: snackTimer; interval: 3500; onTriggered: snack.shown = false }
        Connections { target: audio; function onToast(msg) { snack.text = msg; snack.shown = true; snackTimer.restart() } }
    }

    Shortcut { sequence: "Ctrl+1"; onActivated: win.page = 0 }
    Shortcut { sequence: "Ctrl+2"; onActivated: win.page = 1 }
    Shortcut { sequence: "Ctrl+3"; onActivated: win.page = 2 }
    Shortcut { sequence: "Ctrl+4"; onActivated: win.page = 3 }
    Shortcut { sequence: "Ctrl+5"; onActivated: win.page = 4 }
    Shortcut { sequence: "Ctrl+6"; onActivated: win.page = 5 }
    Shortcut { sequence: "Ctrl+7"; onActivated: win.page = 6 }
    Shortcut { sequence: "Space"; onActivated: audio.setEnabled(!audio.params.enable) }
}
