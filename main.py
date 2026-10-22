# Sürüm Kontrol Sistemi (Version Checking)
APP_VERSION = "1.0.0"

import ctypes
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.components import DateTableWidgetItem, NumericTableWidgetItem, SortableTableWidget, StatCard
from src.database import InvoiceDatabase, get_app_base_dir, sanitize_date_str
from src.dialogs import NakitGirisDialog, OdemeGirisDialog, VadeGirisDialog
from src.dropbox_sync import DropboxSyncManager
from src.file_watcher import WatcherService
from src.holiday_service import holiday_service
from src.pdf_extractor import pdf_extractor
from src.styles import COLORS, MAIN_STYLE_SHEET
from src.updater import APP_VERSION, CURRENT_VERSION, AutoUpdater

# Windows Görev Çubuğu (Taskbar) Simgesi: AppUserModelID tanımlanmalıdır
if sys.platform.startswith("win"):
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("faturatakip.lojistik.app.v1.0")
    except Exception as e:
        print(f"[Taskbar Icon Hatası] {e}")


class FaturaTakipApp(QMainWindow):
    """Fatura Takip Masaüstü Uygulaması Ana Penceresi."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Fatura Takip Sistemi | Lojistik & Taşıma Faturaları (v{APP_VERSION})")
        self.resize(1260, 800)
        self.setMinimumSize(980, 600)

        # Proje / .exe çalışma dizini (PyInstaller sys._MEIPASS yerine sys.executable dizini)
        self.base_dir = get_app_base_dir()

        # Windows / macOS Görev Çubuğu ve Pencere Simgesi (Taskbar Icon)
        icon_path = os.path.join(self.base_dir, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Veritabanı ve Dizin İzleme Servisi
        self.db = InvoiceDatabase(base_dir=self.base_dir)
        self.watcher = WatcherService(db=self.db, extractor=pdf_extractor)

        # Dropbox Yedekleme ve Çift Yönlü Senkronizasyon (5ymg7fu8z3zha1n API anahtarı)
        self.dropbox_sync = DropboxSyncManager(local_json_path=self.db.json_path, parent=self)
        self.db.add_change_callback(self.dropbox_sync.trigger_instant_upload)
        self.dropbox_sync.sync_status_updated.connect(self._on_dropbox_status_updated)
        self.dropbox_sync.data_reloaded_from_cloud.connect(self._on_cloud_data_reloaded)
        self.dropbox_sync.sync_countdown_tick.connect(self._on_sync_countdown_tick)
        self.dropbox_sync.active_sessions_updated.connect(self._on_active_sessions_updated)
        self.dropbox_sync.start()

        # Güncelleme Servisi (Sipariş Takip / APK-STU mimarisi)
        self.updater = AutoUpdater(self)

        self._setup_ui()
        self._setup_watcher()
        self.refresh_all_tabs()

        # Uygulama açılışında arka planda sessiz güncelleme kontrolü
        QTimer.singleShot(2000, lambda: self.updater.check_for_updates(silent_if_latest=True))

    def _setup_ui(self):
        # Ana widget ve layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 14, 16, 12)
        main_layout.setSpacing(12)

        # 1. ÜST BAR: Başlık, Durum Rozeti, Butonlar ve Global Arama Çubuğu
        top_bar = self._create_top_bar()
        main_layout.addWidget(top_bar)

        # 2. KPI / İSTATİSTİK KARTLARI
        stats_bar = self._create_stats_bar()
        main_layout.addWidget(stats_bar)

        # 3. SEKMELER (QTabWidget)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Sekme 1: Düzenlenecek Faturalar
        self.tab_pending = QWidget()
        self._setup_tab_pending()
        self.tabs.addTab(self.tab_pending, "  Düzenlenecek Faturalar  ")

        # Sekme 2: Tüm Faturalar
        self.tab_all = QWidget()
        self._setup_tab_all()
        self.tabs.addTab(self.tab_all, "  Tüm Faturalar  ")

        # Sekme 3: Vadesi Gelmiş Faturalar
        self.tab_due = QWidget()
        self._setup_tab_due()
        self.tabs.addTab(self.tab_due, "  Vadesi Gelmiş Faturalar  ")

        # Sekme 4: Ödenmiş Faturalar
        self.tab_paid = QWidget()
        self._setup_tab_paid()
        self.tabs.addTab(self.tab_paid, "  Ödenmiş Faturalar  ")

        main_layout.addWidget(self.tabs)

        # 4. ALT DURUM ÇUBUĞU (Status Bar)
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Sistem hazır. TasımaFaturaları klasörü izleniyor.")

        # Canlı Durum ve Sayaç Rozetleri (Status Bar Sağ Köşe)
        self.sb_sessions_lbl = QLabel("👥 Aktif Oturum Sayısı: 1")
        self.sb_sessions_lbl.setStyleSheet(
            "color: #10B981; font-weight: bold; font-size: 11px; padding: 2px 8px; "
            "background-color: #064E3B; border-radius: 4px; border: 1px solid #059669;"
        )
        self.sb_sessions_lbl.setToolTip("Dropbox üzerinde tespit edilen eşzamanlı aktif cihaz/pencere oturumu sayısı")

        self.sb_countdown_lbl = QLabel("⏱️ Sonraki eşitlemeye: 30 saniye")
        self.sb_countdown_lbl.setStyleSheet(
            "color: #38BDF8; font-weight: bold; font-size: 11px; padding: 2px 8px; "
            "background-color: #0F172A; border-radius: 4px; border: 1px solid #0284C7;"
        )
        self.sb_countdown_lbl.setToolTip("Dropbox çift yönlü otomatik senkronizasyonuna (Auto-Sync) kalan süre")

        self.status_bar.addPermanentWidget(self.sb_sessions_lbl)
        self.status_bar.addPermanentWidget(self.sb_countdown_lbl)

    def _create_top_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("topBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(12)

        # Uygulama Başlığı ve İkon Metni
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        app_title = QLabel(f"📄 FATURA TAKİP SİSTEMİ <span style='font-size: 11px; font-weight: normal; color: #94A3B8;'>v{APP_VERSION}</span>")
        app_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.5px;")

        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        self.watch_status_lbl = QLabel("● Klasör İzleniyor (TasımaFaturaları)")
        self.watch_status_lbl.setStyleSheet("font-size: 11px; color: #10B981; font-weight: 600;")

        self.dropbox_status_lbl = QLabel("● Dropbox: Başlatılıyor...")
        self.dropbox_status_lbl.setStyleSheet("font-size: 11px; color: #F59E0B; font-weight: 600;")

        self.top_sync_countdown_lbl = QLabel("⏱️ Eşitleme: 30s")
        self.top_sync_countdown_lbl.setStyleSheet("font-size: 11px; color: #38BDF8; font-weight: 600;")

        self.top_active_sessions_lbl = QLabel("💻 Aktif Oturum: 1")
        self.top_active_sessions_lbl.setStyleSheet("font-size: 11px; color: #10B981; font-weight: 600;")

        status_row.addWidget(self.watch_status_lbl)
        status_row.addWidget(self.dropbox_status_lbl)
        status_row.addWidget(self.top_sync_countdown_lbl)
        status_row.addWidget(self.top_active_sessions_lbl)
        status_row.addStretch()

        title_box.addWidget(app_title)
        title_box.addLayout(status_row)
        layout.addLayout(title_box)

        layout.addStretch()

        # Manuel Nakit Girişi Butonu (PDF Zorunluluğu Olmayan Hızlı Nakit Girişi)
        self.btn_manual_cash = QPushButton("💵 Manuel Nakit Girişi")
        self.btn_manual_cash.setObjectName("successBtn")
        self.btn_manual_cash.setToolTip("PDF belgesi olmadan doğrudan sisteme nakit işlem kaydı ekle")
        self.btn_manual_cash.clicked.connect(self._open_manual_cash_dialog)
        layout.addWidget(self.btn_manual_cash)

        # Genel Arama Çubuğu (Search Bar) - Tüm sekmelerde geçerli
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("searchBar")
        self.search_bar.setPlaceholderText("🔍 Şirket İsmi veya Fatura No Ara...")
        self.search_bar.textChanged.connect(self._on_search_text_changed)
        layout.addWidget(self.search_bar)

        # Butonlar
        self.btn_open_folder = QPushButton("📁 Klasörü Aç")
        self.btn_open_folder.setObjectName("secondaryBtn")
        self.btn_open_folder.setToolTip("TasımaFaturaları klasörünü Finder'da / Dosya Yöneticisi'nde aç")
        self.btn_open_folder.clicked.connect(self._open_invoices_folder)
        layout.addWidget(self.btn_open_folder)

        self.btn_scan = QPushButton("🔄 Klasörü Tara")
        self.btn_scan.setObjectName("secondaryBtn")
        self.btn_scan.setToolTip("Klasördeki yeni veya taranmamış PDF'leri tara")
        self.btn_scan.clicked.connect(self._scan_folder_now)
        layout.addWidget(self.btn_scan)

        self.btn_check_update = QPushButton("🚀 Güncellemeleri Kontrol Et")
        self.btn_check_update.setObjectName("secondaryBtn")
        self.btn_check_update.setToolTip("GitHub üzerinden yeni sürüm kontrolü yap")
        self.btn_check_update.clicked.connect(lambda: self.updater.check_for_updates(silent_if_latest=False))
        layout.addWidget(self.btn_check_update)

        return frame

    def _create_stats_bar(self) -> QWidget:
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(6)

        # 1. SATIR: Durum Sayaçları (Operational Status Cards)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.card_pending = StatCard("DÜZENLENECEK (EKSİK VADE)", "0", "#F97316")
        self.card_all_active = StatCard("AKTİF / BEKLEYEN", "0", "#60A5FA")
        self.card_due_urgent = StatCard("VADESİ GELMİŞ / GEÇMİŞ", "0", "#EF4444")
        status_row.addWidget(self.card_pending)
        status_row.addWidget(self.card_all_active)
        status_row.addWidget(self.card_due_urgent)
        main_layout.addLayout(status_row)

        # 2. SATIR / GRUP: GENEL TOPLAM ALANI (En Üstte - Sabit)
        # Hiçbir tarih veya arama filtresinden etkilenmeyen sabit kümülatif toplamlar
        self.frame_general = QFrame()
        self.frame_general.setObjectName("summaryFrameGeneral")
        gen_vbox = QVBoxLayout(self.frame_general)
        gen_vbox.setContentsMargins(10, 6, 10, 6)
        gen_vbox.setSpacing(4)

        gen_header_layout = QHBoxLayout()
        self.lbl_gen_title = QLabel("📌 GENEL TOPLAM ALANI (SABİT — VERİTABANI KÜMÜLATİF)")
        self.lbl_gen_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #94A3B8; letter-spacing: 0.5px;")
        self.lbl_gen_count = QLabel("(Tüm Veritabanı)")
        self.lbl_gen_count.setStyleSheet("font-size: 11px; font-weight: 600; color: #64748B;")
        gen_header_layout.addWidget(self.lbl_gen_title)
        gen_header_layout.addWidget(self.lbl_gen_count)
        gen_header_layout.addStretch()
        gen_vbox.addLayout(gen_header_layout)

        gen_cards_layout = QHBoxLayout()
        gen_cards_layout.setSpacing(8)
        # Sıralama: 1. Genel Vergi Hariç, 2. Genel KDV, 3. Genel Toplam
        self.card_gen_tax_excluded = StatCard("GENEL VERGİ HARİÇ", "0.00 TL", "#38BDF8")
        self.card_gen_kdv = StatCard("GENEL KDV", "0.00 TL", "#F59E0B")
        self.card_gen_total = StatCard("GENEL TOPLAM", "0.00 TL", "#10B981")

        gen_cards_layout.addWidget(self.card_gen_tax_excluded)
        gen_cards_layout.addWidget(self.card_gen_kdv)
        gen_cards_layout.addWidget(self.card_gen_total)
        gen_vbox.addLayout(gen_cards_layout)
        main_layout.addWidget(self.frame_general)

        # 3. SATIR / GRUP: FİLTRELENEN TOPLAM ALANI (Hemen Altında - Dinamik)
        # Sadece tarih seçici veya arama kutusu ile filtrelenip ekrandaki tabloya yansıyan faturalar
        self.frame_filtered = QFrame()
        self.frame_filtered.setObjectName("summaryFrameFiltered")
        fil_vbox = QVBoxLayout(self.frame_filtered)
        fil_vbox.setContentsMargins(10, 6, 10, 6)
        fil_vbox.setSpacing(4)

        fil_header_layout = QHBoxLayout()
        self.lbl_fil_title = QLabel("🔍 FİLTRELENEN TOPLAM ALANI (DİNAMİK — TARİH / ARAMA)")
        self.lbl_fil_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #38BDF8; letter-spacing: 0.5px;")
        self.lbl_fil_count = QLabel("(Filtrelenen Faturalar)")
        self.lbl_fil_count.setStyleSheet("font-size: 11px; font-weight: 600; color: #94A3B8;")
        fil_header_layout.addWidget(self.lbl_fil_title)
        fil_header_layout.addWidget(self.lbl_fil_count)
        fil_header_layout.addStretch()
        fil_vbox.addLayout(fil_header_layout)

        fil_cards_layout = QHBoxLayout()
        fil_cards_layout.setSpacing(8)
        # Sıralama: 1. Filtrelenen Vergi Hariç, 2. Filtrelenen KDV, 3. Filtrelenen Toplam
        self.card_fil_tax_excluded = StatCard("FİLTRELENEN VERGİ HARİÇ", "0.00 TL", "#38BDF8")
        self.card_fil_kdv = StatCard("FİLTRELENEN KDV", "0.00 TL", "#F59E0B")
        self.card_fil_total = StatCard("FİLTRELENEN TOPLAM", "0.00 TL", "#10B981")

        fil_cards_layout.addWidget(self.card_fil_tax_excluded)
        fil_cards_layout.addWidget(self.card_fil_kdv)
        fil_cards_layout.addWidget(self.card_fil_total)
        fil_vbox.addLayout(fil_cards_layout)
        main_layout.addWidget(self.frame_filtered)

        # Geriye dönük uyumluluk takma adları (backward compatibility aliases)
        self.card_total_tax_excluded = self.card_gen_tax_excluded
        self.card_total_kdv = self.card_gen_kdv
        self.card_total_amount = self.card_gen_total

        return container

    # --- SEKME 1: DÜZENLENECEK FATURALAR ---
    def _setup_tab_pending(self):
        layout = QVBoxLayout(self.tab_pending)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        info_lbl = QLabel(
            "ℹ️ Son ödeme tarihi bulunmayan faturalar listelenir. Faturaya çift tıklayarak iş günü cinsinden vade belirleyebilirsiniz."
        )
        info_lbl.setStyleSheet("color: #94A3B8; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(info_lbl)

        # Sütunlar: Şirket İsmi, Fatura No, Tarih, Vergi Hariç Fiyat, Vergi (KDV Tutarı), Toplam Fiyat (Vergiler Dahil)
        headers = [
            "Şirket İsmi",
            "Fatura No",
            "Fatura Kesim Tarihi",
            "Vergi Hariç Fiyat",
            "Vergi (KDV Tutarı)",
            "Toplam Fiyat (Vergiler Dahil)",
        ]
        self.table_pending = SortableTableWidget(headers)
        self.table_pending.set_column_weights([0.30, 0.16, 0.14, 0.13, 0.13, 0.14])
        self.table_pending.cellDoubleClicked.connect(self._on_pending_cell_double_clicked)
        self.table_pending.copied_to_clipboard.connect(self._show_clipboard_status)
        layout.addWidget(self.table_pending)

    # --- SEKME 2: TÜM FATURALAR ---
    def _setup_tab_all(self):
        layout = QVBoxLayout(self.tab_all)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        # Uyarı Lejantı
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(16)

        legend_title = QLabel("Durum Uyarıları:")
        legend_title.setStyleSheet("font-weight: 600; color: #94A3B8; font-size: 12px;")
        legend_layout.addWidget(legend_title)

        l_white = QLabel("● Normal / >2 Gün (Beyaz)")
        l_white.setStyleSheet("color: #FFFFFF; font-weight: bold; font-size: 12px;")
        l_yellow = QLabel("● Vadesine 2 Gün Kalan (Sarı)")
        l_yellow.setStyleSheet("color: #EAB308; font-weight: bold; font-size: 12px;")
        l_orange = QLabel("● Vadesine 1 Gün Kalan (Turuncu)")
        l_orange.setStyleSheet("color: #F97316; font-weight: bold; font-size: 12px;")
        l_red = QLabel("● Vadesi Gelmiş/Geçmiş (Kırmızı)")
        l_red.setStyleSheet("color: #EF4444; font-weight: bold; font-size: 12px;")
        l_partial = QLabel("● Kısmi / Parçalı (Kehribar / Sarı)")
        l_partial.setStyleSheet("color: #F59E0B; font-weight: bold; font-size: 12px;")
        l_paid = QLabel("● Ödenmiş (Yeşil)")
        l_paid.setStyleSheet("color: #10B981; font-weight: bold; font-size: 12px;")

        legend_layout.addWidget(l_white)
        legend_layout.addWidget(l_yellow)
        legend_layout.addWidget(l_orange)
        legend_layout.addWidget(l_red)
        legend_layout.addWidget(l_partial)
        legend_layout.addWidget(l_paid)
        legend_layout.addStretch()

        layout.addLayout(legend_layout)

        # Sütunlar: Şirket İsmi, Fatura No, Tarih, Vergi Hariç Fiyat, Vergi (KDV Tutarı), Toplam Fiyat (Vergiler Dahil), Son Ödeme Tarihi, Ödenme Durumu, Kalan Gün Sayısı
        headers = [
            "Şirket İsmi",
            "Fatura No",
            "Fatura Tarihi",
            "Vergi Hariç Fiyat",
            "Vergi (KDV Tutarı)",
            "Toplam Fiyat (Vergiler Dahil)",
            "Son Ödeme Tarihi",
            "Ödenme Durumu",
            "Kalan Gün Sayısı",
        ]
        self.table_all = SortableTableWidget(headers)
        self.table_all.set_column_weights([0.22, 0.13, 0.09, 0.11, 0.09, 0.12, 0.09, 0.07, 0.08])
        self.table_all.cellDoubleClicked.connect(self._on_all_cell_double_clicked)
        self.table_all.copied_to_clipboard.connect(self._show_clipboard_status)
        layout.addWidget(self.table_all)

    # --- SEKME 3: VADESİ GELMİŞ FATURALAR ---
    def _setup_tab_due(self):
        layout = QVBoxLayout(self.tab_due)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        info_lbl = QLabel(
            "⚠️ Vadesi bugüne eşit veya geçmiş, henüz ödenmemiş faturalar listelenir. Çift tıklayarak ödendi işaretleyebilirsiniz."
        )
        info_lbl.setStyleSheet("color: #F87171; font-size: 12px; font-weight: 600; margin-bottom: 4px;")
        layout.addWidget(info_lbl)

        # Sütunlar: Şirket İsmi, Fatura No, Tarih, Vergi Hariç Fiyat, Vergi (KDV Tutarı), Toplam Fiyat (Vergiler Dahil), Son Ödeme Tarihi
        headers = [
            "Şirket İsmi",
            "Fatura No",
            "Fatura Tarihi",
            "Vergi Hariç Fiyat",
            "Vergi (KDV Tutarı)",
            "Toplam Fiyat (Vergiler Dahil)",
            "Son Ödeme Tarihi",
        ]
        self.table_due = SortableTableWidget(headers)
        self.table_due.set_column_weights([0.28, 0.15, 0.11, 0.12, 0.10, 0.13, 0.11])
        self.table_due.cellDoubleClicked.connect(self._on_due_cell_double_clicked)
        self.table_due.copied_to_clipboard.connect(self._show_clipboard_status)
        layout.addWidget(self.table_due)

    # --- SEKME 4: ÖDENMİŞ FATURALAR ---
    def _setup_tab_paid(self):
        layout = QVBoxLayout(self.tab_paid)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        # Araçlar: Tarih Seçiciler (Date Picker / DateEntry) ve Filtrele Butonları
        filter_box = QFrame()
        filter_box.setStyleSheet(f"background-color: #1A2438; border-radius: 8px; padding: 6px;")
        filter_layout = QHBoxLayout(filter_box)
        filter_layout.setContentsMargins(10, 6, 10, 6)
        filter_layout.setSpacing(12)

        # Varsayılan Tarih Aralığı: Son 1 ay (datetime.today() - timedelta(days=30) ile datetime.today())
        today_dt = datetime.today()
        start_dt = today_dt - timedelta(days=30)

        lbl_from = QLabel("Başlangıç Tarihi:")
        lbl_from.setStyleSheet("font-weight: 600; color: #94A3B8;")
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd.MM.yyyy")
        self.date_from.setMinimumDate(QDate(1900, 1, 1))
        self.date_from.setSpecialValueText(" ")
        self.date_from.setDate(QDate(start_dt.year, start_dt.month, start_dt.day))
        if self.date_from.calendarWidget():
            self.date_from.calendarWidget().setGridVisible(True)
        if self.date_from.lineEdit():
            self.date_from.lineEdit().setClearButtonEnabled(True)

        lbl_to = QLabel("Bitiş Tarihi:")
        lbl_to.setStyleSheet("font-weight: 600; color: #94A3B8;")
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd.MM.yyyy")
        self.date_to.setMinimumDate(QDate(1900, 1, 1))
        self.date_to.setSpecialValueText(" ")
        self.date_to.setDate(QDate(today_dt.year, today_dt.month, today_dt.day))
        if self.date_to.calendarWidget():
            self.date_to.calendarWidget().setGridVisible(True)
        if self.date_to.lineEdit():
            self.date_to.lineEdit().setClearButtonEnabled(True)

        self.btn_filter_paid = QPushButton("🔍 Filtrele")
        self.btn_filter_paid.setToolTip("Seçilen tarih aralığına göre ödenmiş faturaları filtrele")
        self.btn_filter_paid.clicked.connect(self._on_filter_paid_clicked)

        # macOS ve Windows klavye Enter/Return desteği
        if self.date_from.lineEdit():
            self.date_from.lineEdit().returnPressed.connect(self._on_filter_paid_clicked)
        if self.date_to.lineEdit():
            self.date_to.lineEdit().returnPressed.connect(self._on_filter_paid_clicked)

        self.btn_reset_paid = QPushButton("Tümünü Göster")
        self.btn_reset_paid.setObjectName("secondaryBtn")
        self.btn_reset_paid.clicked.connect(self._reset_paid_filter)

        filter_layout.addWidget(lbl_from)
        filter_layout.addWidget(self.date_from)
        filter_layout.addWidget(lbl_to)
        filter_layout.addWidget(self.date_to)
        filter_layout.addWidget(self.btn_filter_paid)
        filter_layout.addWidget(self.btn_reset_paid)
        filter_layout.addStretch()

        layout.addWidget(filter_box)

        # Sütunlar: Şirket İsmi, Fatura No, Tarih, Vergi Hariç Fiyat, Vergi (KDV Tutarı), Toplam Fiyat (Vergiler Dahil), Ödeme Tarihi
        headers = [
            "Şirket İsmi",
            "Fatura No",
            "Fatura Tarihi",
            "Vergi Hariç Fiyat",
            "Vergi (KDV Tutarı)",
            "Toplam Fiyat (Vergiler Dahil)",
            "Ödeme Tarihi",
        ]
        self.table_paid = SortableTableWidget(headers)
        self.table_paid.set_column_weights([0.28, 0.15, 0.11, 0.12, 0.10, 0.13, 0.11])
        self.table_paid.cellDoubleClicked.connect(self._on_paid_cell_double_clicked)
        self.table_paid.copied_to_clipboard.connect(self._show_clipboard_status)
        layout.addWidget(self.table_paid)

    def _show_clipboard_status(self, msg: str):
        self.status_bar.showMessage(msg, 4000)

    # --- WATCHDOG ENTEGRASYONU ---
    def _setup_watcher(self):
        self.watcher.new_invoice_detected.connect(self._on_new_invoice_detected)
        self.watcher.duplicate_invoice_skipped.connect(self._on_duplicate_skipped)
        self.watcher.scan_finished.connect(self._on_scan_finished)
        self.watcher.log_message.connect(self._on_log_message)
        self.watcher.start()

    @pyqtSlot(dict)
    def _on_new_invoice_detected(self, inv_data: dict):
        self.refresh_all_tabs()
        inv_no = inv_data.get("invoice_number", "")
        company = inv_data.get("company_name", "")
        self.status_bar.showMessage(f"Yeni fatura kaydedildi: {inv_no} - {company}", 5000)

    @pyqtSlot(str, str)
    def _on_duplicate_skipped(self, inv_no: str, file_name: str):
        self.status_bar.showMessage(f"Mükerrer fatura atlandı: {inv_no} ({file_name})", 4000)

    @pyqtSlot(int, int)
    def _on_scan_finished(self, added: int, total: int):
        self.refresh_all_tabs()
        self.status_bar.showMessage(f"Tarama tamamlandı: {total} PDF taranarak {added} yeni fatura eklendi.", 6000)

    @pyqtSlot(str)
    def _on_log_message(self, msg: str):
        print(f"[Watcher Log] {msg}")

    # --- DROPBOX SENKRONİZASYON SLOTS ---
    @pyqtSlot(str, str)
    def _on_dropbox_status_updated(self, text: str, color: str):
        if hasattr(self, "dropbox_status_lbl"):
            self.dropbox_status_lbl.setText(text)
            self.dropbox_status_lbl.setStyleSheet(f"font-size: 11px; color: {color}; font-weight: 600;")

    @pyqtSlot()
    def _on_cloud_data_reloaded(self):
        self.refresh_all_tabs()
        self.status_bar.showMessage("✓ Dropbox: Buluttaki güncel veriler çekildi ve listeler yenilendi.", 5000)

    @pyqtSlot(int)
    def _on_sync_countdown_tick(self, seconds: int):
        """Dropbox 30 saniyelik Auto-Sync döngüsünün canlı geriye sayım sayacı."""
        if seconds > 0:
            msg = f"⏱️ Sonraki eşitlemeye: {seconds:02d} saniye"
            top_msg = f"⏱️ Eşitleme: {seconds}s"
            color = "#F59E0B" if seconds <= 5 else "#38BDF8"
        else:
            msg = "🔄 Eşitleniyor..."
            top_msg = "🔄 Eşitleniyor..."
            color = "#10B981"

        if hasattr(self, "sb_countdown_lbl"):
            self.sb_countdown_lbl.setText(msg)
            self.sb_countdown_lbl.setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: 11px; padding: 2px 8px; "
                f"background-color: #0F172A; border-radius: 4px; border: 1px solid {color};"
            )
        if hasattr(self, "top_sync_countdown_lbl"):
            self.top_sync_countdown_lbl.setText(top_msg)
            self.top_sync_countdown_lbl.setStyleSheet(f"font-size: 11px; color: {color}; font-weight: 600;")

    @pyqtSlot(int)
    def _on_active_sessions_updated(self, count: int):
        """Dropbox üzerinde aktif oturum sayısı değiştiğinde arayüzü günceller."""
        text = f"👥 Aktif Oturum Sayısı: {count}"
        top_text = f"💻 Aktif Oturum: {count}"
        color = "#10B981" if count <= 1 else "#F59E0B"
        border = "#059669" if count <= 1 else "#D97706"
        bg = "#064E3B" if count <= 1 else "#78350F"

        if hasattr(self, "sb_sessions_lbl"):
            self.sb_sessions_lbl.setText(text)
            self.sb_sessions_lbl.setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: 11px; padding: 2px 8px; "
                f"background-color: {bg}; border-radius: 4px; border: 1px solid {border};"
            )
        if hasattr(self, "top_active_sessions_lbl"):
            self.top_active_sessions_lbl.setText(top_text)
            self.top_active_sessions_lbl.setStyleSheet(f"font-size: 11px; color: {color}; font-weight: 600;")

    # --- VERİ YÜKLEME VE YENİLEME ---
    def refresh_all_tabs(self):
        """Tüm sekmeleri ve istatistik kartlarını günceller."""
        self._load_tab_pending()
        self._load_tab_all()
        self._load_tab_due()
        self._load_tab_paid()
        self._apply_current_search_filter()

    def _update_stat_cards(self, displayed_paid_invoices: Optional[List[Dict[str, Any]]] = None):
        """
        Özet Bilgi Paneli Güncellemesi:
        1. Genel Toplam Alanı (En Üstte - Sabit):
           Hiçbir tarih veya arama filtresine bağlı kalmadan, veritabanındaki (infos.json)
           TÜM faturaların kümülatif tutarlarını gösterir.
           Sıralama: 1. Genel Vergi Hariç, 2. Genel KDV, 3. Genel Toplam
        2. Filtrelenen Toplam Alanı (Hemen Altında - Dinamik):
           Sadece tarih seçici veya arama kutusu ile filtrelenip ekrandaki tabloda listelenen
           faturaların toplamını anlık olarak gösterir.
           Sıralama: 1. Filtrelenen Vergi Hariç, 2. Filtrelenen KDV, 3. Filtrelenen Toplam
        """
        # Durum Sayaçları (Operational Status Counts)
        pending_invoices = self.db.get_pending_invoices()
        all_complete = self.db.get_all_complete_invoices()
        active_count = len([i for i in all_complete if i.get("status") not in ["paid", "ödendi", "odendi"]])
        due_invoices = self.db.get_due_invoices()

        self.card_pending.set_value(str(len(pending_invoices)))
        self.card_all_active.set_value(str(active_count))
        self.card_due_urgent.set_value(str(len(due_invoices)))

        # Aktif sekme ve ilgili tabloyu belirle
        tab_idx = self.tabs.currentIndex() if hasattr(self, "tabs") else 3

        if tab_idx == 3:  # Ödenmiş Faturalar
            list_name = "Ödenmiş Faturalar"
            table = getattr(self, "table_paid", None)
        elif tab_idx == 1:  # Tüm Faturalar
            list_name = "Tüm Faturalar"
            table = getattr(self, "table_all", None)
        elif tab_idx == 2:  # Vadesi Gelmiş Faturalar
            list_name = "Vadesi Gelmiş Faturalar"
            table = getattr(self, "table_due", None)
        else:  # Düzenlenecek Faturalar
            list_name = "Düzenlenecek Faturalar"
            table = getattr(self, "table_pending", None)

        # 1. GENEL TOPLAM ALANI HESAPLAMASI (En Üstte - Sabit: Veritabanındaki TÜM faturaların kümülatif toplamı)
        all_db_invoices = self.db.load_all()
        gen_tax_excluded = sum(float(i.get("tax_excluded_amount") or 0.0) for i in all_db_invoices)
        gen_kdv = sum(float(i.get("kdv_amount") or 0.0) for i in all_db_invoices)
        gen_total = sum(
            float(
                i.get("total_amount")
                if i.get("total_amount") is not None
                else ((i.get("tax_excluded_amount") or 0.0) + (i.get("kdv_amount") or 0.0))
            )
            for i in all_db_invoices
        )

        self.card_gen_tax_excluded.set_value(f"{gen_tax_excluded:,.2f} TL")
        self.card_gen_kdv.set_value(f"{gen_kdv:,.2f} TL")
        self.card_gen_total.set_value(f"{gen_total:,.2f} TL")
        if hasattr(self, "lbl_gen_count"):
            self.lbl_gen_count.setText(f"(Veritabanı Kümülatif: Toplam {len(all_db_invoices)} Kayıt)")

        # 2. FİLTRELENEN TOPLAM ALANI HESAPLAMASI (Hemen Altında - Dinamik)
        # Sadece ekranda görünür olan (tarih ve arama filtrelerinden geçen) satırları toplar
        fil_tax_excluded = 0.0
        fil_kdv = 0.0
        fil_total = 0.0
        visible_count = 0

        if table is not None and table.rowCount() > 0:
            for row in range(table.rowCount()):
                if not table.isRowHidden(row):
                    visible_count += 1
                    # Sütun 3: Vergi Hariç Fiyat
                    item_tax = table.item(row, 3)
                    if item_tax and hasattr(item_tax, "numeric_value"):
                        fil_tax_excluded += item_tax.numeric_value
                    # Sütun 4: Vergi (KDV Tutarı)
                    item_kdv = table.item(row, 4)
                    if item_kdv and hasattr(item_kdv, "numeric_value"):
                        fil_kdv += item_kdv.numeric_value
                    # Sütun 5: Toplam Fiyat (Vergiler Dahil)
                    item_tot = table.item(row, 5)
                    if item_tot and hasattr(item_tot, "numeric_value"):
                        fil_total += item_tot.numeric_value
        elif displayed_paid_invoices is not None and (table is None or table.rowCount() == 0):
            # Tablo henüz çizilmeden önce ilk çağrıda fallback
            fil_tax_excluded = sum(float(i.get("tax_excluded_amount") or 0.0) for i in displayed_paid_invoices)
            fil_kdv = sum(float(i.get("kdv_amount") or 0.0) for i in displayed_paid_invoices)
            fil_total = sum(
                float(
                    i.get("total_amount")
                    if i.get("total_amount") is not None
                    else ((i.get("tax_excluded_amount") or 0.0) + (i.get("kdv_amount") or 0.0))
                )
                for i in displayed_paid_invoices
            )
            visible_count = len(displayed_paid_invoices)

        self.card_fil_tax_excluded.set_value(f"{fil_tax_excluded:,.2f} TL")
        self.card_fil_kdv.set_value(f"{fil_kdv:,.2f} TL")
        self.card_fil_total.set_value(f"{fil_total:,.2f} TL")
        if hasattr(self, "lbl_fil_count"):
            self.lbl_fil_count.setText(f"(Filtrelenen: {visible_count} Fatura Gösteriliyor)")

    def _load_tab_pending(self):
        invoices = self.db.get_pending_invoices()
        self.table_pending.setSortingEnabled(False)
        self.table_pending.clearSelection()
        self.table_pending.clearContents()
        self.table_pending.setRowCount(len(invoices))

        for row, inv in enumerate(invoices):
            inv_id = str(inv.get("id") or inv.get("invoice_number", ""))

            # 0: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, "normal")
            self.table_pending.setItem(row, 0, c_item)

            # 1: Fatura No
            f_item = QTableWidgetItem(str(inv.get("invoice_number", "")))
            self.table_pending.setItem(row, 1, f_item)

            # 2: Fatura Kesim Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_pending.setItem(row, 2, d_item)

            cur = str(inv.get("currency", "TL"))

            # 3: Vergi Hariç Fiyat
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_pending.setItem(row, 3, tax_item)

            # 4: Vergi (KDV Tutarı)
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_pending.setItem(row, 4, kdv_item)

            # 5: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else (tax_ex + kdv)
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_pending.setItem(row, 5, tot_item)

        self.table_pending.setSortingEnabled(True)
        # Sütun ve Ekran Optimizasyonu
        self.table_pending.auto_fit_columns()

    def _load_tab_all(self):
        invoices = self.db.get_all_complete_invoices()
        self.table_all.setSortingEnabled(False)
        self.table_all.clearSelection()
        self.table_all.clearContents()
        self.table_all.setRowCount(len(invoices))

        for row, inv in enumerate(invoices):
            inv_id = str(inv.get("id") or inv.get("invoice_number", ""))
            inv_no = str(inv.get("invoice_number", ""))
            status = str(inv.get("status", "active")).lower()
            due_date = inv.get("due_date")
            days_left = holiday_service.get_days_remaining(due_date)
            cur = str(inv.get("currency", "TL"))

            # 0: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            self.table_all.setItem(row, 0, c_item)

            # 1: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_all.setItem(row, 1, f_item)

            # 2: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_all.setItem(row, 2, d_item)

            # 3: Vergi Hariç Fiyat
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_all.setItem(row, 3, tax_item)

            # 4: Vergi (KDV Tutarı)
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_all.setItem(row, 4, kdv_item)

            # 5: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else (tax_ex + kdv)
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_all.setItem(row, 5, tot_item)

            # 6: Son Ödeme Tarihi
            due_item = DateTableWidgetItem(due_date)
            self.table_all.setItem(row, 6, due_item)

            # 7: Ödenme Durumu
            if status in ["paid", "ödendi", "odendi"]:
                status_text = "✓ Ödendi"
            elif status == "partial":
                paid_amt = float(inv.get("paid_amount") or 0.0)
                status_text = f"⏳ Kısmi Ödendi ({paid_amt:,.2f} {cur})"
            else:
                status_text = "Ödenmedi"

            s_item = QTableWidgetItem(status_text)
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_all.setItem(row, 7, s_item)

            # 8: Kalan Gün Sayısı
            if status in ["paid", "ödendi", "odendi"]:
                kalan_item = QTableWidgetItem("Tamamlandı")
                kalan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            elif status == "partial":
                rem_amt = float(inv.get("remaining_amount") or 0.0)
                if days_left is not None:
                    if days_left > 0:
                        kalan_text = f"{days_left} gün kaldı (Kalan: {rem_amt:,.2f})"
                    elif days_left == 0:
                        kalan_text = f"BUGÜN SON GÜN ({rem_amt:,.2f})"
                    else:
                        kalan_text = f"{abs(days_left)} gün geçti ({rem_amt:,.2f})"
                else:
                    kalan_text = f"Kalan: {rem_amt:,.2f} {cur}"
                kalan_item = QTableWidgetItem(kalan_text)
                kalan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            elif days_left is not None:
                if days_left > 0:
                    kalan_text = f"{days_left} gün kaldı"
                elif days_left == 0:
                    kalan_text = "BUGÜN SON GÜN"
                else:
                    kalan_text = f"{abs(days_left)} gün geçti"

                kalan_item = NumericTableWidgetItem(days_left, kalan_text)
                kalan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                kalan_item = QTableWidgetItem("-")
                kalan_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.table_all.setItem(row, 8, kalan_item)

            # UYARI VE SATIR RENKLENDİRMESİ:
            # - normal: >2 gün kaldı -> BEYAZ
            # - yellow: 2 gün kaldı -> SARI
            # - orange: 1 gün kaldı -> TURUNCU
            # - red: Vadesi gelmiş/geçmiş -> KIRMIZI
            # - partial: Kısmi ödeme yapılmış -> KEHRİBAR / SARI TONLARI (#FDE68A)
            # - paid: Tamamı ödenmiş -> YEŞİL
            if status == "partial":
                status_type = "partial"
            elif status in ["paid", "ödendi", "odendi"]:
                status_type = "paid"
            elif days_left is not None:
                if days_left <= 0:
                    status_type = "red"
                elif days_left == 1:
                    status_type = "orange"
                elif days_left == 2:
                    status_type = "yellow"
                else:
                    status_type = "normal"
            else:
                status_type = "normal"

            # Durum tipini ilk hücreye kaydet (CustomInvoiceRowDelegate tarafından kullanılır)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, status_type)

        self.table_all.setSortingEnabled(True)
        # Sütun ve Ekran Optimizasyonu
        self.table_all.auto_fit_columns()

    def _load_tab_due(self):
        invoices = self.db.get_due_invoices()
        self.table_due.setSortingEnabled(False)
        self.table_due.clearSelection()
        self.table_due.clearContents()
        self.table_due.setRowCount(len(invoices))

        for row, inv in enumerate(invoices):
            inv_id = str(inv.get("id") or inv.get("invoice_number", ""))
            inv_no = str(inv.get("invoice_number", ""))
            cur = str(inv.get("currency", "TL"))

            # 0: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            status_type = "partial" if str(inv.get("status", "")).lower() == "partial" else "red"
            c_item.setData(Qt.ItemDataRole.UserRole + 2, status_type)
            self.table_due.setItem(row, 0, c_item)

            # 1: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_due.setItem(row, 1, f_item)

            # 2: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_due.setItem(row, 2, d_item)

            # 3: Vergi Hariç Fiyat
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_due.setItem(row, 3, tax_item)

            # 4: Vergi (KDV Tutarı)
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_due.setItem(row, 4, kdv_item)

            # 5: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else (tax_ex + kdv)
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_due.setItem(row, 5, tot_item)

            # 6: Son Ödeme Tarihi
            due_item = DateTableWidgetItem(inv.get("due_date"))
            self.table_due.setItem(row, 6, due_item)

        self.table_due.setSortingEnabled(True)
        # Sütun ve Ekran Optimizasyonu
        self.table_due.auto_fit_columns()

    @pyqtSlot()
    def _on_filter_paid_clicked(self):
        """
        Filtrele butonu doğrudan tıklama / komut tetikleyicisi.
        macOS ve Windows event döngüsü ve buton tıklamalarını doğrudan karşılar.
        """
        print("\n" + "=" * 55)
        print("[Filtrele Butonu] Butona tıklandı (Command / Clicked Event tetiklendi).")
        self._load_tab_paid()

    def _load_tab_paid(self, show_all: bool = False):
        """
        Sekme 4: Ödenmiş Faturalar.
        - show_all=True ise: DatePicker bileşenlerinin içindeki mevcut başlangıç ve bitiş
          tarihi değerleri KESİNLİKLE değiştirilmez (State Retention). Yalnızca tablo
          sıfırlanarak tüm Ödendi statüsündeki faturalar listelenir.
        - show_all=False ise: DatePicker'daki mevcut tarihlere göre filtre uygulanır.
        """
        if show_all:
            start_val = None
            end_val = None
            print("[Filtre İzolasyonu] 'Tümünü Göster' tetiklendi: DatePicker değerleri KORUNDU, tüm liste getiriliyor.")
        else:
            # 1. macOS ve Windows Odaklanma (Focus) ve DatePicker Senkronizasyonu
            if hasattr(self, "date_from") and self.date_from:
                self.date_from.interpretText()
            if hasattr(self, "date_to") and self.date_to:
                self.date_to.interpretText()

            # 2. Ham değerleri al ve Veri Temizleme (Sanitization) uygula
            start_raw = self.date_from.text() if hasattr(self, "date_from") else ""
            end_raw = self.date_to.text() if hasattr(self, "date_to") else ""

            start_clean = sanitize_date_str(start_raw)
            end_clean = sanitize_date_str(end_raw)

            # Minimum tarih veya boş alan kontrolü
            start_val = None
            if hasattr(self, "date_from") and self.date_from.date() != self.date_from.minimumDate() and start_clean:
                start_val = start_clean

            end_val = None
            if hasattr(self, "date_to") and self.date_to.date() != self.date_to.minimumDate() and end_clean:
                end_val = end_clean

            # DatePicker Uyumluluk Log Kontrolü
            print(f"[DatePicker Uyumluluk Logu] Başlangıç Tarihi: '{start_val}' (Ham: '{start_raw}') | Bitiş Tarihi: '{end_val}' (Ham: '{end_raw}')")

        # 3. Hata Yakalama (Try-Except ValueError) ile veritabanı sorgusu
        try:
            invoices = self.db.get_paid_invoices(start_date=start_val, end_date=end_val)
            print(f"[Filtreleme Döngüsü] Veritabanından gelen eşleşen ödenmiş fatura sayısı: {len(invoices)}")
        except ValueError as ve:
            print(f"[Filtreleme Hatası] Tarih format uyuşmazlığı tespit edildi (ValueError): {ve}")
            invoices = self.db.get_paid_invoices()  # Hata halinde tüm ödenmiş faturaları güvenli liste olarak getir
        except Exception as e:
            print(f"[Filtreleme Hatası] Beklenmeyen hata: {e}")
            invoices = self.db.get_paid_invoices()

        # 4. Tabloyu önce tamamen temizle
        self.table_paid.setSortingEnabled(False)
        self.table_paid.clearSelection()
        self.table_paid.clearContents()
        self.table_paid.setRowCount(0)

        # 5. Şartı sağlayan kayıtları tabloya yeniden ekle
        self.table_paid.setRowCount(len(invoices))
        for row, inv in enumerate(invoices):
            inv_id = str(inv.get("id") or inv.get("invoice_number", ""))
            inv_no = str(inv.get("invoice_number", ""))
            cur = str(inv.get("currency", "TL"))

            # 0: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, "paid")
            self.table_paid.setItem(row, 0, c_item)

            # 1: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_paid.setItem(row, 1, f_item)

            # 2: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_paid.setItem(row, 2, d_item)

            # 3: Vergi Hariç Fiyat
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_paid.setItem(row, 3, tax_item)

            # 4: Vergi (KDV Tutarı)
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_paid.setItem(row, 4, kdv_item)

            # 5: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else (tax_ex + kdv)
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_paid.setItem(row, 5, tot_item)

            # 6: Ödeme Tarihi
            pay_date = inv.get("payment_date") or inv.get("invoice_date")
            p_item = DateTableWidgetItem(pay_date)
            self.table_paid.setItem(row, 6, p_item)

        self.table_paid.setSortingEnabled(True)
        # Sütun ve Ekran Optimizasyonu
        self.table_paid.auto_fit_columns()

        # Dinamik Toplam Hesaplama (Özet Panel):
        # Filtrelenmiş listedeki faturaların toplamlarını gösterecek şekilde anlık olarak güncellenir.
        self._update_stat_cards(displayed_paid_invoices=invoices)

        # Kullanıcı arayüzünde durum çubuğu bildirimi
        if show_all:
            status_msg = f"Tüm Ödenmiş Faturalar: Toplam {len(invoices)} adet fatura listelendi (Tarih filtreleri korundu)."
        elif start_val and end_val:
            status_msg = f"Ödenmiş Faturalar: {len(invoices)} adet fatura listelendi. (Filtre: {start_val} - {end_val})"
        elif start_val or end_val:
            status_msg = f"Ödenmiş Faturalar: {len(invoices)} adet fatura listelendi (Tarih seçicilerden biri boş bırakıldığı için filtresiz tam liste getirildi)"
        else:
            status_msg = f"Ödenmiş Faturalar: {len(invoices)} adet fatura listelendi (Filtresiz tam liste)"

        self.status_bar.showMessage(status_msg, 5000)
        print(f"[Durum Çubuğu] {status_msg}")
        print("=" * 55 + "\n")

    def _reset_paid_filter(self):
        """
        Filtre İzolasyonu (State Retention):
        Tümünü Göster işlemi yalnızca tablodaki verileri sıfırlayarak tüm 'Ödendi'
        statüsündeki faturaları listeler.
        DatePicker bileşenlerinin içindeki mevcut başlangıç ve bitiş tarihi değerleri
        KESİNLİKLE temizlenmez veya değiştirilmez!
        """
        print("\n" + "=" * 55)
        print("[Tümünü Göster Butonu] DatePicker değerleri KORUNARAK tüm ödenmiş faturalar listeleniyor...")
        self._load_tab_paid(show_all=True)

    # --- FATURA SİLME VE ARŞİVLEME (MOVE & DELETE) ---
    def _delete_and_archive_invoice(self, invoice: Dict[str, Any]):
        """
        Fatura Silme ve Arşivleme (Move & Delete) İşlemi:
        - İlgili PDF dosyası TasımaFaturaları dizininden alınarak TasımaFaturaları/Silinenler
          dizinine (klasör yoksa os.makedirs ile oluşturularak) shutil.move komutuyla taşınır.
        - İlgili faturanın veri kaydı infos.json veritabanından tamamen silinir.
        - Arayüzdeki Treeview/Tablo yeniden yüklenerek silinen fatura listeden kaldırılır.
        """
        inv_id = str(invoice.get("id") or invoice.get("invoice_number", "")).strip()
        inv_no = str(invoice.get("invoice_number", "")).strip()
        file_path = invoice.get("file_path")
        file_name = invoice.get("file_name") or (f"{inv_no}.pdf" if inv_no and inv_no != "Nakit" else "")

        # PDF'in bulunduğu dizini güvenle belirle (Manuel Nakit işlemlerinde PDF olmayabilir)
        if file_path and os.path.exists(file_path):
            source_dir = os.path.dirname(os.path.abspath(file_path))
            actual_src_file = os.path.abspath(file_path)
            silinenler_dir = os.path.join(source_dir, "Silinenler")
            os.makedirs(silinenler_dir, exist_ok=True)
            dest_path = os.path.join(silinenler_dir, os.path.basename(actual_src_file))

            try:
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                shutil.move(actual_src_file, dest_path)
                print(f"[Fatura Silme] Dosya taşındı: {actual_src_file} -> {dest_path}")
            except Exception as e:
                print(f"[Fatura Silme Hatası] Dosya taşınırken hata oluştu: {e}")

        # infos.json dosyasından tamamen sil
        self.db.delete_invoice(inv_id)

        # Tabloları ve istatistik panelini yeniden yükle
        self.refresh_all_tabs()
        self.status_bar.showMessage(f"'{inv_no}' faturası silindi.", 5000)

    # --- ETKİLEŞİMLER VE AKILLI İLETİŞİM GÜNCELLEMESİ ---

    def _handle_invoice_updated(self, inv_id: str, old_invoice: Dict[str, Any], res: Dict[str, Any]):
        """
        Fatura güncellemesini kaydeder ve firma iletişim bilgileri değişmişse
        aynı firmaya ait diğer tüm kayıtların topluca güncellenmesi için kullanıcıdan onay ister.
        """
        # Veritabanını güncelle
        self.db.update_invoice(inv_id, res)

        # Gizli İletişim Bilgileri ve Akıllı Güncelleme Kontrolü:
        # Kullanıcı bir firmanın iletişim bilgisini güncellediğinde sistem aynı firma ismine
        # sahip diğer faturaları kontrol eder ve kullanıcıya onay sorar.
        comp_name = old_invoice.get("company_name", "")
        new_name = res.get("contact_name", "")
        new_phone = res.get("contact_phone", "")
        old_name = old_invoice.get("contact_name", "")
        old_phone = old_invoice.get("contact_phone", "")

        if comp_name and (new_name or new_phone):
            if (new_name != old_name) or (new_phone != old_phone):
                self._check_and_prompt_company_contact_update(comp_name, new_name, new_phone, inv_id)

        self.refresh_all_tabs()

    def _check_and_prompt_company_contact_update(
        self, company_name: str, contact_name: str, contact_phone: str, current_id: str
    ):
        """Aynı firmaya ait diğer faturalar varsa toplu güncelleme onay penceresi açar."""
        others = self.db.get_other_invoices_for_company(company_name, current_id)
        if others:
            reply = QMessageBox.question(
                self,
                "İletişim Bilgilerini Toplu Güncelle",
                f"'{company_name}' firmasına ait sistemde {len(others)} adet daha fatura bulunmaktadır.\n\n"
                "Bu firmaya ait tüm faturaların iletişim bilgileri güncellensin mi?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                count = self.db.update_company_contacts(company_name, contact_name, contact_phone)
                self.status_bar.showMessage(
                    f"'{company_name}' firmasına ait {count} faturanın iletişim bilgileri topluca güncellendi.",
                    5000,
                )

    def _on_pending_cell_double_clicked(self, row: int, col: int):
        """Sekme 1 Çift Tıklama: Vade / İş Günü Belirleme Pop-up'ı."""
        item = self.table_pending.item(row, 0)
        if not item:
            return
        inv_id = item.data(Qt.ItemDataRole.UserRole)
        invoice = self.db.get_invoice(inv_id)
        if not invoice:
            return

        dialog = VadeGirisDialog(invoice, self)
        if dialog.exec():
            if getattr(dialog, "delete_requested", False):
                self._delete_and_archive_invoice(invoice)
                return
            res = dialog.get_result()
            self._handle_invoice_updated(inv_id, invoice, res)
            self.status_bar.showMessage(
                f"{invoice.get('invoice_number')} faturasına {res.get('work_days_added')} iş günü vade eklendi ve 'Tüm Faturalar' sekmesine aktarıldı.",
                5000,
            )

    def _on_all_cell_double_clicked(self, row: int, col: int):
        """Sekme 2 Çift Tıklama: Ödendi / Parçalı Ödeme statüsüne alma veya düzenleme Pop-up'ı."""
        item = self.table_all.item(row, 0)
        if not item:
            return
        inv_id = item.data(Qt.ItemDataRole.UserRole)
        invoice = self.db.get_invoice(inv_id)
        if not invoice:
            return

        dialog = OdemeGirisDialog(invoice, self)
        if dialog.exec():
            if getattr(dialog, "delete_requested", False):
                self._delete_and_archive_invoice(invoice)
                return
            res = dialog.get_result()
            self._handle_invoice_updated(inv_id, invoice, res)
            self.status_bar.showMessage(f"{invoice.get('invoice_number')} fatura durumu güncellendi.", 4000)

    def _on_due_cell_double_clicked(self, row: int, col: int):
        """Sekme 3 Çift Tıklama: Vadesi gelmiş faturayı ödeme / parçalı ödeme yapma."""
        item = self.table_due.item(row, 0)
        if not item:
            return
        inv_id = item.data(Qt.ItemDataRole.UserRole)
        invoice = self.db.get_invoice(inv_id)
        if not invoice:
            return

        dialog = OdemeGirisDialog(invoice, self)
        if dialog.exec():
            if getattr(dialog, "delete_requested", False):
                self._delete_and_archive_invoice(invoice)
                return
            res = dialog.get_result()
            self._handle_invoice_updated(inv_id, invoice, res)
            self.status_bar.showMessage(f"{invoice.get('invoice_number')} faturası güncellendi.", 4000)

    def _on_paid_cell_double_clicked(self, row: int, col: int):
        """Sekme 4 Çift Tıklama: Ödenmiş faturayı düzeltme imkanı."""
        item = self.table_paid.item(row, 0)
        if not item:
            return
        inv_id = item.data(Qt.ItemDataRole.UserRole)
        invoice = self.db.get_invoice(inv_id)
        if not invoice:
            return

        dialog = OdemeGirisDialog(invoice, self)
        if dialog.exec():
            if getattr(dialog, "delete_requested", False):
                self._delete_and_archive_invoice(invoice)
                return
            res = dialog.get_result()
            self._handle_invoice_updated(inv_id, invoice, res)
            self.status_bar.showMessage(f"{invoice.get('invoice_number')} ödeme kaydı güncellendi.", 4000)

    # --- MANUEL NAKİT GİRİŞİ DİYALOĞU ---
    def _open_manual_cash_dialog(self):
        """PDF gerektirmeyen doğrudan Manuel Nakit Girişi pop-up'ını açar."""
        dialog = NakitGirisDialog(db=self.db, parent=self)
        if dialog.exec():
            cash_data = dialog.get_result()
            comp_name = cash_data.get("company_name", "")
            c_name = cash_data.get("contact_name", "")
            c_phone = cash_data.get("contact_phone", "")

            # Veritabanına nakit faturasını ekle
            self.db.add_invoice(cash_data)

            # İletişim bilgisi girilmişse diğer faturalar için toplu güncelleme onayı sor
            if (c_name or c_phone) and comp_name:
                self._check_and_prompt_company_contact_update(comp_name, c_name, c_phone, cash_data.get("id"))

            self.refresh_all_tabs()
            self.status_bar.showMessage(f"Manuel nakit işlemi '{comp_name}' için başarıyla kaydedildi.", 5000)

    # --- ARAMA VE FİLTRELEME (SEARCH BAR) ---
    def _on_search_text_changed(self, text: str):
        self._apply_current_search_filter()

    def _on_tab_changed(self, index: int):
        self._apply_current_search_filter()

    def _apply_current_search_filter(self):
        query = self.search_bar.text()
        current_tab_idx = self.tabs.currentIndex()

        if current_tab_idx == 0:
            self.table_pending.filter_by_text(query, [0, 1])
        elif current_tab_idx == 1:
            self.table_all.filter_by_text(query, [0, 1])
        elif current_tab_idx == 2:
            self.table_due.filter_by_text(query, [0, 1])
        elif current_tab_idx == 3:
            self.table_paid.filter_by_text(query, [0, 1])

        # Dinamik özet panelini filtrelenmiş ekrandaki verilere göre anlık güncelle
        self._update_stat_cards()

    # --- SÜRÜM KONTROL VE GÜNCELLEME SİSTEMİ (VERSION CHECK & AUTO-UPDATE) ---
    def check_for_updates(self, manual: bool = False):
        """GitHub API üzerinden en son yayınlanan Release sürümünü kontrol eder (APK-STU altyapısı)."""
        self.updater.check_for_updates(silent_if_latest=not manual)

    # --- YARDIMCI BUTON İŞLEVLERİ ---
    def _open_invoices_folder(self):
        watch_path = self.watcher.watch_dir
        if not os.path.exists(watch_path):
            os.makedirs(watch_path, exist_ok=True)
        # Windows (.exe), macOS ve Linux uyumlu klasör açma
        if sys.platform.startswith("win"):
            os.startfile(watch_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", watch_path])
        else:
            subprocess.run(["xdg-open", watch_path])

    def _scan_folder_now(self):
        added, total = self.watcher.scan_existing_files()
        QMessageBox.information(
            self,
            "Klasör Taraması",
            f"TasımaFaturaları klasöründe {total} adet PDF bulundu.\n{added} yeni fatura sisteme dahil edildi.",
        )

    def closeEvent(self, event):
        """Uygulama kapatılırken izleyiciyi ve arka plan işlerini durdur."""
        if hasattr(self, "dropbox_sync"):
            self.dropbox_sync.stop()
        self.watcher.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(MAIN_STYLE_SHEET)

    # Görev çubuğu ve uygulama ikonu
    base_dir = get_app_base_dir()
    icon_path = os.path.join(base_dir, "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Font ayarı
    font = QFont("-apple-system", 10)
    app.setFont(font)

    window = FaturaTakipApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

