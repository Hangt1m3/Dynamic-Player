from array import array

from PyQt5.QtCore import Qt, QElapsedTimer
from PyQt5.QtGui import (
    QColor,
    QVector2D,
    QVector3D,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLBuffer,
    QOpenGLVersionProfile,
    QSurfaceFormat,
)
from PyQt5.QtWidgets import QOpenGLWidget


GL_FLOAT = 0x1406
GL_TRIANGLE_STRIP = 0x0005
GL_COLOR_BUFFER_BIT = 0x00004000


VERTEX_SHADER = """
attribute vec2 a_pos;
varying vec2 v_uv;

void main() {
    v_uv = (a_pos + vec2(1.0, 1.0)) * 0.5;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""


FRAGMENT_SHADER = """
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_intensity;
uniform vec3 u_baseColor;
uniform float u_warpAmount;
uniform float u_baseDominance;
uniform float u_ambientMix;
uniform float u_blobCoreMix;
uniform float u_blobHaloMix;
uniform float u_blobSoftMix;
uniform float u_blobMistMix;
uniform float u_finalBasePull;
uniform float u_globalOpacity;
uniform int u_paletteSize;
uniform vec3 u_palette0;
uniform vec3 u_palette1;
uniform vec3 u_palette2;
uniform vec3 u_palette3;
uniform vec3 u_palette4;
uniform vec3 u_palette5;
uniform vec3 u_palette6;
uniform vec3 u_palette7;

varying vec2 v_uv;

float hash1(float n) {
    return fract(sin(n) * 43758.5453123);
}

float hash2(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise2(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = hash2(i);
    float b = hash2(i + vec2(1.0, 0.0));
    float c = hash2(i + vec2(0.0, 1.0));
    float d = hash2(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
    for (int i = 0; i < 3; ++i) {
        v += a * noise2(p);
        p = m * p;
        a *= 0.5;
    }
    return v;
}

vec2 flow_warp(vec2 p, float t) {
    vec2 q = vec2(
        fbm(p * 1.2 + vec2(0.0, t * 0.10)),
        fbm(p * 1.2 + vec2(5.2, -t * 0.09))
    );
    vec2 r = vec2(
        fbm(p * 2.1 + q * 1.6 + vec2(1.7, 9.2 + t * 0.07)),
        fbm(p * 2.1 + q * 1.6 + vec2(8.3, 2.8 - t * 0.08))
    );
    return (q - 0.5) * (0.18 * u_warpAmount) + (r - 0.5) * (0.14 * u_warpAmount);
}

vec2 blob_center(float i, float t) {
    float seed = i * 13.731;
    float sx = 0.5 + 0.30 * sin((0.16 + hash1(seed) * 0.24) * t + seed * 0.71);
    float sy = 0.5 + 0.30 * cos((0.13 + hash1(seed + 2.0) * 0.22) * t + seed * 1.17);
    sx += 0.08 * sin((0.58 + hash1(seed + 4.0)) * t + seed);
    sy += 0.08 * cos((0.66 + hash1(seed + 8.0)) * t + seed * 0.59);
    return vec2(sx, sy);
}

float ellipse_field(vec2 p, vec2 c, vec2 axis, float angle, float aspect) {
    vec2 d = p - c;
    d.x *= aspect;
    float ca = cos(angle);
    float sa = sin(angle);
    mat2 rot = mat2(ca, -sa, sa, ca);
    vec2 e = rot * d;
    vec2 n = e / max(axis, vec2(0.03, 0.03));
    float dist = dot(n, n);
    return 1.0 / (dist + 0.08);
}

vec3 get_palette_color(int i) {
    if (i == 0) return u_palette0;
    if (i == 1) return u_palette1;
    if (i == 2) return u_palette2;
    if (i == 3) return u_palette3;
    if (i == 4) return u_palette4;
    if (i == 5) return u_palette5;
    if (i == 6) return u_palette6;
    return u_palette7;
}

void main() {
    float aspect = u_resolution.x / max(u_resolution.y, 1.0);
    // long_axis_factor > 1 when portrait (tall), = 1 when square/landscape.
    // Scaling blob spread along the long edge ensures all palette colors stay
    // distributed and visible instead of stacking in one band.
    float long_axis_factor = max(1.0, 1.0 / max(aspect, 0.05));
    float long_spread = min(long_axis_factor, 2.0);
    // aspect_norm normalizes blob axis sizes to the short edge. Inside ellipse_field,
    // axis values are in height-normalized units (d.x *= aspect), so axis.x=0.40 means
    // the blob spans 0.40*height pixels wide. In portrait that exceeds screen width.
    // Multiplying by min(1,aspect) keeps blobs proportional to the short edge.
    float aspect_norm = min(1.0, aspect);
    vec2 centered = v_uv - vec2(0.5, 0.5);
    vec2 centered_vig = centered;
    centered_vig.x *= aspect;
    vec2 uv = v_uv;

    float t = u_time * 0.82;
    vec3 ambient = vec3(0.0);
    for (int i = 0; i < 8; ++i) {
        if (i >= u_paletteSize) {
            continue;
        }
        ambient += get_palette_color(i);
    }
    ambient /= max(float(u_paletteSize), 1.0);
    vec2 warp = flow_warp(uv * vec2(1.3, 1.1) + vec2(0.0, t * 0.06), t);
    vec2 uvw = uv + warp;

    float bg_noise = fbm(uv * vec2(1.6, 1.3) + vec2(t * 0.04, -t * 0.03));
    vec3 col = mix(u_baseColor, ambient * 0.28 + u_baseColor * 0.72, u_ambientMix + 0.05 * bg_noise);

    // Keep the player background color dominant while still breathing with soft color shifts.
    col = mix(col, u_baseColor, u_baseDominance);

    float totalGlow = 0.0;
    float totalField = 0.0;

    for (int i = 0; i < 8; ++i) {
        if (i >= u_paletteSize) {
            continue;
        }
        float fi = float(i);
        vec3 baseColorForIndex = get_palette_color(i);

        // Render multiple blobs per color so the whole screen stays active and dynamic.
        for (int j = 0; j < 4; ++j) {
            float fj = float(j);
            float idx = fi * 4.0 + fj;

            vec3 blobColor = baseColorForIndex;
            // Include base background color into one instance to preserve overall dominance.
            if (j == 3) {
                blobColor = mix(baseColorForIndex, u_baseColor, 0.62);
            }

            float speed = 0.62 + 0.95 * hash1(fi * 9.17 + fj * 17.31 + 1.3);
            float phase = fi * 1.93 + fj * 2.71 + hash1(fi * 7.1 + fj * 3.8) * 6.2831;
            vec2 c = blob_center(fi + 1.0 + fj * 0.41 + phase, t * speed);

            // Distribute blobs along the long axis so portrait/ultrawide layouts show all palette colors.
            vec2 spread = vec2(
                (fj - 1.5) * 0.50,
                (mod(fi + fj, 3.0) - 1.0) * 0.30 * long_spread
            );
            spread += vec2(
                0.22 * sin(t * (0.24 + 0.06 * speed) + phase),
                0.20 * cos(t * (0.21 + 0.05 * speed) + phase * 0.7) * long_spread
            );
            c += spread;
            c = clamp(c, vec2(0.01, 0.01), vec2(0.99, 0.99));

            float wobble = 0.08 * sin(t * (0.42 + 0.08 * speed) + idx * 2.3 + phase);
            // Scale axis by aspect_norm so blobs are always proportional to the short edge.
            vec2 axis = vec2((0.40 - 0.03 * fj) * aspect_norm, (0.29 + wobble + 0.02 * fj) * aspect_norm);
            float angle = t * (0.06 + 0.022 * speed) + idx * 1.17 + phase * 0.35;

            float f = ellipse_field(uvw, c, axis, angle, aspect) * (0.90 + 0.18 * sin(t * (0.42 + 0.08 * speed) + idx));

            float body = smoothstep(0.08, 0.50, f * u_intensity);
            float core = smoothstep(0.26, 0.82, f * u_intensity);
            float solid = smoothstep(0.52, 1.14, f * u_intensity);
            float halo = smoothstep(0.010, 0.18, f * u_intensity * 0.95);
            float soft = smoothstep(0.00, 0.12, f * u_intensity * 0.92);
            float mist = smoothstep(0.00, 0.09, f * u_intensity * 0.86);
            vec2 gel_vec = (uvw - c) * vec2(aspect, 1.0) + vec2(0.20, -0.18);
            float gel_highlight = core * smoothstep(0.30, 0.02, length(gel_vec));
            float glow = halo * 0.42 + soft * 0.22 + mist * 0.08;

            col = mix(col, blobColor, body * u_blobCoreMix);
            col = mix(col, blobColor, core * min(1.0, u_blobCoreMix * 1.18));
            if (j == 0) {
                col = mix(col, blobColor, solid * 0.96);
            }
            vec3 highlightColor = mix(blobColor, vec3(1.0), 0.16);
            col += highlightColor * gel_highlight * 0.045;
            col += blobColor * halo * u_blobHaloMix * 0.72;
            col += blobColor * soft * u_blobSoftMix * 0.68;
            col += blobColor * mist * u_blobMistMix * 0.62;
            totalGlow += glow;
            totalField += body + solid * 0.65;
        }
    }

    float layer_mix = smoothstep(0.04, 1.05, totalField / 2.6);
    col = mix(col, mix(u_baseColor, ambient, 0.24), layer_mix * 0.08);

    float vignette = smoothstep(1.20, 0.20, length(centered_vig));
    col = mix(col * 0.70, col, vignette);
    col += ambient * min(totalGlow * 0.035, 0.06);

    // Keep a persistent ambient tint so black only acts as tone, not visible gaps.
    col = mix(col, mix(ambient, u_baseColor, 0.42), 0.18);

    // Final pull toward base color so the background still reads as the dominant tone.
    col = mix(col, u_baseColor, u_finalBasePull);

    // Roll off overbright peaks before clamping so vivid colors keep their hue instead of clipping toward white.
    float peak = max(max(col.r, col.g), col.b);
    if (peak > 0.92) {
        float compress = mix(1.0, 0.92 / peak, smoothstep(0.92, 1.30, peak));
        col *= compress;
    }

    col = clamp(col, 0.0, 1.0);
    col *= u_globalOpacity;

    gl_FragColor = vec4(col, 1.0);
}
"""


PRESET_SETTINGS = {
    "ultra_soft": {
        "warp": 1.48,
        "base_dom": 0.54,
        "ambient": 0.16,
        "core": 0.44,
        "halo": 0.050,
        "soft": 0.028,
        "mist": 0.018,
        "final_base": 0.30,
    },
    "balanced": {
        "warp": 1.22,
        "base_dom": 0.52,
        "ambient": 0.22,
        "core": 0.58,
        "halo": 0.082,
        "soft": 0.048,
        "mist": 0.024,
        "final_base": 0.26,
    },
    "color_pop": {
        "warp": 1.10,
        "base_dom": 0.40,
        "ambient": 0.28,
        "core": 0.70,
        "halo": 0.100,
        "soft": 0.056,
        "mist": 0.032,
        "final_base": 0.20,
    },
}


class LavaLampGLWidget(QOpenGLWidget):
    """GPU background renderer for smooth lava-lamp style animation."""

    def __init__(self, parent=None, intensity=1.0):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setUpdateBehavior(QOpenGLWidget.NoPartialUpdate)
        fmt = self.format()
        # Capture apps can stall on vsync-bound swaps for transparent OpenGL widgets.
        # Keep OpenGL enabled, but make present non-blocking for stable screen sharing.
        fmt.setSwapInterval(0)
        self.setFormat(fmt)
        self._program = None
        self._vertex_buffer = None
        self._gl_funcs = None
        self._did_log_gl_failure = False
        self.initialization_failed = False
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._time_offset = 0.0
        self._paused = False
        self._paused_time = 0.0
        self._frame_interval_ms = 28
        self._last_update_ms = -1
        self._last_forced_repaint_ms = -1
        self._forced_repaint_interval_ms = 240
        self._palette = [QColor(29, 185, 84), QColor(15, 120, 50), QColor(60, 210, 130)]
        self._palette_from = [QColor(c) for c in self._palette]
        self._palette_to = [QColor(c) for c in self._palette]
        self._palette_transition_start_ms = -1
        self._palette_transition_duration_ms = 1200
        self._base_color = QColor(0, 0, 0)
        self._global_opacity = 1.0
        self._intensity = max(0.2, float(intensity))
        self._style_preset = "balanced"
        self._preset_params = dict(PRESET_SETTINGS["balanced"])

    def _normalize_palette(self, colors):
        normalized = [QColor(c) for c in (colors or []) if QColor(c).isValid()]
        if not normalized:
            normalized = [QColor(29, 185, 84)]
        return normalized[:8]

    def _palette_progress(self):
        if self._palette_transition_start_ms < 0:
            return 1.0
        elapsed = self._elapsed.elapsed() - self._palette_transition_start_ms
        if elapsed <= 0:
            return 0.0
        return min(1.0, float(elapsed) / float(max(1, self._palette_transition_duration_ms)))

    def _get_palette_entry(self, palette, index):
        if not palette:
            return QColor(29, 185, 84)
        return palette[min(index, len(palette) - 1)]

    def _mix_color(self, color_a, color_b, t):
        inv_t = 1.0 - t
        return QColor(
            int(color_a.red() * inv_t + color_b.red() * t),
            int(color_a.green() * inv_t + color_b.green() * t),
            int(color_a.blue() * inv_t + color_b.blue() * t),
        )

    def _current_palette(self):
        progress = self._palette_progress()
        if progress >= 1.0:
            if self._palette_transition_start_ms >= 0:
                self._palette_transition_start_ms = -1
                self._palette_from = [QColor(c) for c in self._palette_to]
            return [QColor(c) for c in self._palette_to]

        count = max(len(self._palette_from), len(self._palette_to))
        blended = []
        for idx in range(max(1, count)):
            from_color = self._get_palette_entry(self._palette_from, idx)
            to_color = self._get_palette_entry(self._palette_to, idx)
            blended.append(self._mix_color(from_color, to_color, progress))
        return blended

    def set_palette(self, colors):
        next_palette = self._normalize_palette(colors)
        current_palette = self._current_palette()
        if len(current_palette) == len(next_palette) and all(
            current_palette[i].rgba() == next_palette[i].rgba() for i in range(len(next_palette))
        ):
            self._palette = [QColor(c) for c in next_palette]
            self._palette_from = [QColor(c) for c in next_palette]
            self._palette_to = [QColor(c) for c in next_palette]
            self._palette_transition_start_ms = -1
            self.update()
            return

        self._palette_from = [QColor(c) for c in current_palette]
        self._palette_to = [QColor(c) for c in next_palette]
        self._palette = [QColor(c) for c in next_palette]
        self._palette_transition_start_ms = self._elapsed.elapsed()
        self.update()

    def set_base_color(self, color):
        qcolor = QColor(color)
        if not qcolor.isValid():
            return
        self._base_color = qcolor

    def set_global_opacity(self, value):
        self._global_opacity = max(0.0, min(1.0, float(value)))
        self.update()

    def set_intensity(self, value):
        self._intensity = max(0.2, float(value))

    def set_style_preset(self, preset_name):
        candidate = str(preset_name).strip().lower()
        if candidate not in PRESET_SETTINGS:
            candidate = "balanced"
        self._style_preset = candidate
        self._preset_params = dict(PRESET_SETTINGS[candidate])
        self.update()

    def advance(self):
        if self._paused:
            return
        now_ms = self._elapsed.elapsed()
        if self._last_update_ms >= 0 and (now_ms - self._last_update_ms) < self._frame_interval_ms:
            return
        self._last_update_ms = now_ms
        if self._last_forced_repaint_ms < 0 or (now_ms - self._last_forced_repaint_ms) >= self._forced_repaint_interval_ms:
            self._last_forced_repaint_ms = now_ms
            self.repaint()
            return
        self.update()

    def _current_time(self):
        return self._time_offset + (self._elapsed.elapsed() / 1000.0)

    def set_animation_paused(self, paused):
        paused = bool(paused)
        if paused == self._paused:
            return

        if paused:
            self._paused_time = self._current_time()
            self._paused = True
            return

        # Keep shader time continuous when refocusing so blobs do not jump.
        self._time_offset = self._paused_time - (self._elapsed.elapsed() / 1000.0)
        self._paused = False
        self._last_update_ms = -1
        self.update()

    def initializeGL(self):
        self._program = QOpenGLShaderProgram(self.context())
        self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER)
        self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER)
        if not self._program.link():
            print(f"Lava shader link failed: {self._program.log()}")
            self.initialization_failed = True
            self._program = None
            return

        vertices = array("f", [-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0])
        self._vertex_buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vertex_buffer.create()
        self._vertex_buffer.bind()
        self._vertex_buffer.allocate(vertices.tobytes(), len(vertices) * 4)
        self._vertex_buffer.release()

    def _gl(self):
        """Return a GL function table compatible with both PyQt5/PyQt6 bindings."""
        if self._gl_funcs is not None:
            return self._gl_funcs

        ctx = self.context()
        if ctx is None:
            return None

        # Qt6-style path
        if hasattr(ctx, "functions"):
            funcs = ctx.functions()
            if funcs:
                self._gl_funcs = funcs
                return self._gl_funcs

        # PyQt5 commonly exposes versionFunctions()
        if hasattr(ctx, "versionFunctions"):
            profile = QOpenGLVersionProfile()
            profile.setVersion(2, 1)
            profile.setProfile(QSurfaceFormat.NoProfile)
            funcs = ctx.versionFunctions(profile)
            if funcs is None:
                funcs = ctx.versionFunctions()
            if funcs:
                init = getattr(funcs, "initializeOpenGLFunctions", None)
                if callable(init):
                    init()
                self._gl_funcs = funcs
                return self._gl_funcs

        return None

    def resizeGL(self, width, height):
        funcs = self._gl()
        if funcs is None:
            if not self._did_log_gl_failure:
                print("Lava GL: failed to resolve OpenGL function table in resizeGL")
                self._did_log_gl_failure = True
            return
        funcs.glViewport(0, 0, width, height)

    def paintGL(self):
        funcs = self._gl()
        if funcs is None:
            if not self._did_log_gl_failure:
                print("Lava GL: failed to resolve OpenGL function table in paintGL")
                self._did_log_gl_failure = True
            return
        if self.initialization_failed:
            bg = self._base_color
            funcs.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
            funcs.glClear(GL_COLOR_BUFFER_BIT)
            return

        if self._program is None or self._vertex_buffer is None:
            bg = self._base_color
            funcs.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
            funcs.glClear(GL_COLOR_BUFFER_BIT)
            return

        # Clear to the base color first to avoid a visible flash on focus/context transitions.
        bg = self._base_color
        funcs.glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
        funcs.glClear(GL_COLOR_BUFFER_BIT)

        active_palette = self._current_palette()

        palette_vec = []
        for color in active_palette[:8]:
            palette_vec.append(QVector3D(color.redF(), color.greenF(), color.blueF()))
        while len(palette_vec) < 8:
            palette_vec.append(QVector3D(0.0, 0.0, 0.0))

        t = self._paused_time if self._paused else self._current_time()

        self._program.bind()
        self._program.setUniformValue("u_resolution", QVector2D(float(max(1, self.width())), float(max(1, self.height()))))
        self._program.setUniformValue("u_time", float(t))
        self._program.setUniformValue("u_intensity", float(self._intensity))
        self._program.setUniformValue("u_baseColor", QVector3D(bg.redF(), bg.greenF(), bg.blueF()))
        self._program.setUniformValue("u_warpAmount", float(self._preset_params["warp"]))
        self._program.setUniformValue("u_baseDominance", float(self._preset_params["base_dom"]))
        self._program.setUniformValue("u_ambientMix", float(self._preset_params["ambient"]))
        self._program.setUniformValue("u_blobCoreMix", float(self._preset_params["core"]))
        self._program.setUniformValue("u_blobHaloMix", float(self._preset_params["halo"]))
        self._program.setUniformValue("u_blobSoftMix", float(self._preset_params["soft"]))
        self._program.setUniformValue("u_blobMistMix", float(self._preset_params["mist"]))
        self._program.setUniformValue("u_finalBasePull", float(self._preset_params["final_base"]))
        self._program.setUniformValue("u_globalOpacity", float(self._global_opacity))
        self._program.setUniformValue("u_paletteSize", int(min(8, len(active_palette))))
        self._program.setUniformValue("u_palette0", palette_vec[0])
        self._program.setUniformValue("u_palette1", palette_vec[1])
        self._program.setUniformValue("u_palette2", palette_vec[2])
        self._program.setUniformValue("u_palette3", palette_vec[3])
        self._program.setUniformValue("u_palette4", palette_vec[4])
        self._program.setUniformValue("u_palette5", palette_vec[5])
        self._program.setUniformValue("u_palette6", palette_vec[6])
        self._program.setUniformValue("u_palette7", palette_vec[7])

        self._vertex_buffer.bind()
        pos_loc = self._program.attributeLocation("a_pos")
        self._program.enableAttributeArray(pos_loc)
        self._program.setAttributeBuffer(pos_loc, GL_FLOAT, 0, 2, 0)
        funcs.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        self._program.disableAttributeArray(pos_loc)
        self._vertex_buffer.release()
        self._program.release()

    def cleanup(self):
        if self._vertex_buffer is not None:
            try:
                self._vertex_buffer.destroy()
            except Exception:
                pass
            self._vertex_buffer = None
        if self._program is not None:
            try:
                self._program.removeAllShaders()
            except Exception:
                pass
            self._program = None

    def closeEvent(self, event):
        self.makeCurrent()
        self.cleanup()
        self.doneCurrent()
        super().closeEvent(event)
