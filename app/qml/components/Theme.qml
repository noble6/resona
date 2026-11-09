pragma Singleton
import QtQuick

// Material 3 dynamic color, derived from a single seed (approximated in HSL).
QtObject {
    id: t
    property color seed: audio ? audio.accent : "#8B5CF6"
    property bool dark: audio ? audio.dark : true
    readonly property real h: seed.hslHue < 0 ? 0.75 : seed.hslHue
    readonly property real s: Math.max(0.45, seed.hslSaturation)
    readonly property string font: fontFamily

    function tone(hue, sat, l) { return Qt.hsla(((hue % 1) + 1) % 1, sat, l / 100, 1) }
    function pick(d, l) { return dark ? d : l }

    // accent roles
    readonly property color primary: pick(tone(h, s, 78), tone(h, s * 0.9, 42))
    readonly property color inkPrimary: pick(tone(h, s, 16), tone(h, s, 99))
    readonly property color primaryContainer: pick(tone(h, s * 0.75, 30), tone(h, s, 90))
    readonly property color inkPrimaryContainer: pick(tone(h, s, 92), tone(h, s, 12))
    readonly property color secondary: pick(tone(h, 0.28, 78), tone(h, 0.25, 40))
    readonly property color secondaryContainer: pick(tone(h, 0.22, 24), tone(h, 0.35, 88))
    readonly property color inkSecondaryContainer: pick(tone(h, 0.3, 90), tone(h, 0.3, 12))
    readonly property color tertiary: pick(tone(h + 0.17, s * 0.9, 76), tone(h + 0.17, s * 0.8, 40))
    readonly property color tertiaryContainer: pick(tone(h + 0.17, s * 0.6, 28), tone(h + 0.17, s, 88))
    readonly property color inkTertiaryContainer: pick(tone(h + 0.17, s, 92), tone(h + 0.17, s, 12))
    readonly property color error: pick("#FFB4AB", "#BA1A1A")

    // tinted neutrals
    readonly property color surface: pick(tone(h, 0.16, 6), tone(h, 0.3, 98))
    readonly property color surfaceDim: pick(tone(h, 0.16, 4), tone(h, 0.2, 90))
    readonly property color surfaceContainerLowest: pick(tone(h, 0.14, 3.5), tone(h, 0.3, 100))
    readonly property color surfaceContainerLow: pick(tone(h, 0.14, 9), tone(h, 0.3, 96))
    readonly property color surfaceContainer: pick(tone(h, 0.13, 11.5), tone(h, 0.28, 94))
    readonly property color surfaceContainerHigh: pick(tone(h, 0.12, 15.5), tone(h, 0.25, 91.5))
    readonly property color surfaceContainerHighest: pick(tone(h, 0.11, 20), tone(h, 0.22, 89))
    readonly property color ink: pick(tone(h, 0.12, 91), tone(h, 0.2, 10))
    readonly property color inkVariant: pick(tone(h, 0.12, 74), tone(h, 0.12, 32))
    readonly property color outline: pick(tone(h, 0.08, 52), tone(h, 0.08, 52))
    readonly property color outlineVariant: pick(tone(h, 0.1, 26), tone(h, 0.12, 82))
    readonly property color inverseSurface: pick(tone(h, 0.12, 90), tone(h, 0.12, 20))
    readonly property color inverseOnSurface: pick(tone(h, 0.12, 15), tone(h, 0.12, 95))

    // motion (M3 expressive springs, approximated)
    readonly property bool reducedMotion: audio ? audio.reducedMotion : false
    readonly property int fast: reducedMotion ? 0 : 200
    readonly property int medium: reducedMotion ? 0 : 380
    readonly property int slow: reducedMotion ? 0 : 560
    readonly property var spatial: Easing.OutBack
    readonly property real overshoot: 1.25

    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
    function mix(a, b, k) { return Qt.rgba(a.r + (b.r - a.r) * k, a.g + (b.g - a.g) * k, a.b + (b.b - a.b) * k, 1) }
}
