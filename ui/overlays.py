# ui/overlays.py
import io
from PyQt5.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QTimer, QPoint, QRectF
from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout, QGraphicsOpacityEffect, QSizePolicy
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QFontDatabase, QFontMetrics, QPixmap
from .widgets import CircularButton, ScrollingTextLabel

class OverlayWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.opacity_animation = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.opacity_animation.setDuration(250)
        self.opacity_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # Main vertical layout to stack playlist panel above buttons
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 60)
        self.main_layout.setSpacing(20)
        self.main_layout.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        
        # Placeholder for playlist panel (will be set from main.py)
        self.playlist_panel = None
        
        # Spacer to push everything to the bottom
        self.main_layout.addStretch(1)
        
        self.button_container = QWidget()
        self.button_container.setStyleSheet("background-color: rgba(0,0,0,0.3); border-radius: 35px;")
        self.button_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        container_layout = QHBoxLayout(self.button_container)
        container_layout.setContentsMargins(20, 10, 20, 10)
        container_layout.setSpacing(20)
        
        # Initialize buttons with NoFocus policy to prevent stealing keybinds from the main window
        self.settings_button = CircularButton(tooltip="Settings (C)", icon_char="⚙")
        self.settings_button.setFocusPolicy(Qt.NoFocus)
        
        self.lights_button = CircularButton(tooltip="Toggle Lights (L)", icon_char="💡")
        self.lights_button.setFocusPolicy(Qt.NoFocus)
        
        self.multi_monitor_button = CircularButton(tooltip="Toggle Multi-Monitor (F11)", icon_char="🖥")
        self.multi_monitor_button.setFocusPolicy(Qt.NoFocus)
        
        self.wallpaper_button = CircularButton(tooltip="Toggle Wallpaper Mode (F12)", icon_char="🎨")
        self.wallpaper_button.setFocusPolicy(Qt.NoFocus)

        self.background_only_button = CircularButton(tooltip="Toggle Background Only Mode", icon_char="🌌")
        self.background_only_button.setFocusPolicy(Qt.NoFocus)
        
        self.notif_mode_button = CircularButton(tooltip="Notification Only Mode", icon_char="📬")
        self.notif_mode_button.setFocusPolicy(Qt.NoFocus)
        
        self.fullscreen_button = CircularButton(tooltip="Toggle Fullscreen", icon_char="⛶")
        self.fullscreen_button.setFocusPolicy(Qt.NoFocus)
        
        self.switch_monitor_button = CircularButton(tooltip="Switch Monitor", icon_char="🔄")
        self.switch_monitor_button.setFocusPolicy(Qt.NoFocus)
        
        # FIX: Set FocusPolicy to NoFocus for all buttons.
        # This ensures clicking them doesn't steal focus from the main window,
        # allowing arrow keys and other binds to keep working.
        buttons = [self.settings_button, self.lights_button, self.multi_monitor_button, 
                   self.wallpaper_button, self.background_only_button, self.notif_mode_button, self.fullscreen_button,
                   self.switch_monitor_button]
        for btn in buttons: btn.setFocusPolicy(Qt.NoFocus)
        
        container_layout.addWidget(self.settings_button)
        container_layout.addWidget(self.lights_button)
        container_layout.addWidget(self.fullscreen_button)
        container_layout.addWidget(self.switch_monitor_button)
        container_layout.addWidget(self.multi_monitor_button)
        container_layout.addWidget(self.wallpaper_button)
        container_layout.addWidget(self.background_only_button)
        container_layout.addWidget(self.notif_mode_button)
        
        self.main_layout.addWidget(self.button_container, 0, Qt.AlignHCenter)
        self.setLayout(self.main_layout)
    
    def sizeHint(self):
        """Calculate proper size based on content."""
        # Get button container size
        button_hint = self.button_container.sizeHint()
        button_height = button_hint.height()
        button_width = button_hint.width()
        
        # Get playlist panel size
        playlist_width = self.playlist_panel.width() if self.playlist_panel else 400
        playlist_height = 0
        if self.playlist_panel and self.playlist_panel.isVisible():
            playlist_height = self.playlist_panel.height() + 20  # Add spacing
        else:
            playlist_height = 80  # Minimum when empty
        
        # Calculate total size
        total_height = playlist_height + button_height + 80  # 80 for margins and spacing
        total_width = max(button_width, playlist_width) + 40  # 40 for margins
        
        return self.size().__class__(total_width, total_height)
    
    def update_size(self):
        """Update overlay size when playlist panel changes."""
        # Calculate proper dimensions based on content
        button_height = self.button_container.sizeHint().height()
        playlist_height = 0
        if self.playlist_panel:
            playlist_height = self.playlist_panel.height() + 20
        else:
            playlist_height = 80
        
        button_width = self.button_container.sizeHint().width()
        playlist_width = self.playlist_panel.width() if self.playlist_panel else 400
        
        total_width = max(button_width, playlist_width) + 40
        total_height = playlist_height + button_height + 80
        
        self.resize(total_width, total_height)
    
    def set_playlist_panel(self, panel):
        """Attach the playlist panel to the overlay."""
        if self.playlist_panel:
            self.main_layout.removeWidget(self.playlist_panel)
        self.playlist_panel = panel
        if panel:
            # Insert playlist panel after the stretch (index 1), before the button container
            # Layout is: [0: stretch, 1: <insert here>, 2: button_container]
            self.main_layout.insertWidget(1, panel, alignment=Qt.AlignHCenter)
            # Update size when panel is set
            self.update_size()

    def fade_in(self):
        try: self.opacity_animation.finished.disconnect(self.hide)
        except TypeError: pass
        self.opacity_effect.setOpacity(0)
        self.show()
        self.raise_()
        # Show playlist panel if attached
        if self.playlist_panel:
            self.playlist_panel.show()
            self.playlist_panel.raise_()
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)
        self.opacity_animation.start()
        if self.parent():
            self.parent().activateWindow()
            self.parent().setFocus(Qt.ActiveWindowFocusReason)

    def fade_out(self):
        try: self.opacity_animation.finished.disconnect(self.hide)
        except TypeError: pass
        # Store current size to prevent layout from shrinking
        current_size = self.size()
        # Restore size after fading to prevent shrinking
        self.resize(current_size)
        # Disconnect any previous connections to avoid multiple hide calls
        try:
            self.opacity_animation.finished.disconnect()
        except TypeError:
            pass
        # Connect to hide the entire overlay (including playlist panel) after fade completes
        self.opacity_animation.finished.connect(self.hide)
        self.opacity_animation.setStartValue(1.0)
        self.opacity_animation.setEndValue(0.0)
        self.opacity_animation.start()
        if self.parent():
            self.parent().activateWindow()
            self.parent().setFocus(Qt.ActiveWindowFocusReason)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            if self.childAt(event.pos()) is None:
                self.fade_out()
                event.accept()
            else:
                if self.parent():
                    self.parent().activateWindow()
                    self.parent().setFocus(Qt.ActiveWindowFocusReason)
                super().mousePressEvent(event)
        else:
            if self.parent():
                self.parent().activateWindow()
                self.parent().setFocus(Qt.ActiveWindowFocusReason)
            super().mousePressEvent(event)

class NotificationContent(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bg_color = QColor(20, 20, 20)
        self.bg_opacity = 230
        self.border_enabled = False
        self.border_color = QColor(255, 255, 255)
        self.radius = 12
        
    def paintEvent(self, event):
        painter = QPainter()
        if not painter.begin(self):
            return
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            bg = QColor(self.bg_color)
            bg.setAlpha(self.bg_opacity)
            path = QPainterPath()
            rect = QRectF(self.rect())
            if self.border_enabled:
                rect = rect.adjusted(1, 1, -1, -1)
            path.addRoundedRect(rect, self.radius, self.radius)
            painter.fillPath(path, bg)
            if self.border_enabled:
                pen = QPen(self.border_color)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawPath(path)
        finally:
            painter.end()

class NotificationWidget(QWidget):
    clicked = pyqtSignal()
    
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        
        self._scale = 1.0
        self.setFixedSize(350, 90)
        self._text_color = QColor(255, 255, 255)
        
        self.content_widget = NotificationContent(self)
        self.content_widget.setFixedSize(350, 90)
        
        layout = QHBoxLayout(self.content_widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        
        self.art_label = QLabel()
        self.art_label.setFixedSize(66, 66)
        self.art_label.setStyleSheet("background-color: transparent;")
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)
        text_layout.setAlignment(Qt.AlignVCenter)
        
        self.title_label = ScrollingTextLabel()
        self.artist_label = ScrollingTextLabel()
        
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.artist_label)
        
        layout.addWidget(self.art_label)
        layout.addLayout(text_layout)
        
        self.opacity_anim = QPropertyAnimation(self, b"windowOpacity")
        self.opacity_anim.setDuration(400)
        self.opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        self.pos_anim = QPropertyAnimation(self.content_widget, b"pos")
        
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fade_out)
        
        self._is_fading_out = False
        self._anim_duration = 500
        self._anim_type = "Fade"
        self._direction = "From Top"
        
        # State for transitioning between songs
        self._pending_transition = False
        self._pending_style = None
        self._pending_content = None
        self._pending_anim = None
        self._stay_duration = 4000
        self._permanent = False

    def set_zoom(self, scale):
        self._scale = scale
        w = int(350 * scale)
        h = int(90 * scale)
        self.setFixedSize(w, h)
        self.content_widget.setFixedSize(w, h)
        self.content_widget.radius = int(12 * scale)
        art_size = int(66 * scale)
        self.art_label.setFixedSize(art_size, art_size)
        m = int(12 * scale)
        self.content_widget.layout().setContentsMargins(m, m, m, m)
        self.content_widget.layout().setSpacing(m)

    def update_style(self, bg_color, text_color, font_family, font_style, border_enabled=False, border_color=None, notif_opacity=230, notif_border_enabled=False, notif_border_color=None, border_size=3):
        self.content_widget.bg_color = bg_color
        self.content_widget.bg_opacity = notif_opacity
        self.content_widget.border_enabled = notif_border_enabled
        if notif_border_color:
            self.content_widget.border_color = QColor(notif_border_color)
            
        self._text_color = text_color
        db = QFontDatabase()
        title_font = db.font(font_family, font_style, -1)
        title_font.setPointSizeF(11 * self._scale)
        artist_font = db.font(font_family, font_style, -1)
        artist_font.setPointSizeF(10 * self._scale)
        
        self.title_label.setFont(title_font)
        self.artist_label.setFont(artist_font)
        self.title_label.setTextColor(text_color)
        self.artist_label.setTextColor(text_color)
        self.title_label.setBorder(border_enabled, border_color, border_size)
        self.artist_label.setBorder(border_enabled, border_color, border_size)
        
        self.content_widget.update()

    def set_content(self, title, artist, pixmap):
        has_art = pixmap is not None and not pixmap.isNull()
        self.art_label.setVisible(has_art)
        
        if not has_art:
            self.title_label.setStandardPainting(True)
            self.artist_label.setStandardPainting(True)
            self.artist_label.setWordWrap(True)
            
            fm_title = QFontMetrics(self.title_label.font())
            fm_artist = QFontMetrics(self.artist_label.font())
            
            w_title = fm_title.width(title)
            rect_artist = fm_artist.boundingRect(0, 0, 500, 1000, Qt.TextWordWrap | Qt.AlignLeft, artist)
            
            req_width = max(350, min(max(w_title, rect_artist.width()) + 36, 600))
            req_height = max(90, fm_title.height() + rect_artist.height() + 36)
            
            self.setFixedSize(req_width, req_height)
            self.content_widget.setFixedSize(req_width, req_height)
            self.title_label.setText(title)
            self.artist_label.setText(artist)
        else:
            self.title_label.setStandardPainting(False)
            self.artist_label.setStandardPainting(False)
            self.artist_label.setWordWrap(False)
            
            w = int(350 * self._scale)
            h = int(90 * self._scale)
            self.setFixedSize(w, h)
            self.content_widget.setFixedSize(w, h)
            
            m = int(12 * self._scale)
            art_w = int(66 * self._scale)
            avail_w = w - m - art_w - m - m
            
            metrics = QFontMetrics(self.title_label.font())
            self.title_label.setText(metrics.elidedText(title, Qt.ElideRight, avail_w))
            
            metrics = QFontMetrics(self.artist_label.font())
            self.artist_label.setText(metrics.elidedText(artist, Qt.ElideRight, avail_w))
            
            size = self.art_label.size()
            rounded = QPixmap(size)
            rounded.fill(Qt.transparent)
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(0, 0, size.width(), size.height(), 6, 6)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, size.width(), size.height(), pixmap.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            painter.end()
            self.art_label.setPixmap(rounded)

    def transition_to_notification(self, style_args, content_args, anim_args):
        """
        Orchestrates the transition. 
        If visible: Animate Out (Old Data) -> Wait -> Apply New Data -> Animate In.
        If hidden: Apply New Data -> Animate In.
        """
        self._pending_style = style_args
        self._pending_content = content_args
        self._pending_anim = anim_args

        if self.isVisible() and self.windowOpacity() > 0.01:
            self._pending_transition = True
            # Ensure we use the animation duration specified in the new args for consistency
            self._anim_duration = anim_args.get('anim_duration', 500)
            self.fade_out()
        else:
            self._apply_pending_and_show()

    def _apply_pending_and_show(self):
        if self._pending_style:
            self.update_style(**self._pending_style)
        if self._pending_content:
            self.set_content(**self._pending_content)
        if self._pending_anim:
            self.show_notification(**self._pending_anim)
        
        self._pending_transition = False
        self._pending_style = None
        self._pending_content = None
        self._pending_anim = None

    def show_notification(self, anim_type, direction, screen_pos, duration=4000, anim_duration=500, permanent=False):
        self._anim_duration = anim_duration
        self._anim_type = anim_type
        self._direction = direction
        self._is_fading_out = False
        self._stay_duration = duration
        self._permanent = permanent
        
        self.move(screen_pos)
        self.raise_()
        self.pos_anim.stop()
        self.opacity_anim.stop()
        
        try: self.pos_anim.finished.disconnect(self._on_anim_finished)
        except TypeError: pass
        try: self.opacity_anim.finished.disconnect(self._on_anim_finished)
        except TypeError: pass
        
        w, h = self.width(), self.height()
        start_pos = QPoint(0, 0)
        end_pos = QPoint(0, 0)
        
        if direction == "From Top": start_pos = QPoint(0, -h)
        elif direction == "From Bottom": start_pos = QPoint(0, h)
        elif direction == "From Left": start_pos = QPoint(-w, 0)
        elif direction == "From Right": start_pos = QPoint(w, 0)
        
        main_anim = None
        
        if anim_type == "Fade":
            self.content_widget.move(0, 0)
            self.setWindowOpacity(0.0)
            self.opacity_anim.setStartValue(0.0)
            self.opacity_anim.setEndValue(1.0)
            self.opacity_anim.setDuration(anim_duration)
            self.opacity_anim.setEasingCurve(QEasingCurve.OutQuad)
            self.opacity_anim.start()
            main_anim = self.opacity_anim
        elif anim_type == "Slide" or anim_type == "Bounce":
            self.setWindowOpacity(1.0)
            self.pos_anim.setStartValue(start_pos)
            self.pos_anim.setEndValue(QPoint(0,0))
            self.pos_anim.setDuration(anim_duration)
            self.pos_anim.setEasingCurve(QEasingCurve.OutBounce if anim_type == "Bounce" else QEasingCurve.OutExpo)
            self.pos_anim.start()
            main_anim = self.pos_anim
        elif anim_type == "Fade Slide":
            self.setWindowOpacity(0.0)
            self.opacity_anim.setStartValue(0.0)
            self.opacity_anim.setEndValue(1.0)
            self.opacity_anim.setDuration(anim_duration)
            self.opacity_anim.setEasingCurve(QEasingCurve.OutQuad)
            self.opacity_anim.start()
            
            self.pos_anim.setStartValue(start_pos)
            self.pos_anim.setEndValue(QPoint(0, 0))
            self.pos_anim.setDuration(anim_duration)
            self.pos_anim.setEasingCurve(QEasingCurve.OutExpo)
            self.pos_anim.start()
            main_anim = self.pos_anim

        if main_anim:
            main_anim.finished.connect(self._on_anim_finished)

        self.show()

    def fade_out(self):
        self._is_fading_out = True
        self.opacity_anim.stop()
        self.pos_anim.stop()
        self.timer.stop()
        
        try: self.pos_anim.finished.disconnect(self._on_anim_finished)
        except TypeError: pass
        try: self.opacity_anim.finished.disconnect(self._on_anim_finished)
        except TypeError: pass
        
        w, h = self.width(), self.height()
        target_pos = QPoint(0, 0)
        if self._direction == "From Top": target_pos = QPoint(0, -h)
        elif self._direction == "From Bottom": target_pos = QPoint(0, h)
        elif self._direction == "From Left": target_pos = QPoint(-w, 0)
        elif self._direction == "From Right": target_pos = QPoint(w, 0)

        main_anim = None

        if self._anim_type == "Fade":
            self.opacity_anim.setStartValue(self.windowOpacity())
            self.opacity_anim.setEndValue(0.0)
            self.opacity_anim.setDuration(self._anim_duration)
            self.opacity_anim.setEasingCurve(QEasingCurve.OutQuad)
            self.opacity_anim.start()
            main_anim = self.opacity_anim
        elif self._anim_type == "Slide" or self._anim_type == "Bounce":
            self.pos_anim.setStartValue(self.content_widget.pos())
            self.pos_anim.setEndValue(target_pos)
            self.pos_anim.setDuration(self._anim_duration)
            self.pos_anim.setEasingCurve(QEasingCurve.InExpo)
            self.pos_anim.start()
            main_anim = self.pos_anim
        elif self._anim_type == "Fade Slide":
            self.opacity_anim.setStartValue(self.windowOpacity())
            self.opacity_anim.setEndValue(0.0)
            self.opacity_anim.setDuration(self._anim_duration)
            self.opacity_anim.setEasingCurve(QEasingCurve.OutQuad)
            
            self.pos_anim.setStartValue(self.content_widget.pos())
            self.pos_anim.setEndValue(target_pos)
            self.pos_anim.setDuration(self._anim_duration)
            self.pos_anim.setEasingCurve(QEasingCurve.InExpo)
            
            self.opacity_anim.start()
            self.pos_anim.start()
            main_anim = self.pos_anim
            
        if main_anim:
            main_anim.finished.connect(self._on_anim_finished)

    def _on_anim_finished(self):
        if self._is_fading_out:
             # Exit animation finished
             self.hide()
             if self._pending_transition:
                 self._apply_pending_and_show()
        else:
             # Entrance animation finished
             # Start the "stay" timer only if not permanent
             if not self._permanent:
                 self.timer.start(self._stay_duration)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            # FIX: Removed self.fade_out() so the notification stays visible
            # when clicked, while still bringing the main player forward.