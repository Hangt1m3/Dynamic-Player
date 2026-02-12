from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRect, pyqtSignal, QPoint, QSize, QEventLoop, QTimer, pyqtProperty, QRectF, QParallelAnimationGroup, QAbstractAnimation
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QHBoxLayout, QDialog, QLineEdit, QMessageBox, QFrame, QGridLayout, QListWidget, QListWidgetItem, QSizePolicy, QRadioButton, QButtonGroup, QApplication
from PyQt5.QtGui import QColor, QPixmap, QCursor, QPainter, QBrush, QPainterPath, QBitmap
import requests

def create_rounded_pixmap(pixmap, radius=12, target_size=None):
    """Create a pixmap with rounded corners. Scales to target_size first if provided."""
    if pixmap.isNull():
        return pixmap
    
    # Scale to target size first if provided
    if target_size:
        pixmap = pixmap.scaled(target_size, target_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        # Crop to square if needed
        if pixmap.width() != target_size or pixmap.height() != target_size:
            x = (pixmap.width() - target_size) // 2
            y = (pixmap.height() - target_size) // 2
            pixmap = pixmap.copy(x, y, target_size, target_size)
    
    size = pixmap.size()
    rounded = QPixmap(size)
    rounded.fill(Qt.transparent)
    
    painter = QPainter()
    if not painter.begin(rounded):
        print("Failed to begin painting on rounded pixmap")
        return pixmap
    
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        
        # Create a path with rounded corners
        from PyQt5.QtGui import QPainterPath
        path = QPainterPath()
        path.addRoundedRect(0, 0, size.width(), size.height(), radius, radius)
        
        # Clip to rounded path and draw pixmap
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pixmap)
    finally:
        painter.end()
    
    return rounded

class OverlayFrame(QFrame):
    """Custom overlay frame that paints with manual opacity to avoid QGraphicsOpacityEffect conflicts."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = 0.0
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")
    
    @pyqtProperty(float)
    def opacity(self):
        return self._opacity
    
    @opacity.setter
    def opacity(self, value):
        self._opacity = value
        self.update()
    
    def setOpacity(self, value):
        self._opacity = value
        self.update()
    
    def paintEvent(self, event):
        if self._opacity <= 0.0:
            return  # Don't paint if invisible
        
        painter = QPainter()
        if not painter.begin(self):
            return
        
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            # Draw rounded rectangle with current opacity - radius 20 to match cover art
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), 20, 20)
            color = QColor(0, 0, 0, int(220 * self._opacity))
            painter.fillPath(path, color)
        finally:
            painter.end()

class PlaylistItemWidget(QFrame):
    SQUARE_SIZE = 196  # Larger to fill the card
    def __init__(self, playlist, panel=None, parent=None):
        super().__init__(parent)
        self.playlist = playlist
        self.panel = panel  # Reference to PlaylistPanel for signal emission
        self.setFixedHeight(self.SQUARE_SIZE + 24)
        self.setFixedWidth(self.SQUARE_SIZE + 24)
        self.setStyleSheet("background: transparent; border: none;")
        self.setMouseTracking(True)
        self.hovered = False
        self._overlay_opacity = 0.0  # For fade animation
        self._play_scale = 1.0
        self._shuffle_scale = 1.0
        self.cover_label = QLabel(self)
        self.cover_label.setFixedSize(self.SQUARE_SIZE, self.SQUARE_SIZE)
        self.cover_label.move(12, 12)
        self.cover_label.setStyleSheet("background: transparent;")
        self.cover_label.setScaledContents(False)
        # Load cover art: prefer cached base64, then try Spotify images, then cover URL
        import base64
        cover_b64 = playlist.get('cover_art_b64')
        if cover_b64:
            try:
                pixmap = QPixmap()
                img_data = base64.b64decode(cover_b64)
                if pixmap.loadFromData(img_data):
                    rounded_pixmap = create_rounded_pixmap(pixmap, radius=20, target_size=self.SQUARE_SIZE)
                    self.cover_label.setPixmap(rounded_pixmap)
                else:
                    print(f"Failed to load pixmap for playlist: {playlist.get('name')}")
                    self.cover_label.setStyleSheet("background: #222;")
            except Exception as e:
                print(f"Error decoding cover art for {playlist.get('name')}: {e}")
                self.cover_label.setStyleSheet("background: #222; border-radius: 20px;")
        else:
            # Try Spotify images first (from user playlists)
            images = playlist.get('images', [])
            if images:
                try:
                    # Get the largest image
                    img_data = images[0].get('url')
                    if img_data:
                        resp = requests.get(img_data, timeout=2)
                        if resp.status_code == 200:
                            pixmap = QPixmap()
                            if pixmap.loadFromData(resp.content):
                                rounded_pixmap = create_rounded_pixmap(pixmap, radius=20, target_size=self.SQUARE_SIZE)
                                self.cover_label.setPixmap(rounded_pixmap)
                            else:
                                self.cover_label.setStyleSheet("background: #222;")
                except Exception as e:
                    print(f"Error fetching Spotify image for {playlist.get('name')}: {e}")
                    self.cover_label.setStyleSheet("background: #222;")
            else:
                # Try cover_url as fallback
                cover_url = playlist.get('cover_url')
                if cover_url:
                    try:
                        resp = requests.get(cover_url, timeout=2)
                        if resp.status_code == 200:
                            pixmap = QPixmap()
                            if pixmap.loadFromData(resp.content):
                                rounded_pixmap = create_rounded_pixmap(pixmap, radius=20, target_size=self.SQUARE_SIZE)
                                self.cover_label.setPixmap(rounded_pixmap)
                            else:
                                self.cover_label.setStyleSheet("background: #222;")
                    except Exception as e:
                        print(f"Error fetching cover art from URL for {playlist.get('name')}: {e}")
                        self.cover_label.setStyleSheet("background: #222;")
                else:
                    # fallback: blank
                    self.cover_label.setStyleSheet("background: #222;")
        # Overlay for details/buttons - custom widget with manual opacity
        self.overlay = OverlayFrame(self)
        self.overlay.setGeometry(12, 12, self.SQUARE_SIZE, self.SQUARE_SIZE)
        self.overlay.setOpacity(0.0)  # Start invisible
        self.overlay.show()  # Keep visible for event handling
        vbox = QVBoxLayout(self.overlay)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(6)
        
        # Top stretch for vertical centering
        vbox.addStretch(2)
        
        # Title vertically centered with more space
        self.name_label = QLabel(playlist['name'], self.overlay)
        # Dynamic font sizing based on text length
        font_size = self._calculate_font_size(playlist['name'])
        self.name_label.setStyleSheet(f"color: white; font-size: {font_size}px; font-weight: bold; background: transparent; padding: 8px;")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(120)  # Even more vertical space for title
        # Start hidden
        self.name_label.setVisible(False)
        vbox.addWidget(self.name_label, 0, Qt.AlignCenter)
        
        # Middle stretch
        vbox.addStretch(2)
        
        vbox.addSpacing(8)
        
        # Button row near bottom
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.play_btn = QPushButton("▶", self.overlay)
        self.play_btn.setFixedSize(32, 32)
        self.play_btn.setStyleSheet("background: #1db954; color: white; border-radius: 16px; font-weight: bold; font-size: 16px;")
        self.play_btn.setVisible(False)  # Start hidden
        self.shuffle_btn = QPushButton("🔀", self.overlay)
        self.shuffle_btn.setFixedSize(32, 32)
        self.shuffle_btn.setStyleSheet("background: #333; color: #1db954; border-radius: 16px; font-weight: bold; font-size: 16px;")
        self.shuffle_btn.setVisible(False)  # Start hidden
        btn_row.addStretch(1)
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.shuffle_btn)
        btn_row.addStretch(1)
        vbox.addLayout(btn_row)
        
        vbox.addSpacing(6)
        
        # Delete button row at bottom
        delete_row = QHBoxLayout()
        self.delete_btn = QPushButton("🗑", self.overlay)
        self.delete_btn.setFixedSize(18, 18)
        self.delete_btn.setStyleSheet("background: #d32f2f; color: white; border-radius: 9px; font-weight: bold; font-size: 10px;")
        self.delete_btn.setVisible(False)  # Start hidden
        delete_row.addStretch(1)
        delete_row.addWidget(self.delete_btn)
        delete_row.addStretch(1)
        vbox.addLayout(delete_row)
        
        # Raise buttons above overlay to ensure visibility
        self.play_btn.raise_()
        self.shuffle_btn.raise_()
        self.delete_btn.raise_()
        self.name_label.raise_()
        
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.play_btn.setFocusPolicy(Qt.NoFocus)
        self.shuffle_btn.setFocusPolicy(Qt.NoFocus)
        self.delete_btn.setFocusPolicy(Qt.NoFocus)
        self.play_btn.clicked.connect(self._on_play)
        self.shuffle_btn.clicked.connect(self._on_shuffle)
        self.delete_btn.clicked.connect(self._on_delete)
        
        # Enable mouse tracking for buttons to handle hover effects
        self.play_btn.installEventFilter(self)
        self.shuffle_btn.installEventFilter(self)
        
        # Animation setup
        self.overlay_fade_anim = QPropertyAnimation(self.overlay, b"opacity")
        self.overlay_fade_anim.setDuration(200)
        self.overlay_fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
    
    def _calculate_font_size(self, text):
        """Calculate optimal font size based on text length to fit in square."""
        text_len = len(text)
        if text_len <= 12:
            return 18  # Short text - larger font
        elif text_len <= 20:
            return 16  # Medium text
        elif text_len <= 30:
            return 14  # Long text
        elif text_len <= 45:
            return 12  # Longer text
        else:
            return 10  # Very long text - smallest font

    def sizeHint(self):
        return QSize(self.SQUARE_SIZE + 24, self.SQUARE_SIZE + 24)
    
    @pyqtProperty(float)
    def playScale(self):
        return self._play_scale
    
    @playScale.setter
    def playScale(self, value):
        self._play_scale = value
        w = int(32 * value)
        h = int(32 * value)
        self.play_btn.setFixedSize(w, h)
        # Update font size proportionally
        font_size = int(16 * value)
        radius = w // 2
        self.play_btn.setStyleSheet(f"background: #1db954; color: white; border-radius: {radius}px; font-weight: bold; font-size: {font_size}px;")
    
    @pyqtProperty(float)
    def shuffleScale(self):
        return self._shuffle_scale
    
    @shuffleScale.setter
    def shuffleScale(self, value):
        self._shuffle_scale = value
        w = int(32 * value)
        h = int(32 * value)
        self.shuffle_btn.setFixedSize(w, h)
        # Update font size proportionally
        font_size = int(16 * value)
        radius = w // 2
        self.shuffle_btn.setStyleSheet(f"background: #333; color: #1db954; border-radius: {radius}px; font-weight: bold; font-size: {font_size}px;")
    
    def eventFilter(self, obj, event):
        if obj == self.play_btn:
            if event.type() == event.Enter:
                self._animate_button_scale(self.play_btn, 1.15, 'play')
            elif event.type() == event.Leave:
                self._animate_button_scale(self.play_btn, 1.0, 'play')
        elif obj == self.shuffle_btn:
            if event.type() == event.Enter:
                self._animate_button_scale(self.shuffle_btn, 1.15, 'shuffle')
            elif event.type() == event.Leave:
                self._animate_button_scale(self.shuffle_btn, 1.0, 'shuffle')
        return super().eventFilter(obj, event)
    
    def _animate_button_scale(self, button, target_scale, button_type):
        """Animate button scale with easing."""
        prop_name = b'playScale' if button_type == 'play' else b'shuffleScale'
        anim = QPropertyAnimation(self, prop_name)
        anim.setDuration(150)
        anim.setEndValue(target_scale)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        # Store animation to prevent garbage collection
        if button_type == 'play':
            self._play_anim = anim
        else:
            self._shuffle_anim = anim

    def enterEvent(self, event):
        self.overlay_fade_anim.stop()
        self.overlay_fade_anim.setStartValue(self.overlay._opacity)
        self.overlay_fade_anim.setEndValue(1.0)
        self.overlay_fade_anim.start()
        # Show buttons and text on hover
        self.name_label.setVisible(True)
        self.play_btn.setVisible(True)
        self.shuffle_btn.setVisible(True)
        self.delete_btn.setVisible(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.overlay_fade_anim.stop()
        self.overlay_fade_anim.setStartValue(self.overlay._opacity)
        self.overlay_fade_anim.setEndValue(0.0)
        self.overlay_fade_anim.start()
        # Hide buttons and text when not hovering
        self.name_label.setVisible(False)
        self.play_btn.setVisible(False)
        self.shuffle_btn.setVisible(False)
        self.delete_btn.setVisible(False)
        super().leaveEvent(event)

    def _on_play(self):
        if self.panel and hasattr(self.panel, 'playlist_selected'):
            playlist_ref = self.playlist.get('uri') or self.playlist.get('id')
            print(f"Play button clicked for playlist: {self.playlist.get('name')} (ID: {self.playlist.get('id')})")
            if playlist_ref:
                self.panel.playlist_selected.emit(playlist_ref)
            else:
                print("Error: Playlist is missing a URI/ID for playback")
        else:
            print("Error: Panel reference not set or missing playlist_selected signal")

    def _on_shuffle(self):
        if self.panel and hasattr(self.panel, 'shuffle_requested'):
            playlist_ref = self.playlist.get('uri') or self.playlist.get('id')
            print(f"Shuffle button clicked for playlist: {self.playlist.get('name')} (ID: {self.playlist.get('id')})")
            if playlist_ref:
                self.panel.shuffle_requested.emit(playlist_ref)
            else:
                print("Error: Playlist is missing a URI/ID for shuffle playback")
        else:
            print("Error: Panel reference not set or missing shuffle_requested signal")
    
    def _on_delete(self):
        if self.panel:
            # Show confirmation dialog
            item_type = self.playlist.get('item_type', 'playlist').capitalize()
            dialog = ThemedConfirmDialog(
                title=f"Delete {item_type}",
                message=f"Are you sure you want to remove '{self.playlist.get('name')}' from your saved items?",
                parent=self.panel
            )
            if dialog.exec_() == QDialog.Accepted:
                # Emit signal to remove from panel
                if hasattr(self.panel, 'remove_playlist'):
                    self.panel.remove_playlist(self.playlist['id'])
                    print(f"Deleted {item_type}: {self.playlist.get('name')}")


class AddPlaylistSquareWidget(QFrame):
    """A clickable square widget for adding new playlists/albums. Appears in the grid like other playlist items."""
    SQUARE_SIZE = 196  # Match PlaylistItemWidget
    
    def __init__(self, panel=None, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.setFixedHeight(self.SQUARE_SIZE + 24)
        self.setFixedWidth(self.SQUARE_SIZE + 24)
        self.setStyleSheet("background: transparent; border: none;")
        self.setMouseTracking(True)
        self.hovered = False
        self._scale = 1.0
        
        # Main square background with "+" icon
        self.square = QFrame(self)
        self.square.setFixedSize(self.SQUARE_SIZE, self.SQUARE_SIZE)
        self.square.move(12, 12)
        self.square.setStyleSheet(
            "QFrame { background: rgba(60, 60, 60, 200); border-radius: 20px; border: 2px solid rgba(100, 100, 100, 150); }"
        )
        
        # Add "+" text in the center
        self.icon_label = QLabel("+", self.square)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setGeometry(0, 0, self.SQUARE_SIZE, self.SQUARE_SIZE)
        self.icon_label.setStyleSheet("QLabel { color: rgba(150, 150, 150, 200); font-size: 72px; font-weight: bold; }")
        
        # Add text below the square
        self.text_label = QLabel("Add Playlist\nor Album", self)
        self.text_label.setAlignment(Qt.AlignHCenter)
        self.text_label.setGeometry(0, self.SQUARE_SIZE + 30, self.SQUARE_SIZE + 24, 40)
        self.text_label.setStyleSheet("QLabel { color: rgba(150, 150, 150, 150); font-size: 11px; }")
        self.text_label.setWordWrap(True)
        
        self.setCursor(Qt.PointingHandCursor)
    
    def enterEvent(self, event):
        """Highlight on hover."""
        self.hovered = True
        self.square.setStyleSheet(
            "QFrame { background: rgba(80, 80, 80, 220); border-radius: 20px; border: 2px solid rgba(150, 150, 150, 200); }"
        )
        self.icon_label.setStyleSheet("QLabel { color: rgba(200, 200, 200, 255); font-size: 72px; font-weight: bold; }")
        self.text_label.setStyleSheet("QLabel { color: rgba(200, 200, 200, 200); font-size: 11px; }")
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """Remove highlight when not hovering."""
        self.hovered = False
        self.square.setStyleSheet(
            "QFrame { background: rgba(60, 60, 60, 200); border-radius: 20px; border: 2px solid rgba(100, 100, 100, 150); }"
        )
        self.icon_label.setStyleSheet("QLabel { color: rgba(150, 150, 150, 200); font-size: 72px; font-weight: bold; }")
        self.text_label.setStyleSheet("QLabel { color: rgba(150, 150, 150, 150); font-size: 11px; }")
        super().leaveEvent(event)
    
    def mousePressEvent(self, event):
        """Open the add playlist dialog when clicked."""
        if self.panel and hasattr(self.panel, '_on_add_clicked'):
            self.panel._on_add_clicked()
        super().mousePressEvent(event)
    
    def sizeHint(self):
        return QSize(self.SQUARE_SIZE + 24, self.SQUARE_SIZE + 24 + 50)  # Extra space for text


class PlaylistPanel(QWidget):

    PANEL_WIDTH = 400  # Base width; expands dynamically with playlist count
    MIN_HEIGHT = 80  # Minimum height (just add button)
    ITEM_HEIGHT = 240  # Height per playlist item (includes square + margins)
    ITEM_WIDTH = 220  # Width per playlist item (includes square + margins)
    GRID_SPACING = 12
    playlist_selected = pyqtSignal(str)
    shuffle_requested = pyqtSignal(str)
    add_from_user_playlists_requested = pyqtSignal()
    


    def _on_context_menu(self, pos):
        # Placeholder for right-click context menu on playlist items
        pass

    def _on_playlist_clicked(self, item):
        # Handle playlist item click event
        widget = self.playlist_list.itemWidget(item)
        if widget and hasattr(widget, 'playlist'):
            playlist_id = widget.playlist.get('id')
            if playlist_id:
                self.playlist_selected.emit(playlist_id)

    def _on_add_clicked(self):
        # Show a brief loading popup before fetching user items
        bg_color = QColor(30, 30, 30)
        text_color = QColor(255, 255, 255)
        accent_color = QColor(100, 100, 100)
        if self.main_window:
            bg_color = getattr(self.main_window, "_current_bg_color", bg_color)
            text_color = getattr(self.main_window, "_current_text_color", text_color)
            accent_color = getattr(self.main_window, "_current_accent_color", accent_color)

        popup = LoadingPopup(
            parent=self,
            message="Loading your playlists and albums. This may take a second...",
            bg_color=bg_color,
            text_color=text_color,
            accent_color=accent_color,
        )
        popup.show()
        QApplication.processEvents()

        wait_loop = QEventLoop()
        QTimer.singleShot(1000, wait_loop.quit)
        wait_loop.exec_()

        user_items = []
        if self.main_window and getattr(self.main_window, "sp", None):
            playlists = self.main_window._get_user_playlists()
            albums = self.main_window._get_user_albums()
            user_items = playlists + albums

        popup.close()

        dialog = AddPlaylistOrAlbumDialog(user_items, parent=self, main_window=self.main_window)
        if dialog.exec_() == QDialog.Accepted:
            selected = dialog.get_selected_item()
            if selected:
                # Encode cover art for the selected item before adding
                if self.main_window and not selected.get('cover_art_b64'):
                    selected['cover_art_b64'] = self.main_window._fetch_and_encode_cover_art(selected)
                # Add the selected item to the panel
                self._playlists.append(selected)
                self.set_playlists(self._playlists)
            else:
                # Check for manual URI/link input
                name, uri = dialog.get_manual_data()
                if name and uri:
                    # Determine if it's a playlist or album
                    item_type = 'album' if 'album' in uri else 'playlist'
                    if item_type == 'album':
                        item_id = self._extract_album_id(uri)
                    else:
                        item_id = self._extract_playlist_id(uri)
                    
                    if item_id:
                        item_data = {
                            'name': name,
                            'id': item_id,
                            'item_type': item_type,
                            'uri': self._normalize_uri(uri, item_id, item_type)
                        }
                        # Fetch cover art if possible
                        if self.main_window:
                            item_data['cover_art_b64'] = self.main_window._fetch_and_encode_cover_art(item_data)
                        self._playlists.append(item_data)
                        self.set_playlists(self._playlists)
                        print(f"Added {item_type} via URI: {name} ({item_id})")
                    else:
                        print(f"Failed to extract {item_type} ID from: {uri}")

    def __init__(self, parent=None, main_window=None):
        super().__init__(parent)
        self.main_window = main_window  # Reference to SpotifyPlayer for saving
        self.setFixedWidth(self.PANEL_WIDTH)
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        
        self.setStyleSheet("background: rgba(30, 30, 30, 220); border-radius: 16px;")
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 8, 12, 12)
        self.layout.setSpacing(0)
        
        # Playlist grid (no scrolling - expands upward)
        self.playlist_container = QWidget(self)
        self.playlist_container.setStyleSheet("background: transparent;")
        self.playlist_grid = QGridLayout(self.playlist_container)
        self.playlist_grid.setContentsMargins(0, 0, 0, 0)
        self.playlist_grid.setSpacing(self.GRID_SPACING)
        self.playlist_grid.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        # Add to main layout with stretch to allow upward expansion
        self.layout.addWidget(self.playlist_container, 1, Qt.AlignHCenter | Qt.AlignTop)
        
        self._playlists = []
        self._user_playlists = []  # Preloaded user playlists
        self._show_add_square = True  # Track if add square should be visible
        
        # Update size based on content
        self._update_size()
        # Start hidden
        self.hide()

    def set_user_playlists(self, playlists, albums=None):
        """Set the preloaded user playlists and albums (public/private from Spotify)."""
        self._user_playlists = (playlists or []) + (albums or [])
    
    def _extract_playlist_id(self, uri_or_link):
        """Extract Spotify playlist ID from URI or web link."""
        import re
        # Handle spotify:playlist:ID format
        if uri_or_link.startswith('spotify:playlist:'):
            return uri_or_link.replace('spotify:playlist:', '')
        # Handle open.spotify.com/playlist/ID or open.spotify.com/playlist/ID?si=...
        match = re.search(r'playlist[/:]([a-zA-Z0-9]+)', uri_or_link)
        if match:
            return match.group(1)
        return None

    def _extract_album_id(self, uri_or_link):
        """Extract Spotify album ID from URI or web link."""
        import re
        # Handle spotify:album:ID format
        if uri_or_link.startswith('spotify:album:'):
            return uri_or_link.replace('spotify:album:', '')
        # Handle open.spotify.com/album/ID or open.spotify.com/album/ID?si=...
        match = re.search(r'album[/:]([a-zA-Z0-9]+)', uri_or_link)
        if match:
            return match.group(1)
        return None

    def _normalize_uri(self, uri_or_link, item_id, item_type='playlist'):
        """Normalize reference to a spotify URI."""
        if not uri_or_link:
            return f"spotify:{item_type}:{item_id}"
        if uri_or_link.startswith(f'spotify:{item_type}:'):
            return uri_or_link
        return f"spotify:{item_type}:{item_id}"
    
    def remove_playlist(self, playlist_id):
        """Remove a playlist from the panel and save."""
        self._playlists = [pl for pl in self._playlists if pl.get('id') != playlist_id]
        self.set_playlists(self._playlists)

    def _update_size(self):
        """Update panel size based on number of playlists.
        
        Hides the add square when total height would exceed available space.
        """
        num_playlists = len(self._playlists)
        
        # Get screen geometry to determine available space
        from PyQt5.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            screen_height = screen.geometry().height()
            # Max height is 70% of screen for dynamic content
            max_height = int(screen_height * 0.7)
        else:
            max_height = 600  # Fallback
        
        # Calculate required height with add square
        total_items_with_add = num_playlists + 1
        columns = min(total_items_with_add, 4)
        rows_with_add = (total_items_with_add + 3) // 4
        height_with_add = (rows_with_add * self.ITEM_HEIGHT) + 40  # Add margins
        
        # Decide if we should show the add square
        self._show_add_square = height_with_add <= max_height
        
        # Calculate actual items and height to display
        if self._show_add_square:
            total_items = total_items_with_add
            target_height = height_with_add
        else:
            total_items = num_playlists
            columns = min(total_items, 4)
            rows = (total_items + 3) // 4 if total_items > 0 else 0
            target_height = (rows * self.ITEM_HEIGHT) + 40 if total_items > 0 else 40
        
        # Calculate width based on actual displayed items
        if total_items > 0:
            columns = min(total_items, 4)
            content_width = (columns * self.ITEM_WIDTH) + ((columns - 1) * self.GRID_SPACING)
            self.playlist_container.setFixedWidth(content_width)
            target_width = max(self.PANEL_WIDTH, content_width + 24)
        else:
            self.playlist_container.setFixedWidth(self.PANEL_WIDTH)
            target_width = self.PANEL_WIDTH

        self.setFixedWidth(target_width)
        self.setFixedHeight(target_height)
        
        # Trigger overlay size update if parent is overlay
        if hasattr(self.parent(), 'update_size'):
            self.parent().update_size()

    def set_playlists(self, playlists, skip_save=False):
        self._playlists = playlists
        
        # First, calculate if add square should be shown based on available space
        self._update_size()
        
        # Repopulate the playlist grid based on calculated _show_add_square
        while self.playlist_grid.count():
            item = self.playlist_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # Calculate total number of items to determine grid layout
        total_items = len(self._playlists) + (1 if self._show_add_square else 0)
        
        # Determine grid dimensions (4 columns)
        columns = 4
        total_rows = (total_items + columns - 1) // columns if total_items > 0 else 0
        
        # Add all playlists in order to the grid
        for idx, pl in enumerate(self._playlists):
            row = idx // columns
            col = idx % columns
            # Reverse row order so items grow upward (new rows appear at top)
            display_row = total_rows - row - 1
            widget = PlaylistItemWidget(pl, panel=self, parent=self.playlist_container)
            self.playlist_grid.addWidget(widget, display_row, col, alignment=Qt.AlignHCenter)
        
        # Add the "Add Playlist" square at the end if there's space
        if self._show_add_square:
            add_idx = len(self._playlists)
            row = add_idx // columns
            col = add_idx % columns
            # Reverse row order for add button too
            display_row = total_rows - row - 1
            add_widget = AddPlaylistSquareWidget(panel=self, parent=self.playlist_container)
            self.playlist_grid.addWidget(add_widget, display_row, col, alignment=Qt.AlignHCenter)
        
        # Recalculate size after all widgets are added
        self._update_size()
        
        # Trigger save unless explicitly skipped
        if not skip_save:
            self._emit_playlist_update()

    def _emit_playlist_update(self):
        # Emit signal to notify main window of playlist changes
        if self.main_window and hasattr(self.main_window, 'on_playlists_updated'):
            self.main_window.on_playlists_updated(self._playlists)
        elif hasattr(self.parent(), 'on_playlists_updated'):
            # Fallback for previous behavior
            self.parent().on_playlists_updated(self._playlists)





# Dialog for adding a playlist from user’s preloaded playlists or by manual URI


# Themed AddUserPlaylistDialog
from ui.styles import get_common_stylesheet
from PyQt5.QtGui import QColor

class LoadingPopup(QDialog):
    def __init__(self, parent=None, message="Loading...", bg_color=None, text_color=None, accent_color=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.bg_color = self._to_qcolor(bg_color, QColor(30, 30, 30))
        self.text_color = self._to_qcolor(text_color, QColor(255, 255, 255))

        container = QWidget(self)
        container.setStyleSheet(f"background: {self.bg_color.name()}; border-radius: 10px;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(18, 14, 18, 14)
        container_layout.setSpacing(8)

        msg_label = QLabel(message, container)
        msg_label.setStyleSheet(f"color: {self.text_color.name()}; font-size: 14px; background: transparent; border: none;")
        msg_label.setWordWrap(True)
        container_layout.addWidget(msg_label)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)
        self.setLayout(main_layout)
        self.adjustSize()

    def _to_qcolor(self, value, fallback):
        if isinstance(value, QColor):
            return value
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return QColor(*value[:3])
        return fallback

class AddPlaylistOrAlbumDialog(QDialog):
    def __init__(self, user_items, parent=None, bg_color=None, text_color=None, accent_color=None, main_window=None):
        super().__init__(parent)
        self.setWindowTitle("Add Playlist or Album")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.selected = None
        self.main_window = main_window
        # Theming
        self.bg_color = bg_color or QColor(30, 30, 30)
        self.text_color = text_color or QColor(255, 255, 255)
        self.accent_color = accent_color or QColor(100, 100, 100)
        
        # Container widget for rounded corners and background
        container = QWidget(self)
        container.setStyleSheet(f"background: {self.bg_color.name()}; border-radius: 12px; border: 2px solid {self.accent_color.name()};")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(12)
        
        # Title header
        title_label = QLabel("Add Playlist or Album", container)
        title_label.setStyleSheet(f"color: {self.text_color.name()}; font-size: 20px; font-weight: bold; background: transparent; border: none;")
        title_label.setAlignment(Qt.AlignCenter)
        container_layout.addWidget(title_label)
        
        label1 = QLabel("Select from your Spotify playlists and albums:", container)
        label1.setStyleSheet(f"color: {self.text_color.name()}; font-weight: bold; background: transparent; border: none;")
        container_layout.addWidget(label1)
        
        # Style scroll bars with rounded corners and accent color
        scrollbar_bg = self.bg_color.darker(120).name()
        scrollbar_handle = self.accent_color.lighter(140).name()
        scrollbar_style = f"""
            QScrollBar:vertical {{
                background: {scrollbar_bg};
                width: 12px;
                margin: 0px;
                border-radius: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {scrollbar_handle};
                min-height: 20px;
                border-radius: 6px;
                border: none;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {self.accent_color.lighter(150).name()};
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                border: none;
            }}
        """
        
        self.list_widget = QListWidget(container)
        self.list_widget.setStyleSheet(
            f"""
            QListWidget {{
                background: rgba(20,20,20,150);
                color: {self.text_color.name()};
                border: 1px solid {self.accent_color.name()};
                border-radius: 6px;
                padding: 4px;
            }}
            {scrollbar_style}
            """
        )
        self.list_widget.setMinimumHeight(400)
        self.list_widget.setMinimumWidth(500)
        
        # Use preloaded items, otherwise fetch lazily from main_window
        all_items = user_items or []
        if not all_items and self.main_window and getattr(self.main_window, "sp", None):
            playlists = self.main_window._get_user_playlists()
            albums = self.main_window._get_user_albums()
            all_items = playlists + albums
        
        # Populate list with items
        for item in all_items:
            item_type = item.get('item_type', 'playlist')
            item_name = item['name']
            display_text = f"[{item_type.upper()}] {item_name}"
            list_item = QListWidgetItem(display_text)
            list_item.setData(Qt.UserRole, item['id'])
            list_item.setData(Qt.UserRole + 1, item_type)
            self.list_widget.addItem(list_item)
        container_layout.addWidget(self.list_widget)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        label2 = QLabel("Or import by URI or link:", container)
        label2.setStyleSheet(f"color: {self.text_color.name()}; font-weight: bold; background: transparent; border: none;")
        container_layout.addWidget(label2)
        self.name_edit = QLineEdit(container)
        self.name_edit.setPlaceholderText("Playlist or Album Name")
        self.name_edit.setStyleSheet(f"color: {self.text_color.name()}; background: rgba(20,20,20,150); border: 1px solid {self.accent_color.name()}; border-radius: 4px; padding: 6px;")
        self.uri_edit = QLineEdit(container)
        self.uri_edit.setPlaceholderText("Spotify Playlist/Album URI or Link")
        self.uri_edit.setStyleSheet(f"color: {self.text_color.name()}; background: rgba(20,20,20,150); border: 1px solid {self.accent_color.name()}; border-radius: 4px; padding: 6px;")
        container_layout.addWidget(self.name_edit)
        container_layout.addWidget(self.uri_edit)
        btns = QHBoxLayout()
        ok_btn = QPushButton("Add", container)
        cancel_btn = QPushButton("Cancel", container)
        ok_btn.setStyleSheet(f"background: #1db954; color: white; border-radius: 6px; padding: 8px 20px; font-weight: bold; border: none;")
        cancel_btn.setStyleSheet(f"background: {self.bg_color.name()}; color: {self.text_color.name()}; border: 1px solid {self.accent_color.name()}; border-radius: 6px; padding: 8px 20px;")
        ok_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setFocusPolicy(Qt.StrongFocus)
        cancel_btn.setFocusPolicy(Qt.StrongFocus)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        container_layout.addLayout(btns)
        
        # Main dialog layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)
        self.setLayout(main_layout)
        
        # Set dialog minimum size for better list visibility
        self.setMinimumSize(600, 700)

    def _on_item_clicked(self, item):
        self.selected = {
            'name': item.text().split('] ', 1)[-1],  # Remove [TYPE] prefix
            'id': item.data(Qt.UserRole),
            'item_type': item.data(Qt.UserRole + 1)
        }
        self.name_edit.clear()
        self.uri_edit.clear()

    def get_selected_item(self):
        return self.selected

    def get_manual_data(self):
        return self.name_edit.text().strip(), self.uri_edit.text().strip()


# Keep old dialog name for backwards compatibility
AddUserPlaylistDialog = AddPlaylistOrAlbumDialog


class ThemedConfirmDialog(QDialog):
    """Themed confirmation dialog matching app style."""
    def __init__(self, title="Confirm", message="Are you sure?", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        
        # Theming
        bg_color = QColor(30, 30, 30)
        text_color = QColor(255, 255, 255)
        accent_color = QColor(100, 100, 100)
        
        # Container widget for rounded corners and background
        container = QWidget(self)
        container.setStyleSheet(f"background: {bg_color.name()}; border-radius: 12px; border: 2px solid {accent_color.name()};")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 20, 20, 20)
        container_layout.setSpacing(16)
        
        # Title header
        title_label = QLabel(title, container)
        title_label.setStyleSheet(f"color: {text_color.name()}; font-size: 20px; font-weight: bold; background: transparent; border: none;")
        title_label.setAlignment(Qt.AlignCenter)
        container_layout.addWidget(title_label)
        
        # Message
        message_label = QLabel(message, container)
        message_label.setStyleSheet(f"color: {text_color.name()}; font-size: 14px; background: transparent; border: none;")
        message_label.setAlignment(Qt.AlignCenter)
        message_label.setWordWrap(True)
        container_layout.addWidget(message_label)
        
        # Buttons
        btns = QHBoxLayout()
        ok_btn = QPushButton("Delete", container)
        cancel_btn = QPushButton("Cancel", container)
        ok_btn.setStyleSheet(f"background: #d32f2f; color: white; border-radius: 6px; padding: 8px 20px; font-weight: bold; border: none;")
        cancel_btn.setStyleSheet(f"background: {bg_color.name()}; color: {text_color.name()}; border: 1px solid {accent_color.name()}; border-radius: 6px; padding: 8px 20px;")
        ok_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.setFocusPolicy(Qt.StrongFocus)
        cancel_btn.setFocusPolicy(Qt.StrongFocus)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        container_layout.addLayout(btns)
        
        # Main dialog layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)
        self.setLayout(main_layout)
