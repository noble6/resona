import QtQuick

// Top-down soundstage: listener, virtual sources, reflections, room ripples.
Canvas {
    id: c
    property real t: 0
    readonly property var p: audio.params
    readonly property real level: audio.meters.out || 0
    Timer { interval: 16; repeat: true; running: c.visible; onTriggered: { c.t += 0.016; c.requestPaint() } }
    function rgba(col, a) { return "rgba(" + Math.round(col.r * 255) + "," + Math.round(col.g * 255) + "," + Math.round(col.b * 255) + "," + Math.max(0, a) + ")" }
    function orb(ctx, x, y, r, col, a) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, r * 2.6)
        g.addColorStop(0, rgba(col, a)); g.addColorStop(0.35, rgba(col, a * 0.5)); g.addColorStop(1, rgba(col, 0))
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 2.6, 0, Math.PI * 2); ctx.fill()
        ctx.fillStyle = rgba(col, Math.min(1, a + 0.2)); ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill()
    }
    onPaint: {
        const ctx = getContext("2d"); ctx.reset()
        const w = width, h = height, cx = w / 2, cy = h * 0.6
        const R = Math.min(w * 0.42, h * 0.5)
        const on = p.enable > 0
        const stage = on && p.stage_on ? 1 : 0
        const width_ = 1 + ((p.stage_width || 1) - 1) * stage
        const depth = on && p.stage_on ? (p.stage_depth || 0) : 0
        const amb = on && p.amb_on ? (p.amb_mix || 0) : 0
        const size = p.amb_size || 0.4
        const xf = on && p.hrtf_on ? 0.85 : (on && p.xfeed_on ? (p.xfeed_amt || 0) : 0)
        const voice = on && p.voice_on ? (p.voice_amt || 0) : 0
        const pulse = 0.6 + 0.4 * level

        // room rings
        for (let i = 1; i <= 4; i++) {
            ctx.strokeStyle = rgba(Theme.outlineVariant, 0.5 - i * 0.08)
            ctx.lineWidth = 1; ctx.setLineDash([2, 6])
            ctx.beginPath(); ctx.arc(cx, cy, R * i / 4 * (0.7 + size * 0.5), 0, Math.PI * 2); ctx.stroke()
        }
        ctx.setLineDash([])
        // ambience ripples
        if (amb > 0.01) {
            for (let k = 0; k < 4; k++) {
                const ph = ((t * (0.35 + 0.25 * (1 - size)) + k / 4) % 1)
                ctx.strokeStyle = rgba(Theme.tertiary, (1 - ph) * amb * 1.6)
                ctx.lineWidth = 2 + 6 * (1 - ph)
                ctx.beginPath(); ctx.arc(cx, cy, 30 + ph * R * (0.8 + size * 0.6), 0, Math.PI * 2); ctx.stroke()
            }
        }
        // sources
        const hrtf = on && p.hrtf_on ? 1 : 0
        const ang = Math.min(80, (hrtf ? (p.hrtf_angle || 30) : 30) * width_) * Math.PI / 180
        const srcs = [[cx - Math.sin(ang) * R * 0.78, cy - Math.cos(ang) * R * 0.78], [cx + Math.sin(ang) * R * 0.78, cy - Math.cos(ang) * R * 0.78]]
        // reflections
        if (depth > 0.01) {
            for (const s of srcs)
                for (let k = 1; k <= 3; k++) {
                    const dx = (s[0] - cx) * (1 + k * 0.28), dy = (s[1] - cy) * (1 + k * 0.28)
                    orb(ctx, cx + dx, cy + dy, 5 - k, Theme.primary, depth * (0.55 - k * 0.12) * pulse)
                }
        }
        // crossfeed arcs
        if (xf > 0.01) {
            ctx.lineWidth = 2; ctx.setLineDash([4, 6])
            ctx.lineDashOffset = -t * 30
            for (let i = 0; i < 2; i++) {
                const s = srcs[i], ear = [cx + (i ? -26 : 26), cy]
                ctx.strokeStyle = rgba(Theme.secondary, xf * 0.9)
                ctx.beginPath(); ctx.moveTo(s[0], s[1])
                ctx.quadraticCurveTo(cx, cy - R * 0.25, ear[0], ear[1]); ctx.stroke()
            }
            ctx.setLineDash([])
        }
        // direct paths
        for (let i = 0; i < 2; i++) {
            const s = srcs[i]
            const g = ctx.createLinearGradient(s[0], s[1], cx, cy)
            g.addColorStop(0, rgba(Theme.primary, 0.5)); g.addColorStop(1, rgba(Theme.primary, 0))
            ctx.strokeStyle = g; ctx.lineWidth = 3
            ctx.beginPath(); ctx.moveTo(s[0], s[1]); ctx.lineTo(cx + (i ? 22 : -22), cy); ctx.stroke()
        }
        for (const s of srcs) orb(ctx, s[0], s[1], 11 + 3 * level, Theme.primary, 0.85 * pulse)
        if (voice > 0.01) orb(ctx, cx, cy - R * 0.82, 7 + 8 * voice, Theme.tertiary, 0.4 + 0.5 * voice)
        // listener (top-down head)
        ctx.fillStyle = rgba(Theme.surfaceContainerHighest, 1)
        ctx.strokeStyle = rgba(Theme.outline, 1); ctx.lineWidth = 2
        ctx.beginPath(); ctx.ellipse(cx - 22, cy - 26, 44, 52); ctx.fill(); ctx.stroke()
        ctx.fillStyle = rgba(Theme.inkVariant, 1)
        ctx.beginPath(); ctx.ellipse(cx - 28, cy - 8, 10, 16); ctx.fill()
        ctx.beginPath(); ctx.ellipse(cx + 18, cy - 8, 10, 16); ctx.fill()
        ctx.beginPath(); ctx.moveTo(cx - 6, cy - 25); ctx.lineTo(cx, cy - 34); ctx.lineTo(cx + 6, cy - 25); ctx.closePath(); ctx.fill()
        // labels
        ctx.fillStyle = rgba(Theme.inkVariant, 0.9)
        ctx.font = "600 12px '" + Theme.font + "'"
        ctx.fillText("L", srcs[0][0] - 4, srcs[0][1] - 24); ctx.fillText("R", srcs[1][0] - 4, srcs[1][1] - 24)
    }
}
