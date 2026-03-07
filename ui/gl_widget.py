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
    return (q - 0.5) * (0.14 * u_warpAmount) + (r - 0.5) * (0.10 * u_warpAmount);
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
        for (int j = 0; j < 3; ++j) {
            float fj = float(j);
            float idx = fi * 3.0 + fj;

            vec3 blobColor = baseColorForIndex;
            // Include base background color into one instance to preserve overall dominance.
            if (j == 2) {
                blobColor = mix(baseColorForIndex, u_baseColor, 0.62);
            }

            float speed = 0.62 + 0.95 * hash1(fi * 9.17 + fj * 17.31 + 1.3);
            float phase = fi * 1.93 + fj * 2.71 + hash1(fi * 7.1 + fj * 3.8) * 6.2831;
            vec2 c = blob_center(fi + 1.0 + fj * 0.41 + phase, t * speed);

            // Wide offsets in normalized coordinates to keep edges alive on ultrawide/tall screens.
            vec2 spread = vec2((fj - 1.0) * 0.52, (mod(fi + fj, 3.0) - 1.0) * 0.30);
            spread += vec2(
                0.16 * sin(t * (0.21 + 0.05 * speed) + phase),
                0.14 * cos(t * (0.18 + 0.04 * speed) + phase * 0.7)
            );
            c += spread;
            c = clamp(c, vec2(0.02, 0.02), vec2(0.98, 0.98));

            float wobble = 0.05 * sin(t * (0.36 + 0.06 * speed) + idx * 2.3 + phase);
            // Noticeably larger ellipses for stronger full-window coverage.
            vec2 axis = vec2(0.30 - 0.03 * fj, 0.21 + wobble + 0.02 * fj);
            float angle = t * (0.06 + 0.022 * speed) + idx * 1.17 + phase * 0.35;

            float f = ellipse_field(uvw, c, axis, angle, aspect) * (0.90 + 0.18 * sin(t * (0.42 + 0.08 * speed) + idx));

            float body = smoothstep(0.08, 0.50, f * u_intensity);
            float halo = smoothstep(0.015, 0.20, f * u_intensity * 0.95);
            float soft = smoothstep(0.00, 0.10, f * u_intensity * 0.90);
            float mist = smoothstep(0.00, 0.07, f * u_intensity * 0.82);
            float glow = halo * 0.58 + soft * 0.30 + mist * 0.12;

            col = mix(col, blobColor, body * u_blobCoreMix);
            col += blobColor * halo * u_blobHaloMix;
            col += blobColor * soft * u_blobSoftMix;
            col += blobColor * mist * u_blobMistMix;
            totalGlow += glow;
            totalField += body;
        }
    }

    float layer_mix = smoothstep(0.08, 1.30, totalField / 2.8);
    col = mix(col, mix(u_baseColor, ambient, 0.24), layer_mix * 0.08);

    float vignette = smoothstep(1.20, 0.20, length(centered_vig));
    col = mix(col * 0.70, col, vignette);
    col += ambient * min(totalGlow * 0.035, 0.06);

    // Final pull toward base color so the background still reads as the dominant tone.
    col = mix(col, u_baseColor, u_finalBasePull);
    col = clamp(col, 0.0, 1.0);

    gl_FragColor = vec4(col, 1.0);
}
"""


PRESET_SETTINGS = {
    "ultra_soft": {
        "warp": 1.25,
        "base_dom": 0.66,
        "ambient": 0.10,
        "core": 0.20,
        "halo": 0.035,
        "soft": 0.018,
        "mist": 0.014,
        "final_base": 0.52,
    },
    "balanced": {
        "warp": 1.0,
        "base_dom": 0.58,
        "ambient": 0.16,
        "core": 0.30,
        "halo": 0.05,
        "soft": 0.025,
        "mist": 0.015,
        "final_base": 0.42,
    },
    "color_pop": {
        "warp": 0.92,
        "base_dom": 0.48,
        "ambient": 0.22,
        "core": 0.42,
        "halo": 0.075,
        "soft": 0.04,
        "mist": 0.025,
        "final_base": 0.32,
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
        fmt.setSwapInterval(1)
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
        self._palette = [QColor(29, 185, 84), QColor(15, 120, 50), QColor(60, 210, 130)]
        self._base_color = QColor(0, 0, 0)
        self._intensity = max(0.2, float(intensity))
        self._style_preset = "balanced"
        self._preset_params = dict(PRESET_SETTINGS["balanced"])

    def set_palette(self, colors):
        self._palette = [QColor(c) for c in (colors or []) if QColor(c).isValid()]
        if not self._palette:
            self._palette = [QColor(29, 185, 84)]
        self.update()

    def set_base_color(self, color):
        qcolor = QColor(color)
        if not qcolor.isValid():
            return
        self._base_color = qcolor

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

        palette_vec = []
        for color in self._palette[:8]:
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
        self._program.setUniformValue("u_paletteSize", int(min(8, len(self._palette))))
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
