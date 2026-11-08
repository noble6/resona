import QtQuick
import QtQuick.Layouts
import QtQuick.Dialogs
import "../components"

Page {
    id: page
    title: "Correction"
    subtitle: "Make your headphones measure right, then add any impulse response you love"
    readonly property var corr: audio.correction
    readonly property var ir: audio.ir

    FileDialog {
        id: eqFile
        title: "Import EQ (AutoEq / EqualizerAPO .txt, ViPER DDC .vdc)"
        nameFilters: ["EQ files (*.txt *.vdc)", "All files (*)"]
        onAccepted: audio.importCorrection(selectedFile)
    }
    FileDialog {
        id: irFile
        title: "Load impulse response (.wav / .irs)"
        nameFilters: ["Impulse responses (*.wav *.irs *.WAV *.IRS)", "All files (*)"]
        onAccepted: audio.loadIr(selectedFile)
    }

    RowLayout {
        width: parent.width
        spacing: 20
        // ------------------------------------------------ AutoEq search
        Card {
            Layout.fillWidth: true; Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            implicitHeight: searchCol.implicitHeight + 56
            ColumnLayout {
                id: searchCol
                anchors.fill: parent; anchors.margins: 28
                spacing: 14
                RowLayout {
                    spacing: 14
                    MorphShape { width: 52; height: 52; Layout.preferredWidth: 52; Layout.preferredHeight: 52
                                 shape: "flower8"; color: Theme.primaryContainer; color2: Theme.tertiaryContainer
                                 Icon { anchors.centerIn: parent; name: "headphones"; color: Theme.inkPrimaryContainer } }
                    Column { Layout.fillWidth: true
                        Label { text: "AutoEq"; role: "titleL"; emphasized: true }
                        Label { text: audio.autoEqCount ? audio.autoEqCount + " headphones & IEMs, measured" : "Thousands of headphones & IEMs, measured"
                                role: "body"; color: Theme.inkVariant } }
                }
                SearchField {
                    Layout.fillWidth: true
                    placeholder: "Find your headphones, e.g. HD 650, Moondrop, AirPods"
                    busy: audio.searching
                    onEdited: (t) => searchDelay.restart()
                    onAccepted: (t) => audio.searchAutoEq(t)
                    Timer { id: searchDelay; interval: 280; onTriggered: audio.searchAutoEq(parent.text) }
                }
                Repeater {
                    model: audio.autoEqResults.slice(0, 12)
                    delegate: Rectangle {
                        id: hit
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        height: 60; radius: ma.containsMouse ? 30 : 16
                        color: ma.containsMouse ? Theme.surfaceContainerHigh : "transparent"
                        Behavior on radius { NumberAnimation { duration: Theme.medium; easing.type: Easing.OutBack } }
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 16
                            Column { Layout.fillWidth: true
                                Label { text: hit.modelData.name; role: "bodyL"; elide: Text.ElideRight; width: parent.width }
                                Label { text: hit.modelData.source; role: "bodyS"; color: Theme.inkVariant } }
                            Icon { name: "download"; size: 22; color: Theme.primary }
                        }
                        MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: audio.applyAutoEq(hit.index) }
                    }
                }
                Label {
                    visible: audio.autoEqResults.length === 0
                    Layout.fillWidth: true; wrapMode: Text.WordWrap
                    text: "Search downloads the AutoEq index once (MIT-licensed, by Jaakko Pasanen). Picking a result applies a parametric EQ that moves your headphone toward the Harman research target."
                    role: "body"; color: Theme.inkVariant
                }
                Btn { text: "Import EQ file…"; icon: "upload"; variant: "outlined"; onClicked: eqFile.open() }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true; Layout.preferredWidth: 1
            Layout.alignment: Qt.AlignTop
            spacing: 20
            // ------------------------------------------------ active correction
            EffectCard {
                Layout.fillWidth: true
                title: page.corr.name || "No correction loaded"
                subtitle: page.corr.name ? page.corr.source + " · " + page.corr.count + " filters" : "Search AutoEq or import a file"
                icon: "hearing"; shape: "cookie12"; toggleKey: page.corr.name ? "corr_on" : ""
                CurveView { Layout.fillWidth: true; Layout.preferredHeight: 170; points: audio.correctionCurve }
                ParamSlider { Layout.fillWidth: true; key: "corr_preamp"; label: "Preamp"; from: -20; to: 6; stepSize: 0.1
                              visible: !!page.corr.name; bipolar: true
                              format: function(v) { return (v > 0 ? "+" : "") + v.toFixed(1) + " dB" } }
                Btn { visible: !!page.corr.name; text: "Remove"; icon: "delete"; variant: "text"; onClicked: audio.clearCorrection() }
            }
            // ------------------------------------------------ convolver
            Card {
                Layout.fillWidth: true
                implicitHeight: irCol.implicitHeight + 56
                color: page.ir.on ? Theme.surfaceContainer : Theme.surfaceContainerLow
                ColumnLayout {
                    id: irCol
                    anchors.fill: parent; anchors.margins: 28
                    spacing: 14
                    RowLayout {
                        spacing: 16
                        MorphShape { width: 52; height: 52; Layout.preferredWidth: 52; Layout.preferredHeight: 52
                                     shape: page.ir.on ? "burst12" : "circle"; spinning: !!page.ir.on && audio.processing
                                     color: page.ir.on ? Theme.primaryContainer : Theme.surfaceContainerHighest
                                     color2: page.ir.on ? Theme.tertiaryContainer : Theme.surfaceContainerHighest
                                     Icon { anchors.centerIn: parent; name: "waves"; color: page.ir.on ? Theme.inkPrimaryContainer : Theme.inkVariant } }
                        Column { Layout.fillWidth: true
                            Label { text: "Convolver"; role: "titleL"; emphasized: true }
                            Label { text: page.ir.name ? page.ir.name + " · " + page.ir.channels + " ch · " + page.ir.seconds + " s · " + (page.ir.rate / 1000) + " kHz"
                                                      : "ViPER/JamesDSP IRS, room impulses, HRIRs or any WAV"
                                    role: "body"; color: Theme.inkVariant; width: parent.width; elide: Text.ElideRight } }
                        M3Switch { visible: !!page.ir.name; checked: !!page.ir.on; onToggled: (v) => audio.setIrOn(v) }
                    }
                    Item {
                        visible: !!page.ir.name
                        Layout.fillWidth: true; implicitHeight: 64
                        Column {
                            anchors.fill: parent; spacing: 2
                            Item { width: parent.width; height: 20
                                Label { text: "Wet / dry"; role: "labelL"; color: Theme.inkVariant }
                                Label { anchors.right: parent.right; text: Math.round((page.ir.mix || 0) * 100) + "%"; role: "labelL"; emphasized: true } }
                            WavySlider { width: parent.width; value: page.ir.mix || 0; enabled: !!page.ir.on
                                         onMoved: (v) => audio.setIrMix(v) }
                        }
                    }
                    Row {
                        spacing: 10
                        Btn { text: page.ir.name ? "Change IR…" : "Load impulse response…"; icon: "folder"; variant: "tonal"; onClicked: irFile.open() }
                        Btn { visible: !!page.ir.name; text: "Remove"; icon: "delete"; variant: "text"; onClicked: audio.clearIr() }
                    }
                }
            }
        }
    }
}
