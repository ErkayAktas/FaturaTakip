"""Modern ve Şık Koyu Tema (Dark Mode QSS) ve Renk Sabitleri."""

COLORS = {
    "bg_dark": "#0F172A",          # Çok koyu slate
    "bg_card": "#1E293B",          # Kart ve panel zemin
    "bg_card_hover": "#334155",    # Hover
    "border": "#334155",           # Kenarlıklar
    "border_light": "#475569",     # Açık kenarlık
    "text_primary": "#F8FAFC",     # Ana metin
    "text_secondary": "#94A3B8",   # İkincil metin
    "text_muted": "#64748B",       # Soluk metin
    "accent_blue": "#3B82F6",      # Birincil mavi buton
    "accent_blue_hover": "#2563EB",
    "accent_indigo": "#6366F1",    # İndigo
    "accent_emerald": "#10B981",   # Başarı / Ödendi (Yeşil)
    "accent_emerald_hover": "#059669",
    # Uyarı Renkleri (Gereksinim uyarınca)
    "warning_yellow": "#EAB308",   # 2 Gün Kalan (Sarı)
    "warning_yellow_bg": "#422006",
    "warning_orange": "#F97316",   # 1 Gün Kalan (Turuncu)
    "warning_orange_bg": "#431407",
    "warning_red": "#EF4444",      # Vadesi Gelmiş/Geçmiş (Kırmızı)
    "warning_red_bg": "#450A0A",
    "status_paid": "#10B981",
    "status_paid_bg": "#064E3B",
}

MAIN_STYLE_SHEET = f"""
QMainWindow {{
    background-color: {COLORS["bg_dark"]};
    color: {COLORS["text_primary"]};
}}

QWidget {{
    background-color: transparent;
    color: {COLORS["text_primary"]};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}}

/* Üst Başlık ve Kartlar */
QFrame#topBar {{
    background-color: {COLORS["bg_card"]};
    border-bottom: 1px solid {COLORS["border"]};
    padding: 10px;
}}

QFrame#statCard {{
    background-color: {COLORS["bg_card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 8px 10px;
}}

QFrame#statCard:hover {{
    border-color: {COLORS["border_light"]};
    background-color: #232F45;
}}

/* İki Ayrı Özet Bilgi Grubu / Çerçeveleri */
QFrame#summaryFrameGeneral {{
    background-color: #172033;
    border: 1px solid #2B3A55;
    border-radius: 8px;
}}

QFrame#summaryFrameFiltered {{
    background-color: #0E1A2E;
    border: 1px solid #1E3A5F;
    border-left: 4px solid #38BDF8;
    border-radius: 8px;
}}

/* Sekmeler (QTabWidget) */
QTabWidget::pane {{
    border: 1px solid {COLORS["border"]};
    background-color: {COLORS["bg_card"]};
    border-radius: 8px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: {COLORS["bg_dark"]};
    color: {COLORS["text_secondary"]};
    padding: 10px 20px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border: 1px solid {COLORS["border"]};
    border-bottom: none;
    font-weight: 600;
    font-size: 13px;
}}

QTabBar::tab:selected {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text_primary"]};
    border-bottom: 2px solid {COLORS["accent_blue"]};
}}

QTabBar::tab:hover:!selected {{
    background-color: #1A2438;
    color: {COLORS["text_primary"]};
}}

/* Tablo (QTableWidget) */
QTableWidget {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text_primary"]};
    gridline-color: {COLORS["border"]};
    border: none;
    border-radius: 6px;
    selection-background-color: #1D4ED8; /* Şık mavi seçim arka planı */
    font-size: 13px;
}}

QTableWidget::item {{
    padding: 8px 10px;
    border-bottom: 1px solid #E2E8F0;
}}

/* Satır seçili durumdayken arka plan mavi kalır, metin rengi dinamik uyarı rengine göre atanır */
QTableWidget::item:selected {{
    background-color: #1D4ED8;
    font-weight: 600;
}}

/* Sağ Tık Menüsü (QMenu) */
QMenu {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 6px 0px;
}}

QMenu::item {{
    padding: 8px 24px 8px 24px;
    font-size: 13px;
}}

QMenu::item:selected {{
    background-color: {COLORS["accent_blue"]};
    color: #FFFFFF;
}}

QMenu::separator {{
    height: 1px;
    background: {COLORS["border"]};
    margin: 4px 10px;
}}

QHeaderView::section {{
    background-color: #0F172A;
    color: {COLORS["text_secondary"]};
    padding: 10px;
    border: none;
    border-bottom: 2px solid {COLORS["border"]};
    border-right: 1px solid {COLORS["border"]};
    font-weight: bold;
    font-size: 12px;
    text-transform: uppercase;
}}

QHeaderView::section:hover {{
    background-color: #1E293B;
    color: {COLORS["text_primary"]};
}}

/* Butonlar */
QPushButton {{
    background-color: {COLORS["accent_blue"]};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
}}

QPushButton:hover {{
    background-color: {COLORS["accent_blue_hover"]};
}}

QPushButton:pressed {{
    background-color: #1D4ED8;
}}

QPushButton#secondaryBtn {{
    background-color: #334155;
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border_light"]};
}}

QPushButton#secondaryBtn:hover {{
    background-color: #475569;
}}

QPushButton#successBtn {{
    background-color: {COLORS["accent_emerald"]};
    color: white;
}}

QPushButton#successBtn:hover {{
    background-color: {COLORS["accent_emerald_hover"]};
}}

QPushButton#dangerBtn {{
    background-color: {COLORS["warning_red"]};
    color: white;
}}

QPushButton#dangerBtn:hover {{
    background-color: #DC2626;
}}

/* Metin Giriş Alanları (QLineEdit, QSpinBox, QDateEdit) */
QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit {{
    background-color: #0F172A;
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: {COLORS["accent_blue"]};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus {{
    border: 1px solid {COLORS["accent_blue"]};
    background-color: #131E35;
}}

/* Arama Çubuğu */
QLineEdit#searchBar {{
    background-color: #0F172A;
    border: 1px solid {COLORS["border"]};
    border-radius: 20px;
    padding: 8px 16px;
    font-size: 13px;
    min-width: 280px;
}}

QLineEdit#searchBar:focus {{
    border-color: {COLORS["accent_blue"]};
}}

/* QComboBox & Dropdown Görünürlüğü (Global Dark Theme Fix) */
QComboBox {{
    background-color: #2B2B2B;
    color: #FFFFFF;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
    font-weight: 500;
    min-height: 22px;
}}

QComboBox:hover {{
    border-color: {COLORS["accent_blue"]};
    background-color: #333333;
}}

QComboBox:focus {{
    border: 1px solid {COLORS["accent_blue"]};
}}

QComboBox:on {{
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #475569;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background-color: #2B2B2B;
}}

QComboBox::down-arrow {{
    width: 0px;
    height: 0px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #CBD5E1;
    margin-right: 2px;
}}

QComboBox::down-arrow:hover {{
    border-top: 5px solid #FFFFFF;
}}

/* QComboBox Açılır Menü Listesi (QAbstractItemView / QListView) */
QComboBox QAbstractItemView {{
    background-color: #2B2B2B;
    color: #FFFFFF;
    border: 1px solid #475569;
    border-radius: 6px;
    selection-background-color: #1D4ED8;
    selection-color: #FFFFFF;
    outline: 0px;
    padding: 4px;
}}

QComboBox QAbstractItemView::item {{
    min-height: 26px;
    padding: 4px 8px;
    background-color: #2B2B2B;
    color: #FFFFFF;
    border-radius: 4px;
}}

QComboBox QAbstractItemView::item:selected {{
    background-color: #1D4ED8;
    color: #FFFFFF;
    font-weight: 600;
}}

QComboBox QAbstractItemView::item:hover {{
    background-color: #3B82F6;
    color: #FFFFFF;
}}

/* QListView genel seçici (macOS ve Linux uyumluluğu için) */
QComboBox QListView {{
    background-color: #2B2B2B;
    color: #FFFFFF;
    selection-background-color: #1D4ED8;
    selection-color: #FFFFFF;
}}



/* Scroll Bar */
QScrollBar:vertical {{
    border: none;
    background: #0F172A;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: #475569;
    min-height: 20px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: #64748B;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    border: none;
    background: #0F172A;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background: #475569;
    min-width: 20px;
    border-radius: 4px;
}}

/* Durum Çubuğu */
QStatusBar {{
    background-color: {COLORS["bg_card"]};
    border-top: 1px solid {COLORS["border"]};
    color: {COLORS["text_secondary"]};
    font-size: 12px;
}}

/* Pop-up / Dialog */
QDialog {{
    background-color: {COLORS["bg_dark"]};
    color: {COLORS["text_primary"]};
}}

/* Scroll Area */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

/* Windows Uyumlu Takvim Açılır Menüsü (QCalendarWidget) Stilleri */
QCalendarWidget QWidget {{
    background-color: #1E293B;
    color: #F8FAFC;
}}
QCalendarWidget QToolButton {{
    background-color: #0F172A;
    color: #F8FAFC;
    border: 1px solid {COLORS["border"]};
    border-radius: 4px;
    padding: 4px 8px;
    margin: 2px;
}}
QCalendarWidget QToolButton:hover {{
    background-color: {COLORS["accent_blue"]};
}}
QCalendarWidget QMenu {{
    background-color: #1E293B;
    color: #F8FAFC;
    border: 1px solid {COLORS["border"]};
}}
QCalendarWidget QSpinBox {{
    background-color: #0F172A;
    color: #F8FAFC;
    border: 1px solid {COLORS["border"]};
    selection-background-color: {COLORS["accent_blue"]};
}}
QCalendarWidget QTableView {{
    background-color: #0F172A;
    selection-background-color: {COLORS["accent_blue"]};
    selection-color: #FFFFFF;
    gridline-color: #1E293B;
}}
QCalendarWidget QTableView:item:hover {{
    background-color: #334155;
}}
QCalendarWidget #qt_datetimedit_calendar {{
    background-color: #1E293B;
    border: 1px solid {COLORS["border"]};
}}
"""
