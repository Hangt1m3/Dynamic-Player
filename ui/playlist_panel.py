from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRect, pyqtSignal, QPoint, QSize, QEventLoop, QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QHBoxLayout, QDialog, QLineEdit, QMessageBox, QFrame, QScrollArea, QGridLayout, QListWidget, QListWidgetItem, QSizePolicy, QRadioButton, QButtonGroup, QApplication
from PyQt5.QtGui import QColor, QPixmap, QCursor, QPainter, QBrush, QPainterPath, QBitmap
import requests

def create_rounded_pixmap(pixmap, radius=12):
    """Create a pixmap with rounded corners."""
    if pixmap.isNull():
        return pixmap
    
    size = pixmap.size()
    rounded = QPixmap(size)
    rounded.fill(Qt.transparent)
    
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    
    # Create a path with rounded corners
    from PyQt5.QtGui import QPainterPath
    path = QPainterPath()
    path.addRoundedRect(0, 0, size.width(), size.height(), radius, radius)
    
    # Clip to rounded path and draw pixmap
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    
    return rounded

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
        self.cover_label = QLabel(self)
        self.cover_label.setFixedSize(self.SQUARE_SIZE, self.SQUARE_SIZE)
        self.cover_label.move(12, 12)
        self.cover_label.setStyleSheet("border-radius: 12px; background: #222;")
        self.cover_label.setScaledContents(True)
        # Load cover art: prefer cached base64, then try Spotify images, then cover URL
        import base64
        cover_b64 = playlist.get('cover_art_b64')
        if cover_b64:
            try:
                pixmap = QPixmap()
                img_data = base64.b64decode(cover_b64)
                if pixmap.loadFromData(img_data):
                    rounded_pixmap = create_rounded_pixmap(pixmap, radius=12)
                    self.cover_label.setPixmap(rounded_pixmap)
                else:
                    print(f"Failed to load pixmap for playlist: {playlist.get('name')}")
                    self.cover_label.setStyleSheet("background: #222; border-radius: 12px;")
            except Exception as e:
                print(f"Error decoding cover art for {playlist.get('name')}: {e}")
                self.cover_label.setStyleSheet("background: #222; border-radius: 12px;")
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
                                rounded_pixmap = create_rounded_pixmap(pixmap, radius=12)
                                self.cover_label.setPixmap(rounded_pixmap)
                            else:
                                self.cover_label.setStyleSheet("background: #222; border-radius: 12px;")
                except Exception as e:
                    print(f"Error fetching Spotify image for {playlist.get('name')}: {e}")
                    self.cover_label.setStyleSheet("background: #222; border-radius: 12px;")
            else:
                # Try cover_url as fallback
                cover_url = playlist.get('cover_url')
                if cover_url:
                    try:
                        resp = requests.get(cover_url, timeout=2)
                        if resp.status_code == 200:
                            pixmap = QPixmap()
                            if pixmap.loadFromData(resp.content):
                                rounded_pixmap = create_rounded_pixmap(pixmap, radius=12)
                                self.cover_label.setPixmap(rounded_pixmap)
                            else:
                                self.cover_label.setStyleSheet("background: #222; border-radius: 12px;")
                    except Exception as e:
                        print(f"Error fetching cover art from URL for {playlist.get('name')}: {e}")
                        self.cover_label.setStyleSheet("background: #222; border-radius: 12px;")
                else:
                    # fallback: blank
                    self.cover_label.setStyleSheet("background: #222; border-radius: 12px;")
        # Overlay for details/buttons - use QFrame for proper rounded corner clipping
        self.overlay = QFrame(self)
        self.overlay.setGeometry(12, 12, self.SQUARE_SIZE, self.SQUARE_SIZE)
        # Set rounded corners with QFrame styling - darker background for hover darkening effect
        self.overlay.setStyleSheet("""
            QFrame {
                background: rgba(0,0,0,220);
                border-radius: 12px;
            }
        """)
        self.overlay.setLineWidth(0)
        self.overlay.setFrameStyle(QFrame.StyledPanel)
        # Apply a rounded rectangle mask to ensure perfect clipping to the corners
        mask = QPixmap(self.SQUARE_SIZE, self.SQUARE_SIZE)
        mask.fill(Qt.transparent)
        mask_painter = QPainter(mask)
        mask_painter.setRenderHint(QPainter.Antialiasing, True)
        mask_painter.fillRect(mask.rect(), Qt.white)
        mask_path = QPainterPath()
        mask_path.addRoundedRect(0, 0, self.SQUARE_SIZE, self.SQUARE_SIZE, 12, 12)
        mask_painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mask_painter.fillPath(mask_path, Qt.white)
        mask_painter.end()
        # Convert pixmap to bitmap for setMask()
        mask_bitmap = QBitmap(mask)
        self.overlay.setMask(mask_bitmap)
        self.overlay.hide()
        vbox = QVBoxLayout(self.overlay)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(10)
        self.name_label = QLabel(playlist['name'], self.overlay)
        self.name_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")
        vbox.addWidget(self.name_label)
        btn_row = QHBoxLayout()
        self.play_btn = QPushButton("▶", self.overlay)
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.setStyleSheet("background: #1db954; color: white; border-radius: 20px; font-weight: bold; font-size: 22px;")
        self.shuffle_btn = QPushButton("🔀", self.overlay)
        self.shuffle_btn.setFixedSize(40, 40)
        self.shuffle_btn.setStyleSheet("background: #333; color: #1db954; border-radius: 20px; font-weight: bold; font-size: 22px;")
        btn_row.addWidget(self.play_btn)
        btn_row.addWidget(self.shuffle_btn)
        vbox.addLayout(btn_row)
        # Delete button row
        delete_row = QHBoxLayout()
        self.delete_btn = QPushButton("🗑", self.overlay)
        self.delete_btn.setFixedSize(28, 28)
        self.delete_btn.setStyleSheet("background: #d32f2f; color: white; border-radius: 14px; font-weight: bold; font-size: 14px;")
        delete_row.addWidget(self.delete_btn)
        vbox.addLayout(delete_row)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.play_btn.setFocusPolicy(Qt.NoFocus)
        self.shuffle_btn.setFocusPolicy(Qt.NoFocus)
        self.delete_btn.setFocusPolicy(Qt.NoFocus)
        self.play_btn.clicked.connect(self._on_play)
        self.shuffle_btn.clicked.connect(self._on_shuffle)
        self.delete_btn.clicked.connect(self._on_delete)

    def sizeHint(self):
        return QSize(self.SQUARE_SIZE + 24, self.SQUARE_SIZE + 24)

    def enterEvent(self, event):
        self.overlay.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.overlay.hide()
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
        
        # Playlist grid (scrollable)
        self.playlist_scroll = QScrollArea(self)
        self.playlist_scroll.setWidgetResizable(True)
        self.playlist_scroll.setFrameShape(QFrame.NoFrame)
        self.playlist_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.playlist_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.playlist_scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.playlist_scroll.setStyleSheet("background: transparent; border: none;")

        self.playlist_container = QWidget(self.playlist_scroll)
        self.playlist_container.setStyleSheet("background: transparent;")
        self.playlist_grid = QGridLayout(self.playlist_container)
        self.playlist_grid.setContentsMargins(0, 0, 0, 0)
        self.playlist_grid.setSpacing(self.GRID_SPACING)
        self.playlist_grid.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        self.playlist_scroll.setWidget(self.playlist_container)
        self.playlist_scroll.setVisible(False)
        
        # Playlist grid first
        self.layout.addWidget(self.playlist_scroll, 1)
        
        # Add button (always visible) - placed last so it's at the bottom
        self.add_btn = QPushButton("+ Add Playlist or Album", self)
        self.add_btn.setStyleSheet("background: #1db954; color: #fff; border-radius: 8px; padding: 10px 16px; font-weight: bold;")
        self.add_btn.clicked.connect(self._on_add_clicked)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setFocusPolicy(Qt.NoFocus)
        self.add_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.layout.addSpacing(4)
        self.layout.addWidget(self.add_btn, 0, Qt.AlignHCenter)
        
        self._playlists = []
        self._user_playlists = []  # Preloaded user playlists
        # No list widget signals needed; item widgets handle their own actions
        
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
        """Update panel size based on number of playlists, with responsive max height."""
        num_playlists = len(self._playlists)
        if num_playlists == 0:
            # Small panel with just the add button
            target_height = self.MIN_HEIGHT
            self.playlist_scroll.setVisible(False)
        else:
            # Expand to show playlists and add button
            self.playlist_scroll.setVisible(True)
            columns = min(num_playlists, 4)
            rows = (num_playlists + 3) // 4
            # Calculate height: items + add button + margins/spacing
            target_height = (rows * self.ITEM_HEIGHT) + 60
            
            # Get screen geometry to determine max height dynamically
            from PyQt5.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                screen_height = screen.geometry().height()
                # Max height is 60% of screen, but at least 400px and at most 800px
                max_height = min(800, max(400, int(screen_height * 0.6)))
            else:
                max_height = 600  # Fallback
            
            # Cap at calculated maximum
            target_height = min(target_height, max_height)
        
        if num_playlists > 0:
            columns = min(num_playlists, 4)
            content_width = (columns * self.ITEM_WIDTH) + ((columns - 1) * self.GRID_SPACING)
            self.playlist_container.setFixedWidth(content_width)
            target_width = max(self.PANEL_WIDTH, content_width + 24)
        else:
            self.playlist_container.setMinimumWidth(0)
            target_width = self.PANEL_WIDTH

        self.setFixedWidth(target_width)
        self.setFixedHeight(target_height)
        
        # Trigger overlay size update if parent is overlay
        if hasattr(self.parent(), 'update_size'):
            self.parent().update_size()

    def set_playlists(self, playlists, skip_save=False):
        self._playlists = playlists
        # Repopulate the playlist grid
        while self.playlist_grid.count():
            item = self.playlist_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for idx, pl in enumerate(self._playlists):
            row = idx // 4
            col = idx % 4
            widget = PlaylistItemWidget(pl, panel=self, parent=self.playlist_container)
            self.playlist_grid.addWidget(widget, row, col, alignment=Qt.AlignHCenter)
        # Update size to accommodate playlists
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
