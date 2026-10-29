# Sürüm Kontrol Sistemi (Version Checking)
APP_VERSION = "v1.0.5"

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
    QComboBox,
    QStackedWidget,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStatusBar,
    QTabWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.components import DateTableWidgetItem, NumericTableWidgetItem, SortableTableWidget, StatCard
from src.database import ExpenseDatabase, InvoiceDatabase, get_app_base_dir, sanitize_date_str
from src.dialogs import (
    GiderYonetimiDialog,
    GiderYonetimiWidget,
    NakitGirisDialog,
    OdemeGirisDialog,
    TopluOdemeDialog,
    TopluVadeDialog,
    VadeGirisDialog,
)
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

        # Uygulama ilk açılışında dizinde kalan eski .old uzantılı dosyaları bulup temizle
        AutoUpdater.cleanup_old_files(self.base_dir)

        # Windows / macOS Görev Çubuğu ve Pencere Simgesi (Taskbar Icon)
        icon_path = os.path.join(self.base_dir, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Veritabanı ve Dizin İzleme Servisi
        self.db = InvoiceDatabase(base_dir=self.base_dir)
        self.watcher = WatcherService(db=self.db, extractor=pdf_extractor)

        # Giderler Veritabanı (expenses.json)
        self.expense_db = ExpenseDatabase(base_dir=self.base_dir)

        # Dropbox Yedekleme ve Çift Yönlü Senkronizasyon (Dropbox OAuth2 Refresh Token desteği)
        self.dropbox_sync = DropboxSyncManager(local_json_path=self.db.json_path, parent=self)
        self.db.add_change_callback(self.dropbox_sync.trigger_instant_upload)
        self.expense_db.add_change_callback(self.dropbox_sync.trigger_instant_upload_expenses)
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
        main_layout.setSpacing(10)

        # 1. ÜST BAR: Header (Sabit)
        top_bar = self._create_top_bar()
        main_layout.addWidget(top_bar)

        # 2. QStackedWidget MİMARİSİ (Dinamik Gövde Geçişi)
        self.stack = QStackedWidget()
        self.stack.currentChanged.connect(lambda idx: self._update_header_buttons_visibility(idx == 0))
        main_layout.addWidget(self.stack, 1)

        # -------------------------------------------------------------
        # 0. İNDEKS (Sayfa 1): Mevcut Fatura Takip Ekranının Tamamı
        # -------------------------------------------------------------
        self.page_invoices = QWidget()
        invoices_layout = QVBoxLayout(self.page_invoices)
        invoices_layout.setContentsMargins(0, 0, 0, 0)
        invoices_layout.setSpacing(10)

        # 2a. FİLTRELEME PANELİ: Doğrudan Header'ın altında, her zaman görünür (Sabit/Daimi)
        self.filter_panel = self._create_filter_panel()
        invoices_layout.addWidget(self.filter_panel)

        # 2b. TOPLAM TUTAR VE DURUM ÖZETLERİ (Bütünleşik Panel)
        stats_bar = self._create_stats_bar()
        invoices_layout.addWidget(stats_bar)

        # 2c. TOPLU İŞLEMLER ÇUBUĞU (Bulk Actions Toolbar)
        self.bulk_bar = self._create_bulk_actions_bar()
        invoices_layout.addWidget(self.bulk_bar)

        # 2d. FATURA SEKMELERİ (QTabWidget - Gider Yönetimi tamamen kaldırıldı)
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

        # Sekme 3: Nakit (Önceden: Vadesi Gelmiş Faturalar)
        self.tab_due = QWidget()
        self._setup_tab_due()
        self.tabs.addTab(self.tab_due, "  💵 Nakit  ")

        # Sekme 4: Ödenmemiş Faturalar
        self.tab_unpaid = QWidget()
        self._setup_tab_unpaid()
        self.tabs.addTab(self.tab_unpaid, "  Ödenmemiş Faturalar  ")

        # Sekme 5: Ödenmiş Faturalar
        self.tab_paid = QWidget()
        self._setup_tab_paid()
        self.tabs.addTab(self.tab_paid, "  Ödenmiş Faturalar  ")

        invoices_layout.addWidget(self.tabs, 1)
        self.stack.addWidget(self.page_invoices)

        # -------------------------------------------------------------
        # 1. İNDEKS (Sayfa 2): Sadece "Gider Yönetimi" Modülü (Tam Boyut)
        # -------------------------------------------------------------
        self.page_expenses = QWidget()
        expenses_layout = QVBoxLayout(self.page_expenses)
        expenses_layout.setContentsMargins(0, 0, 0, 0)
        expenses_layout.setSpacing(0)

        self.expenses_widget = GiderYonetimiWidget(
            db=self.db,
            expense_db=self.expense_db,
            dropbox_sync=self.dropbox_sync,
            parent=self.page_expenses,
        )
        expenses_layout.addWidget(self.expenses_widget, 1)
        self.stack.addWidget(self.page_expenses)

        # Varsayılan olarak Fatura Takip ekranı (0. indeks) aktiftir
        self.stack.setCurrentIndex(0)

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

    def _update_header_buttons_visibility(self, visible: bool):
        """
        Dinamik Header Butonları (Görünürlük Yönetimi):
        'Manuel Nakit Girişi', 'Klasörü Aç' ve 'Klasörü Tara' butonları doğrudan fatura takibi ekranının işlevleridir.
        Gider Yönetimi ekranında bu butonlar gizlenir (hide()), Fatura Takibine dönüldüğünde tekrar gösterilir (show()).
        """
        for btn in (
            getattr(self, "btn_manual_cash", None),
            getattr(self, "btn_open_folder", None),
            getattr(self, "btn_scan", None),
        ):
            if btn is not None:
                if visible:
                    btn.show()
                else:
                    btn.hide()

    def _toggle_view_mode(self):
        """
        Header Butonu ile Dinamik Görünüm Değiştirme:
        Üst kısımdaki Header'da yer alan 'Gider Yönetimi' butonu tıklandığında:
        - 0. İndeksteyse (Fatura Takip): Görünüm 1. İndekse (Gider Yönetimi) geçer,
          buton metni '📄 Fatura Takibine Geç' olarak güncellenir.
          'Manuel Nakit Girişi', 'Klasörü Aç' ve 'Klasörü Tara' butonları gizlenir (hide()).
        - 1. İndeksteyse (Gider Yönetimi): Görünüm 0. İndekse (Fatura Takip) geri döner,
          buton metni '📊 Gider Yönetimi' eski haline döner.
          'Manuel Nakit Girişi', 'Klasörü Aç' ve 'Klasörü Tara' butonları tekrar gösterilir (show()).
        """
        if not hasattr(self, "stack"):
            return

        current_idx = self.stack.currentIndex()
        if current_idx == 0:
            # Fatura Takip -> Gider Yönetimi
            self.stack.setCurrentIndex(1)
            if hasattr(self, "btn_expenses"):
                self.btn_expenses.setText("📄 Fatura Takibine Geç")
                self.btn_expenses.setToolTip("Gider Yönetiminden çıkıp ana Fatura Takip ekranına dön")
                self.btn_expenses.setStyleSheet(
                    "background-color: #0284C7; color: #FFFFFF; font-weight: bold; border: 1px solid #38BDF8; padding: 6px 14px; border-radius: 6px;"
                )
            self._update_header_buttons_visibility(False)
            if hasattr(self, "expenses_widget"):
                self.expenses_widget.refresh_all()
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage("Gider Yönetimi ve Finansal Analiz modülü görüntüleniyor.", 4000)
        else:
            # Gider Yönetimi -> Fatura Takip
            self.stack.setCurrentIndex(0)
            if hasattr(self, "btn_expenses"):
                self.btn_expenses.setText("📊 Gider Yönetimi")
                self.btn_expenses.setToolTip("Gider türlerini düzenle, yeni gider kaydet ve Gelir - Gider finansal özetini incele")
                self.btn_expenses.setStyleSheet(
                    "background-color: #1E293B; color: #38BDF8; font-weight: bold; border: 1px solid #0284C7; padding: 6px 14px; border-radius: 6px;"
                )
            self._update_header_buttons_visibility(True)
            self.refresh_all_tabs()
            if hasattr(self, "status_bar"):
                self.status_bar.showMessage("Fatura Takip ekranına dönüldü.", 4000)

    def _open_expenses_dialog(self):
        """Geriye dönük uyumluluk çağrısı: Görünüm modunu değiştirir."""
        self._toggle_view_mode()

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

        # Klasörü Aç Butonu
        self.btn_open_folder = QPushButton("📁 Klasörü Aç")
        self.btn_open_folder.setObjectName("secondaryBtn")
        self.btn_open_folder.setToolTip("TasımaFaturaları klasörünü Finder'da / Dosya Yöneticisi'nde aç")
        self.btn_open_folder.clicked.connect(self._open_invoices_folder)
        layout.addWidget(self.btn_open_folder)

        # Klasörü Tara Butonu
        self.btn_scan = QPushButton("🔄 Klasörü Tara")
        self.btn_scan.setObjectName("secondaryBtn")
        self.btn_scan.setToolTip("Klasördeki yeni veya taranmamış PDF'leri tara")
        self.btn_scan.clicked.connect(self._scan_folder_now)
        layout.addWidget(self.btn_scan)

        # Gider Yönetimi Butonu (Doğrudan Klasörü Tara ile Güncellemeleri Kontrol Et arasında)
        self.btn_expenses = QPushButton("📊 Gider Yönetimi")
        self.btn_expenses.setObjectName("secondaryBtn")
        self.btn_expenses.setStyleSheet(
            "background-color: #1E293B; color: #38BDF8; font-weight: bold; border: 1px solid #0284C7; padding: 6px 14px; border-radius: 6px;"
        )
        self.btn_expenses.setToolTip("Gider türlerini düzenle, yeni gider kaydet ve Gelir - Gider finansal özetini incele")
        self.btn_expenses.clicked.connect(self._toggle_view_mode)
        layout.addWidget(self.btn_expenses)

        # Güncellemeleri Kontrol Et Butonu
        self.btn_check_update = QPushButton("🚀 Güncellemeleri Kontrol Et")
        self.btn_check_update.setObjectName("secondaryBtn")
        self.btn_check_update.setToolTip("GitHub üzerinden yeni sürüm kontrolü yap")
        self.btn_check_update.clicked.connect(self._manual_check_for_updates)
        layout.addWidget(self.btn_check_update)

        return frame

    def _create_filter_panel(self) -> QFrame:
        """
        Filtreleme Araçları Paneli:
        Header'ın hemen altına yerleştirilmiştir. Açılır-kapanır (toggle) özelliği
        olmadan her zaman ekranda görünür kalır (Arama, ComboBox'lar, Tarih seçiciler, Filtrele/Sıfırla).
        """
        panel = QFrame()
        panel.setObjectName("topFilterPanel")
        panel.setStyleSheet(
            "QFrame#topFilterPanel { background-color: #1A2438; border: 1px solid #334155; border-radius: 8px; padding: 4px 8px; }"
        )
        filter_layout = QHBoxLayout(panel)
        filter_layout.setContentsMargins(8, 4, 8, 4)
        filter_layout.setSpacing(8)

        # Arama Çubuğu
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("searchBar")
        self.search_bar.setPlaceholderText("🔍 Şirket / Fatura No...")
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.setMinimumWidth(150)
        self.search_bar.setMaximumWidth(220)
        self.search_bar.textChanged.connect(self._on_search_text_changed)
        filter_layout.addWidget(self.search_bar)

        # Nakit / Fatura Türü Filtresi
        self.combo_cash_type = QComboBox()
        self.combo_cash_type.setView(QListView())
        self.combo_cash_type.addItems(["Hepsi", "Nakit Dışı (Sadece Faturalar)"])
        self.combo_cash_type.setToolTip("İşlem Türü Filtresi: Tüm kayıtlar veya nakit dışı (sadece faturalar)")
        self.combo_cash_type.setMaximumWidth(170)
        self.combo_cash_type.currentIndexChanged.connect(lambda: self._apply_all_filters())
        filter_layout.addWidget(self.combo_cash_type)

        # Tarih Türü Seçimi
        self.combo_date_type = QComboBox()
        self.combo_date_type.setView(QListView())
        self.combo_date_type.addItems(["Fatura Kesim Tarihi", "Son Ödeme (Vade/Ödenme) Tarihi"])
        self.combo_date_type.setToolTip("Tarih Türü Seçimi: Girilen tarih aralığının hangi veri sütununda aranacağını belirler")
        self.combo_date_type.setMaximumWidth(190)
        self.combo_date_type.currentIndexChanged.connect(lambda: self._apply_all_filters())
        filter_layout.addWidget(self.combo_date_type)

        # Tarih Seçiciler
        today_dt = datetime.today()
        start_dt = today_dt - timedelta(days=30)

        lbl_from = QLabel("Başlangıç:")
        lbl_from.setStyleSheet("font-weight: 600; color: #94A3B8; font-size: 11px;")
        filter_layout.addWidget(lbl_from)

        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat("dd.MM.yyyy")
        self.date_from.setMinimumDate(QDate(1900, 1, 1))
        self.date_from.setSpecialValueText(" ")
        self.date_from.setDate(QDate(start_dt.year, start_dt.month, start_dt.day))
        self.date_from.setMaximumWidth(105)
        if self.date_from.calendarWidget():
            self.date_from.calendarWidget().setGridVisible(True)
        filter_layout.addWidget(self.date_from)

        lbl_to = QLabel("Bitiş:")
        lbl_to.setStyleSheet("font-weight: 600; color: #94A3B8; font-size: 11px;")
        filter_layout.addWidget(lbl_to)

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat("dd.MM.yyyy")
        self.date_to.setMinimumDate(QDate(1900, 1, 1))
        self.date_to.setSpecialValueText(" ")
        self.date_to.setDate(QDate(today_dt.year, today_dt.month, today_dt.day))
        self.date_to.setMaximumWidth(105)
        if self.date_to.calendarWidget():
            self.date_to.calendarWidget().setGridVisible(True)
        filter_layout.addWidget(self.date_to)

        # Filtrele ve Tümünü Göster Butonları
        self.btn_filter_paid = QPushButton("🔍 Filtrele")
        self.btn_filter_paid.setStyleSheet("padding: 5px 12px; font-size: 11px; font-weight: bold;")
        self.btn_filter_paid.setToolTip("Seçilen tarih aralığı, tür ve aramaya göre aktif sekmeyi filtrele")
        self.btn_filter_paid.clicked.connect(self._on_filter_paid_clicked)
        filter_layout.addWidget(self.btn_filter_paid)

        if self.date_from.lineEdit():
            self.date_from.lineEdit().returnPressed.connect(self._on_filter_paid_clicked)
        if self.date_to.lineEdit():
            self.date_to.lineEdit().returnPressed.connect(self._on_filter_paid_clicked)

        self.btn_reset_paid = QPushButton("Tümünü Göster")
        self.btn_reset_paid.setObjectName("secondaryBtn")
        self.btn_reset_paid.setStyleSheet("padding: 5px 10px; font-size: 11px;")
        self.btn_reset_paid.setToolTip("Tarih filtresini kaldırıp tüm faturaları göster (Tarihler korunur)")
        self.btn_reset_paid.clicked.connect(self._reset_paid_filter)
        filter_layout.addWidget(self.btn_reset_paid)

        filter_layout.addStretch()

        return panel

    def _create_stats_bar(self) -> QWidget:
        """
        'Toplam Tutar ve Durum Özetleri' Bütünleşik Paneli:
        Durum Özetleri kutuları ile Filtrelenen Toplam alanını tek bir QFrame/düzen içine alır.
        Dikey sıralama:
        1. Başlık ve Açılır/Kapanır Çubuğu (Collapsible Toggle Bar)
        2. Bütünleşik Gövde (summary_container):
           - Üstte: Durum Özetleri (DÜZENLENECEK, AKTİF / BEKLEYEN, VADESİ GELMİŞ / GEÇMİŞ)
           - Altta: Filtrelenen Toplam alanı (Dinamik - Vergi Hariç, KDV, Toplam, Adet)
        (Genel Toplam alanı tamamen kaldırılmıştır).
        """
        container = QFrame()
        container.setObjectName("unifiedStatsContainer")
        container.setStyleSheet(
            "QFrame#unifiedStatsContainer { background-color: #1A2438; border: 1px solid #334155; border-radius: 8px; padding: 4px; }"
        )
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # 1. AÇILIR / KAPANIR BAŞLIK ÇUBUĞU (Collapsible Toggle Bar)
        self.summary_toggle_bar = QFrame()
        self.summary_toggle_bar.setObjectName("summaryToggleBar")
        self.summary_toggle_bar.setStyleSheet(
            "QFrame#summaryToggleBar { background-color: #1E293B; border: 1px solid #334155; border-radius: 6px; padding: 2px 8px; }"
            "QFrame#summaryToggleBar:hover { background-color: #273549; border-color: #475569; }"
        )
        self.summary_toggle_bar.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_bar_layout = QHBoxLayout(self.summary_toggle_bar)
        toggle_bar_layout.setContentsMargins(8, 4, 8, 4)
        toggle_bar_layout.setSpacing(8)

        toggle_title = QLabel("📊 TOPLAM TUTAR VE DURUM ÖZETLERİ")
        toggle_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #E2E8F0; letter-spacing: 0.5px;")
        toggle_hint = QLabel("(Paneli açıp kapatmak için tıklayabilirsiniz)")
        toggle_hint.setStyleSheet("font-size: 10px; color: #94A3B8; font-weight: normal;")

        toggle_bar_layout.addWidget(toggle_title)
        toggle_bar_layout.addWidget(toggle_hint)
        toggle_bar_layout.addStretch()

        self.btn_toggle_summary = QPushButton("▲ Paneli Gizle")
        self.btn_toggle_summary.setObjectName("summaryToggleBtn")
        self.btn_toggle_summary.setStyleSheet(
            "QPushButton#summaryToggleBtn { background-color: #0F172A; color: #38BDF8; font-size: 11px; font-weight: bold; "
            "border: 1px solid #0284C7; border-radius: 4px; padding: 3px 10px; }"
            "QPushButton#summaryToggleBtn:hover { background-color: #0284C7; color: #FFFFFF; }"
        )
        self.btn_toggle_summary.setToolTip("Toplam tutar ve durum özet göstergelerini gizle/göster (Tablo alanını genişlet)")
        self.btn_toggle_summary.clicked.connect(self._toggle_summary_panel)
        toggle_bar_layout.addWidget(self.btn_toggle_summary)

        self.summary_toggle_bar.mousePressEvent = lambda e: self._toggle_summary_panel()
        main_layout.addWidget(self.summary_toggle_bar)

        # 2. BÜTÜNLEŞİK ÖZET GÖVDESİ (summary_container)
        self.summary_container = QWidget()
        summary_vbox = QVBoxLayout(self.summary_container)
        summary_vbox.setContentsMargins(0, 0, 0, 0)
        summary_vbox.setSpacing(6)

        # 2a. ÜST SATIR: DURUM ÖZETLERİ (DÜZENLENECEK, AKTİF / BEKLEYEN, VADESİ GELMİŞ / GEÇMİŞ)
        self.frame_status_cards = QFrame()
        self.frame_status_cards.setObjectName("frameStatusCards")
        status_cards_layout = QHBoxLayout(self.frame_status_cards)
        status_cards_layout.setContentsMargins(0, 0, 0, 0)
        status_cards_layout.setSpacing(8)

        self.card_pending = StatCard("DÜZENLENECEK (EKSİK VADE)", "0", "#F97316")
        self.card_all_active = StatCard("AKTİF / BEKLEYEN", "0", "#60A5FA")
        self.card_due_urgent = StatCard("VADESİ GELMİŞ / GEÇMİŞ", "0", "#EF4444")

        status_cards_layout.addWidget(self.card_pending)
        status_cards_layout.addWidget(self.card_all_active)
        status_cards_layout.addWidget(self.card_due_urgent)
        summary_vbox.addWidget(self.frame_status_cards)

        # 2b. ALT SATIR: FİLTRELENEN TOPLAM ALANI (Dinamik Hesap Özeti)
        self.frame_filtered = QFrame()
        self.frame_filtered.setObjectName("summaryFrameFiltered")
        self.frame_filtered.setCursor(Qt.CursorShape.PointingHandCursor)
        self.frame_filtered.mousePressEvent = lambda e: self._toggle_summary_panel()
        fil_vbox = QVBoxLayout(self.frame_filtered)
        fil_vbox.setContentsMargins(10, 6, 10, 6)
        fil_vbox.setSpacing(4)

        fil_header_layout = QHBoxLayout()
        self.lbl_fil_title = QLabel("🔍 FİLTRELENEN TOPLAM ALANI (DİNAMİK — TARİH / ARAMA)")
        self.lbl_fil_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #38BDF8; letter-spacing: 0.5px;")
        self.lbl_fil_count = QLabel("(Sistemdeki toplam 0 fatura içinden 0 adet fatura listeleniyor)")
        self.lbl_fil_count.setStyleSheet("font-size: 11px; font-weight: 600; color: #94A3B8;")
        fil_header_layout.addWidget(self.lbl_fil_title)
        fil_header_layout.addWidget(self.lbl_fil_count)
        fil_header_layout.addStretch()
        fil_vbox.addLayout(fil_header_layout)

        fil_cards_layout = QHBoxLayout()
        fil_cards_layout.setSpacing(8)
        self.card_fil_tax_excluded = StatCard("FİLTRELENEN VERGİ HARİÇ", "0.00 TL", "#38BDF8")
        self.card_fil_kdv = StatCard("FİLTRELENEN KDV", "0.00 TL", "#F59E0B")
        self.card_fil_total = StatCard("FİLTRELENEN TOPLAM", "0.00 TL", "#10B981")
        self.card_fil_count = StatCard("FİLTRELENEN ADET", "Toplam Adet: 0", "#38BDF8")
        self.lbl_fil_adet = self.card_fil_count.value_label

        fil_cards_layout.addWidget(self.card_fil_tax_excluded)
        fil_cards_layout.addWidget(self.card_fil_kdv)
        fil_cards_layout.addWidget(self.card_fil_total)
        fil_cards_layout.addWidget(self.card_fil_count)
        fil_vbox.addLayout(fil_cards_layout)

        summary_vbox.addWidget(self.frame_filtered)
        main_layout.addWidget(self.summary_container)

        # Geriye dönük uyumluluk takma adları (Genel Toplam kaldırıldığı için Filtrelenen Toplam'a eşlenir)
        self.card_total_tax_excluded = self.card_fil_tax_excluded
        self.card_total_kdv = self.card_fil_kdv
        self.card_total_amount = self.card_fil_total
        self.card_gen_tax_excluded = self.card_fil_tax_excluded
        self.card_gen_kdv = self.card_fil_kdv
        self.card_gen_total = self.card_fil_total
        self.card_gen_count = self.card_fil_count
        self.lbl_gen_adet = self.card_fil_count.value_label

        return container

    def _toggle_summary_panel(self):
        """Üst kısımdaki toplam tutar ve durum özet panelini (Genel, Filtrelenen ve 3 Durum Kutusu) açar veya gizler."""
        if not hasattr(self, "summary_container"):
            return
        is_hidden = self.summary_container.isHidden()
        new_state = is_hidden  # Gizliyse göster (True), görünürse gizle (False)
        self.summary_container.setVisible(new_state)
        if hasattr(self, "btn_toggle_summary"):
            if new_state:
                self.btn_toggle_summary.setText("▲ Paneli Gizle")
                self.btn_toggle_summary.setToolTip("Toplam tutar ve durum göstergelerini gizle (Tablo alanını genişlet)")
            else:
                self.btn_toggle_summary.setText("▼ Paneli Göster")
                self.btn_toggle_summary.setToolTip("Toplam tutar ve durum göstergelerini görüntüle")

    def _toggle_filter_panel(self, force_close: bool = False):
        """Filtre paneli artık ana ekranda daimi olarak görünür haldedir."""
        pass

    def _update_top_panel_sizing(self, is_filter_visible: bool = True):
        """Filtre paneli ve durum kutuları ayrı yerleşimlere taşındığı için uyumluluk metodu."""
        pass

    def _update_filter_button_state(self):
        """Filtrele butonu daimi açık olduğundan uyumluluk metodu."""
        pass

    # --- TOPLU İŞLEMLER ÇUBUĞU VE EYLEMLERİ (BULK ACTIONS) ---
    def _create_bulk_actions_bar(self) -> QWidget:
        """Tabloların üstünde yer alan toplu işlemler (Toplu Sil, Toplu Vade, Toplu Ödendi) çubuğu."""
        bar = QFrame()
        bar.setObjectName("bulkActionsBar")
        bar.setStyleSheet(
            "QFrame#bulkActionsBar { background-color: #1A2438; border: 1px solid #334155; border-radius: 8px; padding: 4px 10px; }"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(10)

        lbl_title = QLabel("⚡ Seçili Olanlar İçin:")
        lbl_title.setStyleSheet("font-size: 12px; font-weight: 800; color: #E2E8F0; letter-spacing: 0.3px;")
        layout.addWidget(lbl_title)

        self.lbl_selected_count = QLabel("(0 fatura seçildi)")
        self.lbl_selected_count.setStyleSheet("font-size: 11px; font-weight: 600; color: #94A3B8;")
        layout.addWidget(self.lbl_selected_count)

        # Hızlı Seçim Butonları
        self.btn_select_all = QPushButton("Tümünü Seç")
        self.btn_select_all.setObjectName("secondaryBtn")
        self.btn_select_all.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.btn_select_all.setToolTip("Aktif sekmedeki tüm faturaların onay kutularını işaretle")
        self.btn_select_all.clicked.connect(self._select_all_current_tab)
        layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("Seçimi Kaldır")
        self.btn_deselect_all.setObjectName("secondaryBtn")
        self.btn_deselect_all.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        self.btn_deselect_all.setToolTip("Aktif sekmedeki tüm onay kutularının işaretini kaldır")
        self.btn_deselect_all.clicked.connect(self._deselect_all_current_tab)
        layout.addWidget(self.btn_deselect_all)

        layout.addStretch()

        # 3 Toplu İşlem Butonu:
        # 1. Toplu Ödendi İşaretle
        self.btn_bulk_mark_paid = QPushButton("✅ Toplu Ödendi İşaretle")
        self.btn_bulk_mark_paid.setObjectName("successBtn")
        self.btn_bulk_mark_paid.setStyleSheet("padding: 5px 12px; font-size: 11px; font-weight: bold;")
        self.btn_bulk_mark_paid.setToolTip("İşaretli tüm faturaları tek seferde 'Ödendi' olarak kaydet")
        self.btn_bulk_mark_paid.setEnabled(False)
        self.btn_bulk_mark_paid.clicked.connect(self._handle_bulk_mark_paid)
        layout.addWidget(self.btn_bulk_mark_paid)

        # 2. Toplu Vade Değiştir
        self.btn_bulk_due_date = QPushButton("📅 Toplu Vade Değiştir")
        self.btn_bulk_due_date.setObjectName("primaryBtn")
        self.btn_bulk_due_date.setStyleSheet("padding: 5px 12px; font-size: 11px; font-weight: bold; background-color: #0284C7; color: #FFFFFF; border-radius: 6px;")
        self.btn_bulk_due_date.setToolTip("İşaretli faturalar için tek bir tarih seçici ile vadesini güncelle")
        self.btn_bulk_due_date.setEnabled(False)
        self.btn_bulk_due_date.clicked.connect(self._handle_bulk_due_date)
        layout.addWidget(self.btn_bulk_due_date)

        # 3. Toplu Sil
        self.btn_bulk_delete = QPushButton("🗑️ Toplu Sil")
        self.btn_bulk_delete.setObjectName("dangerBtn")
        self.btn_bulk_delete.setStyleSheet("padding: 5px 12px; font-size: 11px; font-weight: bold;")
        self.btn_bulk_delete.setToolTip("İşaretli faturaların tamamını silip PDF dosyalarını Silinenler klasörüne taşı")
        self.btn_bulk_delete.setEnabled(False)
        self.btn_bulk_delete.clicked.connect(self._handle_bulk_delete)
        layout.addWidget(self.btn_bulk_delete)

        return bar

    def _get_active_table(self) -> Optional[SortableTableWidget]:
        """Şu anda aktif olan sekmedeki tabloyu döner."""
        if not hasattr(self, "tabs"):
            return None
        idx = self.tabs.currentIndex()
        if idx == 0:
            return getattr(self, "table_pending", None)
        elif idx == 1:
            return getattr(self, "table_all", None)
        elif idx == 2:
            return getattr(self, "table_due", None)
        elif idx == 3:
            return getattr(self, "table_unpaid", None)
        elif idx == 4:
            return getattr(self, "table_paid", None)
        return None

    def _select_all_current_tab(self):
        """Aktif sekmedeki tüm faturaların onay kutularını işaretler."""
        table = self._get_active_table()
        if table:
            table.select_all_checkboxes(True)
            self._update_bulk_actions_state()

    def _deselect_all_current_tab(self):
        """Aktif sekmedeki tüm onay kutularının işaretini kaldırır."""
        table = self._get_active_table()
        if table:
            table.select_all_checkboxes(False)
            self._update_bulk_actions_state()

    def _on_table_item_changed(self, item: QTableWidgetItem):
        """Onay kutusu (Checkbox) durumu değiştiğinde toplu işlem butonlarını güncelle."""
        if item and item.column() == 0:
            self._update_bulk_actions_state()

    def _update_bulk_actions_state(self):
        """Aktif sekmede işaretlenmiş fatura sayısına göre buton durumlarını ayarlar."""
        table = self._get_active_table()
        checked_ids = table.get_checked_invoice_ids() if table else []
        count = len(checked_ids)
        if hasattr(self, "lbl_selected_count"):
            self.lbl_selected_count.setText(f"({count} fatura seçildi)")
        if hasattr(self, "btn_bulk_mark_paid"):
            self.btn_bulk_mark_paid.setEnabled(count > 0)
        if hasattr(self, "btn_bulk_due_date"):
            self.btn_bulk_due_date.setEnabled(count > 0)
        if hasattr(self, "btn_bulk_delete"):
            self.btn_bulk_delete.setEnabled(count > 0)

    def _handle_bulk_delete(self):
        """Seçilen onay kutuları üzerinden: Toplu Silme."""
        table = self._get_active_table()
        if not table:
            return
        checked_ids = table.get_checked_invoice_ids()
        if not checked_ids:
            QMessageBox.information(self, "Toplu Silme", "Lütfen önce silmek istediğiniz faturaların onay kutularını (✓) işaretleyiniz.")
            return

        reply = QMessageBox.question(
            self,
            "Toplu Fatura Silme Onayı",
            f"İşaretli olan {len(checked_ids)} adet faturayı silmek ve PDF dosyalarını 'Silinenler' klasörüne taşımak istediğinize emin misiniz?\n\nBu işlem veritabanındaki kayıtları tamamen kaldıracaktır.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            deleted_count = 0
            for inv_id in checked_ids:
                inv = self.db.get_invoice(inv_id)
                if inv:
                    file_path = inv.get("file_path")
                    if file_path and os.path.exists(file_path):
                        source_dir = os.path.dirname(os.path.abspath(file_path))
                        silinenler_dir = os.path.join(source_dir, "Silinenler")
                        os.makedirs(silinenler_dir, exist_ok=True)
                        dest_path = os.path.join(silinenler_dir, os.path.basename(file_path))
                        try:
                            if os.path.exists(dest_path):
                                try:
                                    os.remove(dest_path)
                                except Exception:
                                    pass
                            shutil.move(file_path, dest_path)
                        except Exception as e:
                            print(f"[Toplu Silme] Dosya taşıma hatası: {e}")
                    self.db.delete_invoice(inv_id)
                    deleted_count += 1

            self.refresh_all_tabs()
            self._update_bulk_actions_state()
            self.status_bar.showMessage(f"Toplu Silme Tamamlandı: {deleted_count} adet fatura silindi ve arşivlendi.", 5000)

    def _handle_bulk_due_date(self):
        """Seçilen onay kutuları üzerinden: Toplu Vade Değiştirme."""
        table = self._get_active_table()
        if not table:
            return
        checked_ids = table.get_checked_invoice_ids()
        if not checked_ids:
            QMessageBox.information(self, "Toplu Vade Belirleme", "Lütfen önce vadesini değiştirmek istediğiniz faturaların onay kutularını (✓) işaretleyiniz.")
            return

        dialog = TopluVadeDialog(len(checked_ids), parent=self)
        if dialog.exec():
            new_date = dialog.get_selected_date()
            if new_date:
                updated_count = 0
                for inv_id in checked_ids:
                    inv = self.db.get_invoice(inv_id)
                    if inv:
                        cur_status = inv.get("status")
                        update_payload = {"due_date": new_date}
                        if not cur_status or cur_status == "pending":
                            update_payload["status"] = "active"
                        self.db.update_invoice(inv_id, update_payload)
                        updated_count += 1

                self.refresh_all_tabs()
                self._update_bulk_actions_state()
                self.status_bar.showMessage(f"Toplu Vade Güncellendi: {updated_count} adet faturanın vadesi '{dialog.get_selected_date_display()}' olarak ayarlandı.", 5000)

    def _handle_bulk_mark_paid(self):
        """Seçilen onay kutuları üzerinden: Toplu Ödendi İşaretleme."""
        table = self._get_active_table()
        if not table:
            return
        checked_ids = table.get_checked_invoice_ids()
        if not checked_ids:
            QMessageBox.information(self, "Toplu Ödendi İşaretleme", "Lütfen önce ödendi yapmak istediğiniz faturaların onay kutularını (✓) işaretleyiniz.")
            return

        dialog = TopluOdemeDialog(len(checked_ids), parent=self)
        if dialog.exec():
            pay_date = dialog.get_selected_date()
            updated_count = 0
            for inv_id in checked_ids:
                inv = self.db.get_invoice(inv_id)
                if inv:
                    tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
                    kdv = float(inv.get("kdv_amount") or 0.0)
                    tot = float(inv.get("total_amount") if inv.get("total_amount") is not None else (tax_ex + kdv))
                    self.db.update_invoice(
                        inv_id,
                        {
                            "status": "paid",
                            "payment_date": pay_date,
                            "paid_amount": tot,
                            "remaining_amount": 0.0,
                        },
                    )
                    updated_count += 1

            self.refresh_all_tabs()
            self._update_bulk_actions_state()
            self.status_bar.showMessage(f"Toplu İşlem Başarılı: {updated_count} adet fatura '{dialog.get_selected_date_display()}' tarihiyle 'Ödendi' olarak kaydedildi.", 5000)

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

        # Sütunlar: ✓, Şirket İsmi, Fatura No, Tarih, Vergi Hariç Fiyat, Vergi (KDV Tutarı), Toplam Fiyat (Vergiler Dahil)
        headers = [
            "✓",
            "Şirket İsmi",
            "Fatura No",
            "Fatura Kesim Tarihi",
            "Vergi Hariç Fiyat",
            "Vergi (KDV Tutarı)",
            "Toplam Fiyat (Vergiler Dahil)",
        ]
        self.table_pending = SortableTableWidget(headers)
        self.table_pending.set_column_weights([0.04, 0.28, 0.16, 0.14, 0.12, 0.12, 0.14])
        self.table_pending.cellDoubleClicked.connect(self._on_pending_cell_double_clicked)
        self.table_pending.copied_to_clipboard.connect(self._show_clipboard_status)
        self.table_pending.itemChanged.connect(self._on_table_item_changed)
        self.table_pending.bulk_delete_requested.connect(self._handle_bulk_delete)
        self.table_pending.bulk_due_date_requested.connect(self._handle_bulk_due_date)
        self.table_pending.bulk_mark_paid_requested.connect(self._handle_bulk_mark_paid)
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

        # Sütunlar: ✓, Şirket İsmi, Fatura No, Tarih, Vergi Hariç Fiyat, Vergi (KDV Tutarı), Toplam Fiyat (Vergiler Dahil), Son Ödeme Tarihi, Ödenme Durumu, Kalan Gün Sayısı
        headers = [
            "✓",
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
        self.table_all.set_column_weights([0.04, 0.21, 0.12, 0.09, 0.10, 0.09, 0.11, 0.08, 0.08, 0.08])
        self.table_all.cellDoubleClicked.connect(self._on_all_cell_double_clicked)
        self.table_all.copied_to_clipboard.connect(self._show_clipboard_status)
        self.table_all.itemChanged.connect(self._on_table_item_changed)
        self.table_all.bulk_delete_requested.connect(self._handle_bulk_delete)
        self.table_all.bulk_due_date_requested.connect(self._handle_bulk_due_date)
        self.table_all.bulk_mark_paid_requested.connect(self._handle_bulk_mark_paid)
        layout.addWidget(self.table_all)

    # --- SEKME 3: NAKİT FATURALAR VE İŞLEMLER ---
    def _setup_tab_due(self):
        layout = QVBoxLayout(self.tab_due)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        # "Tüm Faturalar" ile birebir aynı Durum Uyarıları Lejantı
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

        # "Tüm Faturalar" ile birebir aynı 10 Sütun Yapısı
        headers = [
            "✓",
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
        self.table_due = SortableTableWidget(headers)
        self.table_due.set_column_weights([0.04, 0.21, 0.12, 0.09, 0.10, 0.09, 0.11, 0.08, 0.08, 0.08])
        self.table_due.cellDoubleClicked.connect(self._on_due_cell_double_clicked)
        self.table_due.copied_to_clipboard.connect(self._show_clipboard_status)
        self.table_due.itemChanged.connect(self._on_table_item_changed)
        self.table_due.bulk_delete_requested.connect(self._handle_bulk_delete)
        self.table_due.bulk_due_date_requested.connect(self._handle_bulk_due_date)
        self.table_due.bulk_mark_paid_requested.connect(self._handle_bulk_mark_paid)
        layout.addWidget(self.table_due)

    # --- SEKME 4: ÖDENMEMİŞ FATURALAR ---
    def _setup_tab_unpaid(self):
        layout = QVBoxLayout(self.tab_unpaid)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        info_lbl = QLabel(
            "ℹ️ Henüz tam ödemesi gerçekleşmemiş (aktif, kısmi ve vadesi bekleyen) tüm faturalar listelenir. Çift tıklayarak işlem yapabilirsiniz."
        )
        info_lbl.setStyleSheet("color: #38BDF8; font-size: 12px; font-weight: 600; margin-bottom: 4px;")
        layout.addWidget(info_lbl)

        # Sütunlar: ✓, Şirket İsmi, Fatura No, Tarih, Vergi Hariç Fiyat, Vergi (KDV Tutarı), Toplam Fiyat (Vergiler Dahil), Son Ödeme Tarihi
        headers = [
            "✓",
            "Şirket İsmi",
            "Fatura No",
            "Fatura Tarihi",
            "Vergi Hariç Fiyat",
            "Vergi (KDV Tutarı)",
            "Toplam Fiyat (Vergiler Dahil)",
            "Son Ödeme Tarihi",
        ]
        self.table_unpaid = SortableTableWidget(headers)
        self.table_unpaid.set_column_weights([0.04, 0.26, 0.15, 0.11, 0.11, 0.10, 0.12, 0.11])
        self.table_unpaid.cellDoubleClicked.connect(self._on_unpaid_cell_double_clicked)
        self.table_unpaid.copied_to_clipboard.connect(self._show_clipboard_status)
        self.table_unpaid.itemChanged.connect(self._on_table_item_changed)
        self.table_unpaid.bulk_delete_requested.connect(self._handle_bulk_delete)
        self.table_unpaid.bulk_due_date_requested.connect(self._handle_bulk_due_date)
        self.table_unpaid.bulk_mark_paid_requested.connect(self._handle_bulk_mark_paid)
        layout.addWidget(self.table_unpaid)

    # --- SEKME 5: ÖDENMİŞ FATURALAR ---
    def _setup_tab_paid(self):
        layout = QVBoxLayout(self.tab_paid)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(10)

        info_lbl = QLabel(
            "ℹ️ Tamamen ödenmiş faturalar listelenir. Üst paneldeki sabit filtreleme alanından tarih ve şirket bazlı filtreleme yapabilirsiniz."
        )
        info_lbl.setStyleSheet("color: #10B981; font-size: 12px; font-weight: 600; margin-bottom: 4px;")
        layout.addWidget(info_lbl)

        # Sütunlar: ✓, Şirket İsmi, Fatura No, Tarih, Vergi Hariç Fiyat, Vergi (KDV Tutarı), Toplam Fiyat (Vergiler Dahil), Ödeme Tarihi
        headers = [
            "✓",
            "Şirket İsmi",
            "Fatura No",
            "Fatura Tarihi",
            "Vergi Hariç Fiyat",
            "Vergi (KDV Tutarı)",
            "Toplam Fiyat (Vergiler Dahil)",
            "Ödeme Tarihi",
        ]
        self.table_paid = SortableTableWidget(headers)
        self.table_paid.set_column_weights([0.04, 0.26, 0.15, 0.11, 0.11, 0.10, 0.12, 0.11])
        self.table_paid.cellDoubleClicked.connect(self._on_paid_cell_double_clicked)
        self.table_paid.copied_to_clipboard.connect(self._show_clipboard_status)
        self.table_paid.itemChanged.connect(self._on_table_item_changed)
        self.table_paid.bulk_delete_requested.connect(self._handle_bulk_delete)
        self.table_paid.bulk_due_date_requested.connect(self._handle_bulk_due_date)
        self.table_paid.bulk_mark_paid_requested.connect(self._handle_bulk_mark_paid)
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
        if hasattr(self, "expense_db"):
            try:
                self.expense_db.reload()
            except Exception as e:
                print(f"[ExpenseDB Reload Hatası] {e}")
        if hasattr(self, "expenses_widget"):
            try:
                self.expenses_widget.refresh_all()
            except Exception as e:
                print(f"[ExpensesWidget Refresh Hatası] {e}")
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
        self._load_tab_unpaid()
        self._load_tab_paid()
        if hasattr(self, "expenses_widget"):
            self.expenses_widget.refresh_all()
        self._apply_current_search_filter()
        self._update_bulk_actions_state()

    def _update_stat_cards(self, displayed_paid_invoices: Optional[List[Dict[str, Any]]] = None):
        """
        Özet Bilgi Paneli Güncellemesi:
        Yalnızca dinamik hesaplama yapan 'Filtrelenen Toplam' alanı ve durum sayaçları güncellenir.
        Genel Toplam alanı tamamen kaldırılmıştır.
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
        tab_idx = self.tabs.currentIndex() if hasattr(self, "tabs") else 0
        all_db_invoices = self.db.load_all()
        total_db_count = len(all_db_invoices)

        if tab_idx == 4:  # Ödenmiş Faturalar
            list_name = "Ödenmiş Faturalar"
            table = getattr(self, "table_paid", None)
        elif tab_idx == 3:  # Ödenmemiş Faturalar
            list_name = "Ödenmemiş Faturalar"
            table = getattr(self, "table_unpaid", None)
        elif tab_idx == 2:  # Nakit
            list_name = "Nakit"
            table = getattr(self, "table_due", None)
        elif tab_idx == 1:  # Tüm Faturalar
            list_name = "Tüm Faturalar"
            table = getattr(self, "table_all", None)
        else:  # Düzenlenecek Faturalar
            list_name = "Düzenlenecek Faturalar"
            table = getattr(self, "table_pending", None)

        # FİLTRELENEN TOPLAM ALANI HESAPLAMASI (Dinamik - Yalnızca bu alan mevcuttur)
        fil_tax_excluded = 0.0
        fil_kdv = 0.0
        fil_total = 0.0
        visible_count = 0

        if table is not None and table.rowCount() > 0:
            for row in range(table.rowCount()):
                if not table.isRowHidden(row):
                    visible_count += 1
                    # Sütun 4: Vergi Hariç Fiyat
                    item_tax = table.item(row, 4)
                    if item_tax and hasattr(item_tax, "numeric_value"):
                        fil_tax_excluded += item_tax.numeric_value
                    # Sütun 5: Vergi (KDV Tutarı)
                    item_kdv = table.item(row, 5)
                    if item_kdv and hasattr(item_kdv, "numeric_value"):
                        fil_kdv += item_kdv.numeric_value
                    # Sütun 6: Toplam Fiyat (Vergiler Dahil)
                    item_tot = table.item(row, 6)
                    if item_tot and hasattr(item_tot, "numeric_value"):
                        fil_total += item_tot.numeric_value
        elif displayed_paid_invoices is not None and (table is None or table.rowCount() == 0) and tab_idx < 5:
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
        fil_count_text = f"Toplam Adet: {visible_count}"
        if hasattr(self, "card_fil_count"):
            self.card_fil_count.set_value(fil_count_text)
        if hasattr(self, "lbl_fil_adet"):
            self.lbl_fil_adet.setText(fil_count_text)
        if hasattr(self, "lbl_fil_count"):
            if tab_idx == 5:
                self.lbl_fil_count.setText("(Gider Yönetimi ve Gelir - Gider Özeti Görüntüleniyor)")
            else:
                self.lbl_fil_count.setText(f"(Sistemdeki toplam {total_db_count} fatura içinden {visible_count} adet fatura listeleniyor)")

    def _load_tab_pending(self):
        invoices = self.db.get_pending_invoices()
        self.table_pending.setSortingEnabled(False)
        self.table_pending.clearSelection()
        self.table_pending.clearContents()
        self.table_pending.setRowCount(len(invoices))

        for row, inv in enumerate(invoices):
            inv_id = str(inv.get("id") or inv.get("invoice_number", ""))

            # 0: Onay Kutusu (Checkbox)
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            chk_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            chk_item.setData(Qt.ItemDataRole.UserRole + 2, "normal")
            self.table_pending.setItem(row, 0, chk_item)

            # 1: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, "normal")
            self.table_pending.setItem(row, 1, c_item)

            # 2: Fatura No
            f_item = QTableWidgetItem(str(inv.get("invoice_number", "")))
            self.table_pending.setItem(row, 2, f_item)

            # 3: Fatura Kesim Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_pending.setItem(row, 3, d_item)

            cur = str(inv.get("currency", "TL"))

            # 4: Vergi Hariç Fiyat
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_pending.setItem(row, 4, tax_item)

            # 5: Vergi (KDV Tutarı)
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_pending.setItem(row, 5, kdv_item)

            # 6: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else (tax_ex + kdv)
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_pending.setItem(row, 6, tot_item)

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

            # UYARI VE SATIR RENKLENDİRMESİ:
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

            # 0: Onay Kutusu (Checkbox)
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            chk_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            chk_item.setData(Qt.ItemDataRole.UserRole + 2, status_type)
            self.table_all.setItem(row, 0, chk_item)

            # 1: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, status_type)
            self.table_all.setItem(row, 1, c_item)

            # 2: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_all.setItem(row, 2, f_item)

            # 3: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_all.setItem(row, 3, d_item)

            # 4: Vergi Hariç Fiyat
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_all.setItem(row, 4, tax_item)

            # 5: Vergi (KDV Tutarı)
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_all.setItem(row, 5, kdv_item)

            # 6: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else (tax_ex + kdv)
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_all.setItem(row, 6, tot_item)

            # 7: Son Ödeme Tarihi
            due_item = DateTableWidgetItem(due_date)
            self.table_all.setItem(row, 7, due_item)

            # 8: Ödenme Durumu
            if status in ["paid", "ödendi", "odendi"]:
                status_text = "✓ Ödendi"
            elif status == "partial":
                paid_amt = float(inv.get("paid_amount") or 0.0)
                status_text = f"⏳ Kısmi Ödendi ({paid_amt:,.2f} {cur})"
            else:
                status_text = "Ödenmedi"

            s_item = QTableWidgetItem(status_text)
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_all.setItem(row, 8, s_item)

            # 9: Kalan Gün Sayısı
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

            self.table_all.setItem(row, 9, kalan_item)

        self.table_all.setSortingEnabled(True)
        # Sütun ve Ekran Optimizasyonu
        self.table_all.auto_fit_columns()

    def _load_tab_due(self):
        invoices = self.db.get_cash_invoices()
        self.table_due.setSortingEnabled(False)
        self.table_due.clearSelection()
        self.table_due.clearContents()
        self.table_due.setRowCount(len(invoices))

        for row, inv in enumerate(invoices):
            inv_id = str(inv.get("id") or inv.get("invoice_number", ""))
            inv_no = str(inv.get("invoice_number", ""))
            status = str(inv.get("status", "active")).lower()
            due_date = inv.get("due_date") or inv.get("payment_date") or inv.get("invoice_date")
            days_left = holiday_service.get_days_remaining(due_date)
            cur = str(inv.get("currency", "TL"))

            # UYARI VE SATIR RENKLENDİRMESİ ("Tüm Faturalar" ile birebir aynı kural ve mantık):
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

            # 0: Onay Kutusu (Checkbox)
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            chk_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            chk_item.setData(Qt.ItemDataRole.UserRole + 2, status_type)
            self.table_due.setItem(row, 0, chk_item)

            # 1: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, status_type)
            self.table_due.setItem(row, 1, c_item)

            # 2: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_due.setItem(row, 2, f_item)

            # 3: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_due.setItem(row, 3, d_item)

            # 4: Vergi Hariç Fiyat
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_due.setItem(row, 4, tax_item)

            # 5: Vergi (KDV Tutarı)
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_due.setItem(row, 5, kdv_item)

            # 6: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else (tax_ex + kdv)
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_due.setItem(row, 6, tot_item)

            # 7: Son Ödeme Tarihi
            due_item = DateTableWidgetItem(due_date)
            self.table_due.setItem(row, 7, due_item)

            # 8: Ödenme Durumu
            if status in ["paid", "ödendi", "odendi"]:
                status_text = "✓ Ödendi"
            elif status == "partial":
                paid_amt = float(inv.get("paid_amount") or 0.0)
                status_text = f"⏳ Kısmi Ödendi ({paid_amt:,.2f} {cur})"
            else:
                status_text = "Ödenmedi"

            s_item = QTableWidgetItem(status_text)
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_due.setItem(row, 8, s_item)

            # 9: Kalan Gün Sayısı
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

            self.table_due.setItem(row, 9, kalan_item)

        self.table_due.setSortingEnabled(True)
        # Sütun ve Ekran Optimizasyonu
        self.table_due.auto_fit_columns()

    def _load_tab_unpaid(self):
        invoices = self.db.get_unpaid_invoices()
        self.table_unpaid.setSortingEnabled(False)
        self.table_unpaid.clearSelection()
        self.table_unpaid.clearContents()
        self.table_unpaid.setRowCount(len(invoices))

        for row, inv in enumerate(invoices):
            inv_id = str(inv.get("id") or inv.get("invoice_number", ""))
            inv_no = str(inv.get("invoice_number", ""))
            cur = str(inv.get("currency", "TL"))
            status = str(inv.get("status", "")).lower()

            due_date = inv.get("due_date")
            days_left = holiday_service.get_days_remaining(due_date)

            if status == "partial":
                status_type = "partial"
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

            # 0: Onay Kutusu (Checkbox)
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            chk_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            chk_item.setData(Qt.ItemDataRole.UserRole + 2, status_type)
            self.table_unpaid.setItem(row, 0, chk_item)

            # 1: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, status_type)
            self.table_unpaid.setItem(row, 1, c_item)

            # 2: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_unpaid.setItem(row, 2, f_item)

            # 3: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_unpaid.setItem(row, 3, d_item)

            # 4: Vergi Hariç Fiyat
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_unpaid.setItem(row, 4, tax_item)

            # 5: Vergi (KDV Tutarı)
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_unpaid.setItem(row, 5, kdv_item)

            # 6: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else (tax_ex + kdv)
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_unpaid.setItem(row, 6, tot_item)

            # 7: Son Ödeme Tarihi
            due_item = DateTableWidgetItem(inv.get("due_date"))
            self.table_unpaid.setItem(row, 7, due_item)

        self.table_unpaid.setSortingEnabled(True)
        self.table_unpaid.auto_fit_columns()

    @pyqtSlot()
    def _on_filter_paid_clicked(self):
        """
        Filtrele butonu doğrudan tıklama / komut tetikleyicisi.
        Tarih aralığı, tür ve arama filtrelerini aktif sekme üzerinde uygular.
        İşlem tamamlandığında paneli otomatik olarak kapatır (collapse).
        """
        print("\n" + "=" * 55)
        print("[Filtrele Butonu] Butona tıklandı (Filtreler aktif sekme üzerinde uygulanıyor).")
        self.date_filter_active = True
        self._apply_all_filters(show_all_dates=False)
        self._toggle_filter_panel(force_close=True)

    def _load_tab_paid(self, show_all: bool = False):
        """
        Sekme 4: Ödenmiş Faturalar.
        - Veritabanındaki tüm ödenmiş faturaları tabloya yükler.
        - Filtreleme işlemi _apply_all_filters() üzerinden dinamik yürütülür.
        """
        try:
            invoices = self.db.get_paid_invoices()
        except Exception as e:
            print(f"[Tablo Yükleme Hatası] Ödenmiş faturalar yüklenirken hata: {e}")
            invoices = []

        self.table_paid.setSortingEnabled(False)
        self.table_paid.clearSelection()
        self.table_paid.clearContents()
        self.table_paid.setRowCount(len(invoices))

        for row, inv in enumerate(invoices):
            inv_id = str(inv.get("id") or inv.get("invoice_number", ""))
            inv_no = str(inv.get("invoice_number", ""))
            cur = str(inv.get("currency", "TL"))

            # 0: Onay Kutusu (Checkbox)
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            chk_item.setCheckState(Qt.CheckState.Unchecked)
            chk_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            chk_item.setData(Qt.ItemDataRole.UserRole + 2, "paid")
            self.table_paid.setItem(row, 0, chk_item)

            # 1: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_id)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, "paid")
            self.table_paid.setItem(row, 1, c_item)

            # 2: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_paid.setItem(row, 2, f_item)

            # 3: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_paid.setItem(row, 3, d_item)

            # 4: Vergi Hariç Fiyat
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_paid.setItem(row, 4, tax_item)

            # 5: Vergi (KDV Tutarı)
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_paid.setItem(row, 5, kdv_item)

            # 6: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else (tax_ex + kdv)
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_paid.setItem(row, 6, tot_item)

            # 7: Ödeme Tarihi
            pay_date = inv.get("payment_date") or inv.get("invoice_date")
            p_item = DateTableWidgetItem(pay_date)
            self.table_paid.setItem(row, 7, p_item)

        self.table_paid.setSortingEnabled(True)
        self.table_paid.auto_fit_columns()

        # Filtreleri uygula ve özet panellerini güncelle
        self._apply_all_filters(show_all_dates=show_all)

    def _reset_paid_filter(self):
        """
        Filtre İzolasyonu (State Retention):
        Tümünü Göster işlemi yalnızca tarih filtresini kaldırır,
        DatePicker bileşenlerinin içindeki mevcut başlangıç ve bitiş tarihi değerleri
        KESİNLİKLE temizlenmez veya değiştirilmez!
        İşlem tamamlandığında paneli otomatik olarak kapatır (collapse).
        """
        print("\n" + "=" * 55)
        print("[Tümünü Göster Butonu] DatePicker değerleri KORUNARAK tüm faturalar listeleniyor...")
        self.date_filter_active = False
        self._apply_all_filters(show_all_dates=True)
        self._toggle_filter_panel(force_close=True)

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
        if col == 0:
            return
        item = self.table_pending.item(row, 0) or self.table_pending.item(row, 1)
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
        if col == 0:
            return
        item = self.table_all.item(row, 0) or self.table_all.item(row, 1)
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
        if col == 0:
            return
        item = self.table_due.item(row, 0) or self.table_due.item(row, 1)
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

    def _on_unpaid_cell_double_clicked(self, row: int, col: int):
        """Sekme 4 Çift Tıklama: Ödenmemiş faturayı ödeme / parçalı ödeme / detay düzenleme."""
        if col == 0:
            return
        item = self.table_unpaid.item(row, 0) or self.table_unpaid.item(row, 1)
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
        """Sekme 5 Çift Tıklama: Ödenmiş faturayı düzeltme imkanı."""
        if col == 0:
            return
        item = self.table_paid.item(row, 0) or self.table_paid.item(row, 1)
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

    # --- ARAMA VE ÇOK KRİTERLİ FİLTRELEME (SEARCH, CASH & DATE FILTERS) ---
    def _on_search_text_changed(self, text: str):
        self._apply_all_filters()

    def _on_tab_changed(self, index: int):
        self._apply_all_filters()
        self._update_bulk_actions_state()

    def _apply_current_search_filter(self):
        """Geriye dönük uyumluluk çağrısı: Çok kriterli filtreyi aktif sekmeye uygular."""
        self._apply_all_filters()

    def _apply_all_filters(self, show_all_dates: bool = False):
        """
        Gelişmiş Çok Kriterli Filtreleme Fonksiyonu:
        1. Arama Metni: Şirket İsmi (Sütun 1) veya Fatura No (Sütun 2) canlı arama eşleşmesi.
        2. Nakit / Fatura Türü Filtresi (combo_cash_type):
           - 'Hepsi': Tüm kayıtlar gösterilir.
           - 'Nakit Dışı (Sadece Faturalar)': Fatura No kısmında 'Nakit' yazan veya
             nakit işlemi (NAKIT_...) olarak kayıtlı olanlar listeden çıkarılır.
        3. Tarih Türü ve Aralığı Filtresi (combo_date_type):
           - 'Fatura Kesim Tarihi': Sütun 3 (Fatura Tarihi) baz alınır.
           - 'Son Ödeme (Vade/Ödenme) Tarihi': Aktif sekmeye göre ilgili sütun baz alınır.
             (Tüm/Vadesi Gelmiş/Ödenmemiş sekmelerinde Sütun 7: Son Ödeme Tarihi,
              Ödenmiş sekmesinde Sütun 7: Ödeme Tarihi).
        show_all_dates=True ise veya tarih filtresi aktif değilse tarih kriteri uygulanmaz
        ancak DatePicker değerleri korunur.
        """
        if show_all_dates:
            self.date_filter_active = False

        current_tab_idx = self.tabs.currentIndex() if hasattr(self, "tabs") else 0
        tables = [
            getattr(self, "table_pending", None),
            getattr(self, "table_all", None),
            getattr(self, "table_due", None),
            getattr(self, "table_unpaid", None),
            getattr(self, "table_paid", None),
        ]
        if not (0 <= current_tab_idx < len(tables)):
            return
        table = tables[current_tab_idx]
        if table is None:
            return

        query = self.search_bar.text().strip().lower() if hasattr(self, "search_bar") else ""
        cash_filter_mode = self.combo_cash_type.currentText().strip() if hasattr(self, "combo_cash_type") else "Hepsi"
        hide_cash = (cash_filter_mode == "Nakit Dışı (Sadece Faturalar)")

        # Tarih filtresi parametreleri
        date_filter_on = getattr(self, "date_filter_active", False) and not show_all_dates
        start_dt = None
        end_dt = None
        target_date_col = None

        if date_filter_on:
            if hasattr(self, "date_from") and self.date_from:
                self.date_from.interpretText()
            if hasattr(self, "date_to") and self.date_to:
                self.date_to.interpretText()

            start_qdate = self.date_from.date() if hasattr(self, "date_from") else None
            end_qdate = self.date_to.date() if hasattr(self, "date_to") else None

            if start_qdate and end_qdate:
                start_dt = datetime(start_qdate.year(), start_qdate.month(), start_qdate.day()).date()
                end_dt = datetime(end_qdate.year(), end_qdate.month(), end_qdate.day()).date()
                if start_dt > end_dt:
                    start_dt, end_dt = end_dt, start_dt

            date_type_text = self.combo_date_type.currentText().strip() if hasattr(self, "combo_date_type") else "Fatura Kesim Tarihi"
            if date_type_text == "Fatura Kesim Tarihi":
                # Tüm sekmelerde Sütun 3 Fatura Kesim Tarihidir
                target_date_col = 3
            else:
                # Son Ödeme (Vade/Ödenme) Tarihi:
                # Sütun 7 (table_all, table_due, table_unpaid için Son Ödeme Tarihi, table_paid için Ödeme Tarihi)
                if table.columnCount() > 7:
                    target_date_col = 7
                else:
                    # Tablo 0 (table_pending) henüz vadesi olmadığı için Sütun 7 içermez
                    target_date_col = -1

        visible_count = 0
        table_row_count = table.rowCount()

        for row in range(table_row_count):
            # 1. Arama Metni Kontrolü (Sütun 1: Şirket, Sütun 2: Fatura No)
            match_text = True
            if query:
                c_item = table.item(row, 1)
                f_item = table.item(row, 2)
                c_str = c_item.text().lower() if c_item else ""
                f_str = f_item.text().lower() if f_item else ""
                match_text = (query in c_str or query in f_str)

            if not match_text:
                table.setRowHidden(row, True)
                continue

            # 2. Nakit / Fatura Türü Kontrolü
            match_cash = True
            if hide_cash:
                f_item = table.item(row, 2)
                chk_item = table.item(row, 0)
                inv_no_val = f_item.text().strip().lower() if f_item else ""
                inv_id_val = str(chk_item.data(Qt.ItemDataRole.UserRole) or "").strip().lower() if chk_item else ""
                if "nakit" in inv_no_val or inv_no_val.startswith("nakit_") or inv_id_val.startswith("nakit_"):
                    match_cash = False

            if not match_cash:
                table.setRowHidden(row, True)
                continue

            # 3. Tarih Aralığı Kontrolü
            match_date = True
            if date_filter_on and start_dt and end_dt:
                if target_date_col == -1 or target_date_col is None:
                    # Sekmede vade tarihi bulunmuyor (örneğin Düzenlenecek Sekmesi)
                    match_date = False
                else:
                    date_item = table.item(row, target_date_col)
                    row_dt = None
                    if date_item:
                        if hasattr(date_item, "timestamp") and date_item.timestamp > 0:
                            row_dt = datetime.fromtimestamp(date_item.timestamp).date()
                        else:
                            raw_t = date_item.text().strip()
                            if raw_t and raw_t != "-":
                                parsed = parse_date_obj(raw_t)
                                if parsed:
                                    row_dt = parsed.date() if isinstance(parsed, datetime) else parsed

                    if row_dt is not None:
                        match_date = (start_dt <= row_dt <= end_dt)
                    else:
                        match_date = False

            if not match_date:
                table.setRowHidden(row, True)
                continue

            # Tüm kriterleri sağlayan satır görünür kalır
            table.setRowHidden(row, False)
            visible_count += 1

        # Dinamik özet panelini (Filtrelenen Toplam ve Adet) anlık güncelle
        self._update_stat_cards()
        self._update_filter_button_state()

        # Durum çubuğunu güncelle
        tab_names = [
            "Düzenlenecek Faturalar",
            "Tüm Faturalar",
            "Nakit",
            "Ödenmemiş Faturalar",
            "Ödenmiş Faturalar",
        ]
        if hasattr(self, "status_bar") and self.status_bar and 0 <= current_tab_idx < len(tab_names):
            filter_details = []
            if query:
                filter_details.append(f"Arama: '{query}'")
            if hide_cash:
                filter_details.append("Nakit Dışı (Sadece Faturalar)")
            if date_filter_on and start_dt and end_dt:
                dt_col_name = "Fatura Kesim" if target_date_col == 3 else "Son Ödeme/Vade"
                filter_details.append(f"{dt_col_name}: {start_dt.strftime('%d.%m.%Y')} - {end_dt.strftime('%d.%m.%Y')}")

            detail_str = f" ({', '.join(filter_details)})" if filter_details else ""
            self.status_bar.showMessage(f"{tab_names[current_tab_idx]}: {visible_count} adet fatura listelendi{detail_str}.", 4000)

    # --- SÜRÜM KONTROL VE GÜNCELLEME SİSTEMİ (VERSION CHECK & AUTO-UPDATE) ---
    def check_for_updates(self, manual: bool = False):
        """GitHub API üzerinden en son yayınlanan Release sürümünü kontrol eder (APK-STU altyapısı)."""
        self.updater.check_for_updates(silent_if_latest=not manual)

    def _manual_check_for_updates(self):
        """Kullanıcı 'Güncellemeleri Kontrol Et' butonuna bastığında çalışan tetikleyici."""
        self.updater.check_for_updates(silent_if_latest=False)

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

