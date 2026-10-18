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
from src.dialogs import OdemeGirisDialog, VadeGirisDialog
from src.file_watcher import WatcherService
from src.holiday_service import holiday_service
from src.pdf_extractor import pdf_extractor
from src.styles import COLORS, MAIN_STYLE_SHEET
from src.updater import (
    DownloadProgressDialog,
    UpdateCheckWorker,
    UpdatePromptDialog,
    apply_update_and_restart,
)

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

        self._setup_ui()
        self._setup_watcher()
        self.refresh_all_tabs()

        # Uygulama açılışında arka planda sessiz güncelleme kontrolü
        QTimer.singleShot(2000, lambda: self.check_for_updates(manual=False))

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

        self.watch_status_lbl = QLabel("● Klasör İzleniyor (TasımaFaturaları)")
        self.watch_status_lbl.setStyleSheet("font-size: 11px; color: #10B981; font-weight: 600;")
        title_box.addWidget(app_title)
        title_box.addWidget(self.watch_status_lbl)
        layout.addLayout(title_box)

        layout.addStretch()

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
        self.btn_check_update.clicked.connect(lambda: self.check_for_updates(manual=True))
        layout.addWidget(self.btn_check_update)

        return frame

    def _create_stats_bar(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.card_pending = StatCard("DÜZENLENECEK (EKSİK VADE)", "0", "#F97316")
        self.card_all_active = StatCard("AKTİF / BEKLEYEN", "0", "#60A5FA")
        self.card_due_urgent = StatCard("VADESİ GELMİŞ / GEÇMİŞ", "0", "#EF4444")
        self.card_total_amount = StatCard("TOPLAM FİYAT (VERGİLER DAHİL)", "0.00 TL", "#10B981")
        self.card_total_tax_excluded = StatCard("TOPLAM KDV HARİÇ", "0.00 TL", "#38BDF8")
        self.card_total_kdv = StatCard("TOPLAM KDV", "0.00 TL", "#F59E0B")

        layout.addWidget(self.card_pending)
        layout.addWidget(self.card_all_active)
        layout.addWidget(self.card_due_urgent)
        layout.addWidget(self.card_total_amount)
        layout.addWidget(self.card_total_tax_excluded)
        layout.addWidget(self.card_total_kdv)

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

        # Sütunlar: Şirket İsmi, Fatura No, Tarih, Toplam Fiyat (Vergiler Dahil), Vergi Hariç Tutar, KDV Tutarı
        headers = [
            "Şirket İsmi",
            "Fatura No",
            "Fatura Kesim Tarihi",
            "Toplam Fiyat (Vergiler Dahil)",
            "Vergi Hariç Tutar",
            "KDV Tutarı",
        ]
        self.table_pending = SortableTableWidget(headers)
        self.table_pending.set_column_weights([0.30, 0.16, 0.14, 0.14, 0.13, 0.13])
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
        l_paid = QLabel("● Ödenmiş (Yeşil)")
        l_paid.setStyleSheet("color: #10B981; font-weight: bold; font-size: 12px;")

        legend_layout.addWidget(l_white)
        legend_layout.addWidget(l_yellow)
        legend_layout.addWidget(l_orange)
        legend_layout.addWidget(l_red)
        legend_layout.addWidget(l_paid)
        legend_layout.addStretch()

        layout.addLayout(legend_layout)

        # Sütunlar: Şirket İsmi, Fatura No, Tarih, Toplam Fiyat (Vergiler Dahil), Vergi Hariç Tutar, KDV Tutarı, Son Ödeme Tarihi, Ödenme Durumu, Kalan Gün Sayısı
        headers = [
            "Şirket İsmi",
            "Fatura No",
            "Fatura Tarihi",
            "Toplam Fiyat (Vergiler Dahil)",
            "Vergi Hariç Tutar",
            "KDV Tutarı",
            "Son Ödeme Tarihi",
            "Ödenme Durumu",
            "Kalan Gün Sayısı",
        ]
        self.table_all = SortableTableWidget(headers)
        self.table_all.set_column_weights([0.22, 0.13, 0.09, 0.12, 0.11, 0.09, 0.09, 0.07, 0.08])
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

        # Sütunlar: Şirket İsmi, Fatura No, Tarih, Toplam Fiyat (Vergiler Dahil), Vergi Hariç Tutar, KDV Tutarı, Son Ödeme Tarihi
        headers = [
            "Şirket İsmi",
            "Fatura No",
            "Fatura Tarihi",
            "Toplam Fiyat (Vergiler Dahil)",
            "Vergi Hariç Tutar",
            "KDV Tutarı",
            "Son Ödeme Tarihi",
        ]
        self.table_due = SortableTableWidget(headers)
        self.table_due.set_column_weights([0.28, 0.15, 0.11, 0.13, 0.12, 0.10, 0.11])
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

        # Sütunlar: Şirket İsmi, Fatura No, Tarih, Toplam Fiyat (Vergiler Dahil), Vergi Hariç Tutar, KDV Tutarı, Ödeme Tarihi
        headers = [
            "Şirket İsmi",
            "Fatura No",
            "Fatura Tarihi",
            "Toplam Fiyat (Vergiler Dahil)",
            "Vergi Hariç Tutar",
            "KDV Tutarı",
            "Ödeme Tarihi",
        ]
        self.table_paid = SortableTableWidget(headers)
        self.table_paid.set_column_weights([0.28, 0.15, 0.11, 0.13, 0.12, 0.10, 0.11])
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
        Dinamik Toplam Hesaplama (Özet Panel):
        Ödenmiş faturalar sekmesinde bir tarih filtrelemesi uygulandığında veya
        sayfa güncellendiğinde 'Toplam Fiyat (Vergiler Dahil)', 'Toplam KDV Hariç' ve 'Toplam KDV'
        yalnızca filtrelenmiş listedeki faturaların toplamlarını anlık olarak gösterir.
        """
        pending_count = len(self.db.get_pending_invoices())
        all_complete = self.db.get_all_complete_invoices()
        active_count = len([i for i in all_complete if i.get("status") != "paid"])
        due_count = len(self.db.get_due_invoices())

        if displayed_paid_invoices is not None:
            paid_invoices = displayed_paid_invoices
        else:
            paid_invoices = self.db.get_paid_invoices()

        total_price = sum(
            float(
                i.get("total_amount")
                if i.get("total_amount") is not None
                else ((i.get("tax_excluded_amount") or 0.0) + (i.get("kdv_amount") or 0.0))
            )
            for i in paid_invoices
        )
        total_tax_excluded = sum(float(i.get("tax_excluded_amount") or 0.0) for i in paid_invoices)
        total_kdv = sum(float(i.get("kdv_amount") or 0.0) for i in paid_invoices)

        self.card_pending.set_value(str(pending_count))
        self.card_all_active.set_value(str(active_count))
        self.card_due_urgent.set_value(str(due_count))
        self.card_total_amount.set_value(f"{total_price:,.2f} TL")
        self.card_total_tax_excluded.set_value(f"{total_tax_excluded:,.2f} TL")
        self.card_total_kdv.set_value(f"{total_kdv:,.2f} TL")

    def _load_tab_pending(self):
        invoices = self.db.get_pending_invoices()
        self.table_pending.setSortingEnabled(False)
        self.table_pending.clearSelection()
        self.table_pending.clearContents()
        self.table_pending.setRowCount(len(invoices))

        for row, inv in enumerate(invoices):
            # 0: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv.get("invoice_number"))
            c_item.setData(Qt.ItemDataRole.UserRole + 2, "normal")
            self.table_pending.setItem(row, 0, c_item)

            # 1: Fatura No
            f_item = QTableWidgetItem(str(inv.get("invoice_number", "")))
            self.table_pending.setItem(row, 1, f_item)

            # 2: Fatura Kesim Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_pending.setItem(row, 2, d_item)

            cur = str(inv.get("currency", "TL"))

            # 3: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else ((inv.get("tax_excluded_amount") or 0.0) + (inv.get("kdv_amount") or 0.0))
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_pending.setItem(row, 3, tot_item)

            # 4: Vergi Hariç Tutar
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_pending.setItem(row, 4, tax_item)

            # 5: KDV Tutarı
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_pending.setItem(row, 5, kdv_item)

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
            inv_no = str(inv.get("invoice_number", ""))
            status = str(inv.get("status", "active"))
            due_date = inv.get("due_date")
            days_left = holiday_service.get_days_remaining(due_date)
            cur = str(inv.get("currency", "TL"))

            # 0: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_no)
            self.table_all.setItem(row, 0, c_item)

            # 1: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_all.setItem(row, 1, f_item)

            # 2: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_all.setItem(row, 2, d_item)

            # 3: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else ((inv.get("tax_excluded_amount") or 0.0) + (inv.get("kdv_amount") or 0.0))
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_all.setItem(row, 3, tot_item)

            # 4: Vergi Hariç Tutar
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_all.setItem(row, 4, tax_item)

            # 5: KDV Tutarı
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_all.setItem(row, 5, kdv_item)

            # 6: Son Ödeme Tarihi
            due_item = DateTableWidgetItem(due_date)
            self.table_all.setItem(row, 6, due_item)

            # 7: Ödenme Durumu
            status_text = "✓ Ödendi" if status == "paid" else "Ödenmedi"
            s_item = QTableWidgetItem(status_text)
            s_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_all.setItem(row, 7, s_item)

            # 8: Kalan Gün Sayısı
            if status == "paid":
                kalan_item = QTableWidgetItem("Tamamlandı")
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
            # 1. Vadesine 2 günden fazla süre olan faturalar -> BEYAZ zemin
            # 2. Vadesine 2 gün kalanlar -> SARI
            # 3. Vadesine 1 gün kalanlar -> TURUNCU
            # 4. Vadesi gelmiş/geçmiş olanlar -> KIRMIZI
            # 5. Ödenmiş faturalar -> YEŞİL
            status_type = "normal"

            if status != "paid" and days_left is not None:
                if days_left <= 0:
                    status_type = "red"
                elif days_left == 1:
                    status_type = "orange"
                elif days_left == 2:
                    status_type = "yellow"
                else:
                    status_type = "normal"
            elif status == "paid":
                status_type = "paid"
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
            inv_no = str(inv.get("invoice_number", ""))
            cur = str(inv.get("currency", "TL"))

            # 0: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_no)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, "red")
            self.table_due.setItem(row, 0, c_item)

            # 1: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_due.setItem(row, 1, f_item)

            # 2: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_due.setItem(row, 2, d_item)

            # 3: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else ((inv.get("tax_excluded_amount") or 0.0) + (inv.get("kdv_amount") or 0.0))
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_due.setItem(row, 3, tot_item)

            # 4: Vergi Hariç Tutar
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_due.setItem(row, 4, tax_item)

            # 5: KDV Tutarı
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_due.setItem(row, 5, kdv_item)

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
            inv_no = str(inv.get("invoice_number", ""))
            cur = str(inv.get("currency", "TL"))

            # 0: Şirket İsmi
            c_item = QTableWidgetItem(str(inv.get("company_name", "")))
            c_item.setData(Qt.ItemDataRole.UserRole, inv_no)
            c_item.setData(Qt.ItemDataRole.UserRole + 2, "paid")
            self.table_paid.setItem(row, 0, c_item)

            # 1: Fatura No
            f_item = QTableWidgetItem(inv_no)
            self.table_paid.setItem(row, 1, f_item)

            # 2: Fatura Tarihi
            d_item = DateTableWidgetItem(inv.get("invoice_date"))
            self.table_paid.setItem(row, 2, d_item)

            # 3: Toplam Fiyat (Vergiler Dahil)
            tot_amt = float(
                inv.get("total_amount")
                if inv.get("total_amount") is not None
                else ((inv.get("tax_excluded_amount") or 0.0) + (inv.get("kdv_amount") or 0.0))
            )
            tot_item = NumericTableWidgetItem(tot_amt, f"{tot_amt:,.2f} {cur}")
            self.table_paid.setItem(row, 3, tot_item)

            # 4: Vergi Hariç Tutar
            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
            tax_item = NumericTableWidgetItem(tax_ex, f"{tax_ex:,.2f} {cur}")
            self.table_paid.setItem(row, 4, tax_item)

            # 5: KDV Tutarı
            kdv = float(inv.get("kdv_amount") or 0.0)
            kdv_item = NumericTableWidgetItem(kdv, f"{kdv:,.2f} {cur}")
            self.table_paid.setItem(row, 5, kdv_item)

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
        inv_no = str(invoice.get("invoice_number", "")).strip()
        file_path = invoice.get("file_path")
        file_name = invoice.get("file_name") or (f"{inv_no}.pdf" if inv_no else "fatura.pdf")

        # PDF'in bulunduğu dizini güvenle belirle
        if file_path and os.path.exists(file_path):
            source_dir = os.path.dirname(os.path.abspath(file_path))
            actual_src_file = os.path.abspath(file_path)
        else:
            source_dir = os.path.abspath(self.watcher.watch_dir)
            actual_src_file = os.path.join(source_dir, file_name)

        silinenler_dir = os.path.join(source_dir, "Silinenler")
        os.makedirs(silinenler_dir, exist_ok=True)
        dest_path = os.path.join(silinenler_dir, os.path.basename(actual_src_file))

        try:
            if os.path.exists(actual_src_file):
                # Hedef dizinde aynı isimde dosya varsa üzerine yazabilmek için kaldır
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except Exception:
                        pass
                shutil.move(actual_src_file, dest_path)
                print(f"[Fatura Silme] Dosya taşındı: {actual_src_file} -> {dest_path}")
            else:
                print(f"[Fatura Silme] Uyarı: PDF dosyası diskte bulunamadı ({actual_src_file}), doğrudan veritabanından siliniyor.")
        except Exception as e:
            print(f"[Fatura Silme Hatası] Dosya taşınırken hata oluştu: {e}")

        # infos.json dosyasından tamamen sil
        self.db.delete_invoice(inv_no)

        # Tabloları ve istatistik panelini yeniden yükle
        self.refresh_all_tabs()
        self.status_bar.showMessage(f"'{inv_no}' faturası silindi ve 'Silinenler' klasörüne taşındı.", 5000)

    # --- ETKİLEŞİMLER (ÇİFT TIKLAMA) ---

    def _on_pending_cell_double_clicked(self, row: int, col: int):
        """Sekme 1 Çift Tıklama: Vade / İş Günü Belirleme Pop-up'ı."""
        item = self.table_pending.item(row, 0)
        if not item:
            return
        inv_no = item.data(Qt.ItemDataRole.UserRole)
        invoice = self.db.get_invoice(inv_no)
        if not invoice:
            return

        dialog = VadeGirisDialog(invoice, self)
        if dialog.exec():
            if getattr(dialog, "delete_requested", False):
                self._delete_and_archive_invoice(invoice)
                return
            res = dialog.get_result()
            # infos.json dosyasına kaydet
            self.db.update_invoice(inv_no, res)
            # Fatura bu sekmeden silinip Tüm Faturalar sekmesine geçer
            self.refresh_all_tabs()
            self.status_bar.showMessage(
                f"{inv_no} faturasına {res['work_days_added']} iş günü vade eklendi ve 'Tüm Faturalar' sekmesine aktarıldı.",
                5000,
            )

    def _on_all_cell_double_clicked(self, row: int, col: int):
        """Sekme 2 Çift Tıklama: Ödendi statüsüne alma veya düzeltme Pop-up'ı."""
        item = self.table_all.item(row, 0)
        if not item:
            return
        inv_no = item.data(Qt.ItemDataRole.UserRole)
        invoice = self.db.get_invoice(inv_no)
        if not invoice:
            return

        dialog = OdemeGirisDialog(invoice, self)
        if dialog.exec():
            if getattr(dialog, "delete_requested", False):
                self._delete_and_archive_invoice(invoice)
                return
            res = dialog.get_result()
            self.db.update_invoice(inv_no, res)
            self.refresh_all_tabs()
            self.status_bar.showMessage(f"{inv_no} fatura durumu güncellendi.", 4000)

    def _on_due_cell_double_clicked(self, row: int, col: int):
        """Sekme 3 Çift Tıklama: Vadesi gelmiş faturayı ödeme yapma."""
        item = self.table_due.item(row, 0)
        if not item:
            return
        inv_no = item.data(Qt.ItemDataRole.UserRole)
        invoice = self.db.get_invoice(inv_no)
        if not invoice:
            return

        dialog = OdemeGirisDialog(invoice, self)
        if dialog.exec():
            if getattr(dialog, "delete_requested", False):
                self._delete_and_archive_invoice(invoice)
                return
            res = dialog.get_result()
            self.db.update_invoice(inv_no, res)
            self.refresh_all_tabs()
            self.status_bar.showMessage(f"{inv_no} faturası ödendi olarak kaydedildi.", 4000)

    def _on_paid_cell_double_clicked(self, row: int, col: int):
        """Sekme 4 Çift Tıklama: Ödenmiş faturayı düzeltme imkanı."""
        item = self.table_paid.item(row, 0)
        if not item:
            return
        inv_no = item.data(Qt.ItemDataRole.UserRole)
        invoice = self.db.get_invoice(inv_no)
        if not invoice:
            return

        dialog = OdemeGirisDialog(invoice, self)
        if dialog.exec():
            if getattr(dialog, "delete_requested", False):
                self._delete_and_archive_invoice(invoice)
                return
            res = dialog.get_result()
            self.db.update_invoice(inv_no, res)
            self.refresh_all_tabs()
            self.status_bar.showMessage(f"{inv_no} ödeme kaydı güncellendi.", 4000)

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

    # --- SÜRÜM KONTROL VE GÜNCELLEME SİSTEMİ (VERSION CHECK & AUTO-UPDATE) ---
    def check_for_updates(self, manual: bool = False):
        """GitHub API üzerinden en son yayınlanan Release sürümünü arka planda kontrol eder."""
        if hasattr(self, "_update_thread") and self._update_thread and self._update_thread.isRunning():
            if manual:
                self.status_bar.showMessage("Güncelleme kontrolü zaten devam ediyor...", 3000)
            return

        if manual:
            self.status_bar.showMessage("GitHub üzerinden güncellemeler kontrol ediliyor...", 4000)

        self._update_thread = UpdateCheckWorker(manual=manual, parent=self)
        self._update_thread.update_available.connect(self._on_update_available)
        self._update_thread.no_update.connect(lambda tag: self._on_no_update(tag, manual))
        self._update_thread.check_failed.connect(lambda err: self._on_update_check_failed(err, manual))
        self._update_thread.start()

    @pyqtSlot(dict)
    def _on_update_available(self, release_info: dict):
        tag_name = release_info.get("tag_name", "")
        self.status_bar.showMessage(f"Yeni sürüm bulundu: {tag_name}", 5000)

        dialog = UpdatePromptDialog(release_info, self)
        if dialog.exec():
            download_url = release_info.get("download_url")
            if not download_url:
                QMessageBox.warning(
                    self,
                    "İndirme Bağlantısı Bulunamadı",
                    f"'{tag_name}' sürümü bulundu ancak doğrudan indirilebilir bir .exe dosyası eklenmemiş.",
                )
                return

            # İndirilecek dosya konumu
            if getattr(sys, "frozen", False):
                exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            else:
                exe_dir = self.base_dir

            target_path = os.path.join(exe_dir, "FaturaTakip_new.exe")

            # Arka Planda İndirme ve İlerleme Çubuğu (Progress Dialog)
            prog_dialog = DownloadProgressDialog(download_url, target_path, self)
            if prog_dialog.exec() and prog_dialog.download_completed:
                # İndirme bitti, update.bat ile hot-swap uygulayıp yeniden başlat
                apply_update_and_restart(prog_dialog.downloaded_file)

    def _on_no_update(self, latest_tag: str, manual: bool):
        self.status_bar.showMessage(f"Uygulamanız güncel. (Sürüm: v{APP_VERSION})", 4000)
        if manual:
            QMessageBox.information(
                self,
                "Sürüm Kontrolü",
                f"Tebrikler! Uygulamanız en güncel sürümde.\n\nMevcut Sürüm: v{APP_VERSION}\nGitHub Son Sürüm: {latest_tag}",
            )

    def _on_update_check_failed(self, error_msg: str, manual: bool):
        if manual:
            self.status_bar.showMessage(f"Güncelleme kontrolü: {error_msg}", 5000)
            QMessageBox.warning(
                self,
                "Güncelleme Kontrolü",
                f"Güncellemeler kontrol edilirken bir durum oluştu:\n\n{error_msg}",
            )
        else:
            print(f"[Updater Otomatik Kontrol] {error_msg}")

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
        if hasattr(self, "_update_thread") and self._update_thread and self._update_thread.isRunning():
            self._update_thread.quit()
            self._update_thread.wait(1000)
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

