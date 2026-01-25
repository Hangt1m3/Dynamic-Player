# ui/styles.py
def get_common_stylesheet(bg_color, text_color, accent_color):
    """Generates a consistent stylesheet for all dialogs based on theme colors."""
    is_bg_light = bg_color.lightnessF() > 0.5
    text_hex = text_color.name()
    accent_hex = accent_color.name()
    
    input_bg = bg_color.darker(110).name() if is_bg_light else bg_color.lighter(125).name()
    btn_bg = bg_color.darker(105).name() if is_bg_light else bg_color.lighter(115).name()
    btn_hover = bg_color.darker(115).name() if is_bg_light else bg_color.lighter(130).name()
    btn_pressed = bg_color.darker(125).name() if is_bg_light else bg_color.lighter(105).name()
    scrollbar_bg = bg_color.darker(120).name() if is_bg_light else bg_color.lighter(110).name()
    scrollbar_handle = accent_color.darker(110).name() if accent_color.lightnessF() > 0.5 else accent_color.lighter(130).name()
    popup_bg = bg_color.darker(105).name() if is_bg_light else bg_color.lighter(115).name()
    
    # Define disabled colors
    disabled_text = "#888888"
    disabled_border = "#555555"
    disabled_bg = "transparent"

    return f"""
        QWidget {{ color: {text_hex}; font-family: 'Segoe UI', sans-serif; font-size: 14px; selection-background-color: {accent_hex}; selection-color: {text_hex}; }}
        QWidget:disabled {{ color: {disabled_text}; }}
        
        QDialog#ThemedDialog {{ background: transparent; }}
        QDialog {{ background-color: {popup_bg}; }}
        QMainWindow {{ background: transparent; }}
        QScrollArea {{ border: none; background: transparent; }}
        QScrollArea > QWidget > QWidget {{ background: transparent; }}
        #scrollAreaContent {{ background: transparent; }}
        
        QGroupBox {{ border: 1px solid {accent_hex}; border-radius: 8px; margin-top: 12px; padding-top: 10px; font-weight: bold; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
        
        QLineEdit, QTextBrowser, QPlainTextEdit {{ background: {input_bg}; color: {text_hex}; border: 1px solid {accent_hex}; border-radius: 6px; padding: 6px; }}
        QLineEdit:disabled {{ border: 1px solid {disabled_border}; color: {disabled_text}; background: rgba(0,0,0,0.1); }}
        
        QPushButton {{ background-color: {btn_bg}; color: {text_hex}; border: 1px solid {accent_hex}; border-radius: 6px; padding: 6px 12px; }}
        QPushButton:hover {{ background-color: {btn_hover}; }}
        QPushButton:pressed {{ background-color: {btn_pressed}; }}
        QPushButton:disabled {{ border: 1px solid {disabled_border}; color: {disabled_text}; background-color: rgba(255,255,255,0.05); }}
        
        QScrollBar:vertical {{ background: {scrollbar_bg}; width: 10px; margin: 0; border-radius: 5px; }}
        QScrollBar::handle:vertical {{ background: {scrollbar_handle}; min-height: 20px; border-radius: 5px; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
        
        QScrollBar:horizontal {{ background: {scrollbar_bg}; height: 10px; margin: 0; border-radius: 5px; }}
        QScrollBar::handle:horizontal {{ background: {scrollbar_handle}; min-width: 20px; border-radius: 5px; }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
        
        QCheckBox {{ spacing: 8px; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {accent_hex}; background: {input_bg}; }}
        QCheckBox::indicator:checked {{ background-color: {accent_hex}; border: 1px solid {accent_hex}; }}
        QCheckBox::indicator:disabled {{ border: 1px solid {disabled_border}; background-color: transparent; }}
        
        QRadioButton {{ spacing: 8px; }}
        QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 8px; border: 1px solid {accent_hex}; background: {input_bg}; }}
        QRadioButton::indicator:checked {{ background-color: {accent_hex}; border: 3px solid {input_bg}; }}
        QRadioButton::indicator:disabled {{ border: 1px solid {disabled_border}; background-color: transparent; }}
        
        QComboBox {{ background: {input_bg}; border: 1px solid {accent_hex}; border-radius: 6px; padding: 5px; min-width: 6em; }}
        QComboBox::drop-down {{ border: none; width: 20px; }}
        QComboBox::down-arrow {{ image: none; border-left: 5px solid transparent; border-right: 5px solid transparent; border-top: 5px solid {text_hex}; margin-right: 5px; }}
        QComboBox:disabled {{ border: 1px solid {disabled_border}; color: {disabled_text}; }}
        QComboBox::down-arrow:disabled {{ border-top: 5px solid {disabled_border}; }}
        QComboBox QAbstractItemView {{ background-color: {input_bg}; color: {text_hex}; selection-background-color: {accent_hex}; selection-color: {text_hex}; border: 1px solid {accent_hex}; outline: none; }}
        
        QTabWidget::pane {{ border: none; }}
        QTabBar::tab {{ background: transparent; padding: 8px 16px; border-bottom: 2px solid transparent; color: {text_hex}; margin-right: 2px; }}
        QTabBar::tab:selected {{ border-bottom: 2px solid {accent_hex}; color: {accent_hex}; }}
        QTabBar::tab:hover {{ background: rgba(255, 255, 255, 0.05); }}
        
        QTableWidget {{ background-color: {input_bg}; gridline-color: {accent_hex}; border: 1px solid {accent_hex}; border-radius: 6px; }}
        QHeaderView::section {{ background-color: {btn_bg}; color: {text_hex}; border: none; padding: 4px; border-bottom: 1px solid {accent_hex}; }}
        QTableCornerButton::section {{ background-color: {btn_bg}; border: none; }}
        
        QSlider::groove:horizontal {{ border: 1px solid {accent_hex}; height: 6px; background: {input_bg}; margin: 2px 0; border-radius: 3px; }}
        QSlider::handle:horizontal {{ background: {accent_hex}; border: 1px solid {accent_hex}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
        QSlider::groove:horizontal:disabled {{ border: 1px solid {disabled_border}; background: rgba(255,255,255,0.05); }}
        QSlider::handle:horizontal:disabled {{ background: {disabled_border}; border: 1px solid {disabled_border}; }}

        QMenu {{ background-color: {popup_bg}; color: {text_hex}; border: 1px solid {accent_hex}; border-radius: 6px; padding: 5px; }}
        QMenu::item {{ padding: 5px 20px; border-radius: 4px; }}
        QMenu::item:selected {{ background-color: {accent_hex}; color: {text_hex}; }}
        
        QToolTip {{ background-color: {popup_bg}; color: {text_hex}; border: 1px solid {accent_hex}; border-radius: 4px; padding: 4px; }}
    """