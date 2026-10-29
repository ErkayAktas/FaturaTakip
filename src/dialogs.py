from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from src.database import ExpenseDatabase, parse_date_obj
from src.holiday_service import holiday_service
from src.styles import COLORS


class BaseResponsiveDialog(QDialog):
    """
    Dinamik Pop-up Yüksekliği ve Scrollbar Desteği:
    - Hiçbir açılır pencerenin (dialog, detay veya düzenleme ekranı) yüksekliğinin
      fiziksel ekran yüksekliğini aşmasına izin vermez.
    - İçerik ekranın %80'ini aşıyorsa pencereyi maksimum ekran yüksekliğine
      (ekranın %80'ine) sabitler.
    - İç kısımdaki verilere dikey kaydırma çubuğu (QScrollArea) eklenerek
      tüm içerik ve butonlar eksiksiz ve konforlu şekilde görüntülenir.
    """

    def __init__(self, parent=None, max_screen_ratio: float = 0.80):
        super().__init__(parent)
        self.max_screen_ratio = max_screen_ratio

    def showEvent(self, event):
        super().showEvent(event)
        self._enforce_dynamic_screen_bounds()

    def _enforce_dynamic_screen_bounds(self):
        screen = None
        if self.parentWidget() and hasattr(self.parentWidget(), "screen"):
            screen = self.parentWidget().screen()
        if not screen:
            screen = QApplication.primaryScreen()
        if not screen and hasattr(self, "screen"):
            screen = self.screen()

        if screen:
            avail_geo = screen.availableGeometry()
            max_allowed_h = int(avail_geo.height() * self.max_screen_ratio)
            max_allowed_w = int(avail_geo.width() * 0.92)

            self.setMaximumHeight(max_allowed_h)
            self.setMaximumWidth(max_allowed_w)

            hint_h = self.sizeHint().height()
            current_h = self.height()
            target_h = max(hint_h, current_h)

            if target_h > max_allowed_h:
                self.resize(self.width(), max_allowed_h)


class VadeGirisDialog(BaseResponsiveDialog):
    """
    Sekme 1 için Vade (İş Günü) Giriş Pop-up'ı.
    Kullanıcı iş günü girdikçe Türkiye resmi tatilleri ve hafta sonları
    atlanarak canlı olarak Son Ödeme Tarihi hesaplanır ve gösterilir.
    """

    def __init__(self, invoice: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.invoice = invoice
        self.calculated_due_date = ""
        self.selected_work_days = 0

        self.delete_requested = False

        self.setWindowTitle("Vade Belirle - " + str(invoice.get("invoice_number", "")))
        self.setMinimumWidth(480)
        self.setup_ui()

    def setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(8)
        root_layout.setContentsMargins(16, 16, 16, 12)

        # Kaydırılabilir Alan (QScrollArea)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(16)
        layout.setContentsMargins(8, 6, 8, 6)

        # Başlık ve Bilgi Kutusu
        title_lbl = QLabel("Vade ve Son Ödeme Tarihi Belirleme")
        title_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLORS['accent_blue']};")
        layout.addWidget(title_lbl)

        # Fatura Özet Bilgi Kartı
        info_frame = QFrame()
        info_frame.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 12px;"
        )
        info_layout = QFormLayout(info_frame)
        info_layout.setSpacing(8)

        company_lbl = QLabel(str(self.invoice.get("company_name", "-")))
        company_lbl.setStyleSheet("font-weight: bold; color: #FFFFFF;")
        inv_no_lbl = QLabel(str(self.invoice.get("invoice_number", "-")))
        inv_no_lbl.setStyleSheet("color: #38BDF8; font-weight: bold;")
        
        # Fatura kesim tarihi formatla
        raw_date = str(self.invoice.get("invoice_date", "-"))
        try:
            display_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            display_date = raw_date
        date_lbl = QLabel(display_date)

        tax_ex_val = float(self.invoice.get("tax_excluded_amount") or 0.0)
        kdv_val = float(self.invoice.get("kdv_amount") or 0.0)
        total_val = float(self.invoice.get("total_amount") or (tax_ex_val + kdv_val))
        currency = str(self.invoice.get("currency", "TL"))

        total_lbl = QLabel(f"{total_val:,.2f} {currency}")
        total_lbl.setStyleSheet("font-weight: bold; color: #10B981; font-size: 13px;")
        tax_ex_lbl = QLabel(f"{tax_ex_val:,.2f} {currency}")
        tax_ex_lbl.setStyleSheet("font-weight: bold; color: #38BDF8; font-size: 13px;")
        kdv_lbl = QLabel(f"{kdv_val:,.2f} {currency}")
        kdv_lbl.setStyleSheet("font-weight: bold; color: #F59E0B; font-size: 13px;")

        info_layout.addRow("Şirket İsmi:", company_lbl)
        info_layout.addRow("Fatura No:", inv_no_lbl)
        info_layout.addRow("Kesim Tarihi:", date_lbl)
        info_layout.addRow("Vergi Hariç Fiyat:", tax_ex_lbl)
        info_layout.addRow("Vergi (KDV Tutarı):", kdv_lbl)
        info_layout.addRow("Toplam Fiyat (Vergiler Dahil):", total_lbl)

        layout.addWidget(info_frame)

        # Firma İletişim Bilgileri (Ana Listelerde Gizli)
        contact_box = QGroupBox("📞 Firma İletişim Bilgileri (Detay Ekranı)")
        contact_box.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: #38BDF8; border: 1px solid {COLORS['border']}; border-radius: 8px; margin-top: 6px; padding: 10px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        contact_layout = QFormLayout(contact_box)
        contact_layout.setSpacing(8)

        self.contact_name_edit = QLineEdit(str(self.invoice.get("contact_name") or ""))
        self.contact_name_edit.setPlaceholderText("Yetkili Adı Soyadı")
        self.contact_name_edit.setStyleSheet("padding: 6px; font-size: 13px;")

        self.contact_phone_edit = QLineEdit(str(self.invoice.get("contact_phone") or ""))
        self.contact_phone_edit.setPlaceholderText("Telefon Numarası (05xx xxx xx xx)")
        self.contact_phone_edit.setStyleSheet("padding: 6px; font-size: 13px;")

        contact_layout.addRow("İsim (Yetkili):", self.contact_name_edit)
        contact_layout.addRow("Numara (Telefon):", self.contact_phone_edit)
        layout.addWidget(contact_box)

        # İş Günü Girişi
        input_frame = QFrame()
        input_frame.setStyleSheet(
            f"background-color: #1E293B; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 14px;"
        )
        input_layout = QVBoxLayout(input_frame)
        input_layout.setSpacing(10)

        input_title = QLabel("Vade (Kaç İş Günü?):")
        input_title.setStyleSheet("font-weight: 600; color: #F8FAFC; font-size: 13px;")
        input_layout.addWidget(input_title)

        spin_layout = QHBoxLayout()
        self.work_days_spin = QSpinBox()
        self.work_days_spin.setRange(1, 365)
        self.work_days_spin.setValue(7)  # Varsayılan 7 iş günü
        self.work_days_spin.setStyleSheet("font-size: 15px; font-weight: bold; padding: 8px;")
        self.work_days_spin.valueChanged.connect(self._recalculate_preview)

        days_text_lbl = QLabel("İş Günü")
        days_text_lbl.setStyleSheet("color: #94A3B8; font-size: 13px;")

        spin_layout.addWidget(self.work_days_spin, 2)
        spin_layout.addWidget(days_text_lbl, 3)
        spin_layout.addStretch()
        input_layout.addLayout(spin_layout)

        # Canlı Hesaplanan Tarih Göstergesi
        self.preview_box = QFrame()
        self.preview_box.setStyleSheet(
            "background-color: #0F172A; border-radius: 6px; padding: 10px; border-left: 4px solid #3B82F6;"
        )
        preview_layout = QVBoxLayout(self.preview_box)
        preview_layout.setSpacing(4)

        self.preview_date_lbl = QLabel("")
        self.preview_date_lbl.setStyleSheet("color: #60A5FA; font-size: 15px; font-weight: bold;")
        self.preview_details_lbl = QLabel("")
        self.preview_details_lbl.setStyleSheet("color: #94A3B8; font-size: 11px;")
        self.preview_details_lbl.setWordWrap(True)

        preview_layout.addWidget(self.preview_date_lbl)
        preview_layout.addWidget(self.preview_details_lbl)

        input_layout.addWidget(self.preview_box)
        layout.addWidget(input_frame)

        scroll_area.setWidget(content_widget)
        root_layout.addWidget(scroll_area, 1)

        # Sabit Alt Butonlar
        btn_frame = QFrame()
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(8, 4, 8, 4)
        btn_layout.setSpacing(12)

        self.delete_btn = QPushButton("🗑️ Faturayı Sil")
        self.delete_btn.setObjectName("dangerBtn")
        self.delete_btn.clicked.connect(self._on_delete_clicked)

        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setObjectName("secondaryBtn")
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("✓ Kaydet ve Tüm Faturalara Taşı")
        self.save_btn.setObjectName("successBtn")
        self.save_btn.clicked.connect(self._on_save)

        btn_layout.addWidget(self.delete_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        root_layout.addWidget(btn_frame)

        # İlk hesaplamayı çalıştır
        self._recalculate_preview()

    def _on_delete_clicked(self):
        inv_no = self.invoice.get("invoice_number", "-")
        reply = QMessageBox.question(
            self,
            "Faturayı Silme Onayı",
            f"'{inv_no}' numaralı faturayı silmek ve PDF dosyasını 'Silinenler' klasörüne taşımak istediğinize emin misiniz?\n\nBu işlem faturayı veritabanından tamamen kaldıracaktır.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_requested = True
            self.accept()

    def _recalculate_preview(self):
        work_days = self.work_days_spin.value()
        invoice_date_str = self.invoice.get("invoice_date", "")

        due_date, weekends, holidays = holiday_service.calculate_due_date_with_breakdown(
            invoice_date_str, work_days
        )
        self.calculated_due_date = due_date.strftime("%Y-%m-%d")
        self.selected_work_days = work_days

        formatted_date = due_date.strftime("%d.%m.%Y")
        day_name = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"][due_date.weekday()]

        self.preview_date_lbl.setText(f"Son Ödeme Tarihi: {formatted_date} ({day_name})")

        detail_text = f"Atlanan Hafta Sonu: {len(weekends)} gün"
        if holidays:
            holiday_names = ", ".join([f"{h[1]} ({h[0].strftime('%d.%m')})" for h in holidays])
            detail_text += f" | Atlanan Resmi Tatiller: {holiday_names}"
        else:
            detail_text += " | Bu aralıkta resmi tatil bulunmuyor."

        self.preview_details_lbl.setText(detail_text)

    def _on_save(self):
        self.accept()

    def get_result(self) -> Dict[str, Any]:
        return {
            "due_date": self.calculated_due_date,
            "work_days_added": self.selected_work_days,
            "status": "active",
            "contact_name": self.contact_name_edit.text().strip(),
            "contact_phone": self.contact_phone_edit.text().strip(),
        }


class OdemeGirisDialog(BaseResponsiveDialog):
    """
    Fatura Durumu, Ödeme ve Parçalı Ödeme Düzenleme Pop-up'ı:
    - Tamamı Ödendi, Kısmi/Parçalı Ödeme ve Ödenmedi (Aktif) seçenekleri.
    - Parçalı ödemede kalan bakiye canlı gösterilir ve "Kalan Bakiye İçin Yeni Son Ödeme Tarihi" seçilir.
    - Gizli İletişim Bilgileri (İsim & Telefon) görüntülenir ve düzenlenebilir.
    """

    def __init__(self, invoice: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.invoice = invoice
        self.delete_requested = False

        inv_title = invoice.get("invoice_number") or invoice.get("id") or "Fatura"
        self.setWindowTitle(f"Fatura Detayı ve Ödeme Durumu - {inv_title}")
        self.setMinimumWidth(520)
        self.setup_ui()

    def setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(8)
        root_layout.setContentsMargins(16, 16, 16, 12)

        # Kaydırılabilir Alan (QScrollArea)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(14)
        layout.setContentsMargins(8, 6, 8, 6)

        # Başlık
        title_lbl = QLabel("Fatura Detayı ve Ödeme Yönetimi")
        title_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {COLORS['accent_blue']};")
        layout.addWidget(title_lbl)

        # Fatura Bilgi Kartı
        info_frame = QFrame()
        info_frame.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 12px;"
        )
        info_layout = QFormLayout(info_frame)
        info_layout.setSpacing(6)

        info_layout.addRow("Şirket İsmi:", QLabel(str(self.invoice.get("company_name", "-"))))
        
        inv_no_display = str(self.invoice.get("invoice_number", "-"))
        if self.invoice.get("is_cash"):
            inv_no_display = "Nakit (Manuel İşlem)"
        info_layout.addRow("Fatura / İşlem No:", QLabel(inv_no_display))
        
        tax_ex = float(self.invoice.get("tax_excluded_amount", 0.0))
        kdv = float(self.invoice.get("kdv_amount", 0.0))
        self.total_val = float(self.invoice.get("total_amount") or (tax_ex + kdv))
        self.currency = str(self.invoice.get("currency", "TL"))

        tax_lbl = QLabel(f"{tax_ex:,.2f} {self.currency}")
        tax_lbl.setStyleSheet("color: #38BDF8; font-weight: bold;")
        info_layout.addRow("Vergi Hariç Fiyat:", tax_lbl)

        kdv_lbl = QLabel(f"{kdv:,.2f} {self.currency}")
        kdv_lbl.setStyleSheet("color: #F59E0B; font-weight: bold;")
        info_layout.addRow("Vergi (KDV Tutarı):", kdv_lbl)

        total_lbl = QLabel(f"{self.total_val:,.2f} {self.currency}")
        total_lbl.setStyleSheet("color: #10B981; font-weight: bold; font-size: 14px;")
        info_layout.addRow("Toplam Tutar:", total_lbl)

        # Mevcut Son Ödeme Tarihi (Vade)
        self.due_date_edit = QDateEdit()
        self.due_date_edit.setCalendarPopup(True)
        self.due_date_edit.setDisplayFormat("dd.MM.yyyy")
        self.due_date_edit.setStyleSheet("font-weight: bold; color: #38BDF8;")
        due_str = str(self.invoice.get("due_date", ""))
        if due_str and due_str.lower() not in ["none", "null", ""]:
            try:
                dt_due = datetime.strptime(due_str[:10], "%Y-%m-%d")
                self.due_date_edit.setDate(QDate(dt_due.year, dt_due.month, dt_due.day))
            except Exception:
                self.due_date_edit.setDate(QDate.currentDate())
        else:
            self.due_date_edit.setDate(QDate.currentDate())

        info_layout.addRow("Vade (Son Ödeme Tarihi):", self.due_date_edit)
        layout.addWidget(info_frame)

        # Gizli İletişim Bilgileri Bölümü (Sadece bu detay ekranında görüntülenir)
        contact_box = QGroupBox("📞 Firma İletişim Bilgileri (Gizli Alan)")
        contact_box.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: #38BDF8; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 10px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        contact_layout = QFormLayout(contact_box)
        contact_layout.setSpacing(8)

        self.contact_name_edit = QLineEdit(str(self.invoice.get("contact_name") or ""))
        self.contact_name_edit.setPlaceholderText("Firma Yetkilisi / İsim")
        self.contact_name_edit.setStyleSheet("padding: 6px; font-size: 13px;")

        self.contact_phone_edit = QLineEdit(str(self.invoice.get("contact_phone") or ""))
        self.contact_phone_edit.setPlaceholderText("Yetkili Telefon Numarası")
        self.contact_phone_edit.setStyleSheet("padding: 6px; font-size: 13px;")

        contact_layout.addRow("Yetkili İsim:", self.contact_name_edit)
        contact_layout.addRow("Telefon Numarası:", self.contact_phone_edit)
        layout.addWidget(contact_box)

        # Durum Seçim Grubu: 3 Seçenek (Ödenmedi, Parçalı Ödeme, Tamamı Ödendi)
        status_box = QGroupBox("Ödeme Durumu")
        status_box.setStyleSheet(f"font-weight: bold; color: {COLORS['text_primary']};")
        status_layout = QHBoxLayout(status_box)
        status_layout.setSpacing(12)

        self.radio_unpaid = QRadioButton("Ödenmedi (Aktif)")
        self.radio_unpaid.setStyleSheet("color: #F87171; font-weight: bold;")

        self.radio_partial = QRadioButton("⏳ Kısmi / Parçalı Ödeme")
        self.radio_partial.setStyleSheet("color: #F59E0B; font-weight: bold;")

        self.radio_paid = QRadioButton("✓ Tamamı Ödendi")
        self.radio_paid.setStyleSheet("color: #10B981; font-weight: bold;")

        self.button_group = QButtonGroup(self)
        self.button_group.addButton(self.radio_unpaid)
        self.button_group.addButton(self.radio_partial)
        self.button_group.addButton(self.radio_paid)

        # Mevcut durumu seç
        current_status = str(self.invoice.get("status", "active")).lower()
        if current_status in ["paid", "ödendi", "odendi"]:
            self.radio_paid.setChecked(True)
        elif current_status == "partial":
            self.radio_partial.setChecked(True)
        else:
            self.radio_unpaid.setChecked(True)

        self.radio_unpaid.toggled.connect(self._on_status_radio_changed)
        self.radio_partial.toggled.connect(self._on_status_radio_changed)
        self.radio_paid.toggled.connect(self._on_status_radio_changed)

        status_layout.addWidget(self.radio_unpaid)
        status_layout.addWidget(self.radio_partial)
        status_layout.addWidget(self.radio_paid)
        layout.addWidget(status_box)

        # Ödeme ve Parçalı Ödeme Detay Alanları
        self.payment_frame = QFrame()
        self.payment_frame.setStyleSheet(
            f"background-color: #1E293B; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 12px;"
        )
        pay_form = QFormLayout(self.payment_frame)
        pay_form.setSpacing(10)

        # 1. Ödeme Tarihi
        self.payment_date_edit = QDateEdit()
        self.payment_date_edit.setCalendarPopup(True)
        self.payment_date_edit.setDisplayFormat("dd.MM.yyyy")
        existing_pay_date = self.invoice.get("payment_date")
        if existing_pay_date:
            try:
                dt = datetime.strptime(str(existing_pay_date)[:10], "%Y-%m-%d")
                self.payment_date_edit.setDate(QDate(dt.year, dt.month, dt.day))
            except Exception:
                self.payment_date_edit.setDate(QDate.currentDate())
        else:
            self.payment_date_edit.setDate(QDate.currentDate())

        # 2. Ödenen Tutar
        self.paid_amount_spin = QDoubleSpinBox()
        self.paid_amount_spin.setRange(0.01, 999999999.0)
        self.paid_amount_spin.setDecimals(2)
        self.paid_amount_spin.setSuffix(f" {self.currency}")
        self.paid_amount_spin.setStyleSheet("font-size: 14px; font-weight: bold; color: #10B981; padding: 6px;")

        existing_paid = self.invoice.get("paid_amount")
        if existing_paid is not None and float(existing_paid) > 0:
            self.paid_amount_spin.setValue(float(existing_paid))
        else:
            self.paid_amount_spin.setValue(self.total_val)

        self.paid_amount_spin.valueChanged.connect(self._on_paid_amount_spin_changed)

        pay_form.addRow("Ödeme Tarihi:", self.payment_date_edit)
        pay_form.addRow("Ödenen Tutar:", self.paid_amount_spin)

        # 3. Kısmi Ödeme İçin Özel Alanlar (Kalan Bakiye & Yeni Son Ödeme Tarihi)
        self.partial_container = QWidget()
        partial_layout = QVBoxLayout(self.partial_container)
        partial_layout.setContentsMargins(0, 4, 0, 0)
        partial_layout.setSpacing(8)

        # Kalan Bakiye Göstergesi
        self.remaining_card = QFrame()
        self.remaining_card.setStyleSheet(
            "background-color: #451A03; border: 1px solid #F59E0B; border-radius: 6px; padding: 8px;"
        )
        rem_layout = QHBoxLayout(self.remaining_card)
        rem_layout.setContentsMargins(8, 6, 8, 6)
        rem_title = QLabel("Kalan Bakiye:")
        rem_title.setStyleSheet("font-weight: bold; color: #FDE68A; font-size: 13px;")
        self.remaining_lbl = QLabel(f"0.00 {self.currency}")
        self.remaining_lbl.setStyleSheet("font-weight: 800; color: #F59E0B; font-size: 14px;")
        rem_layout.addWidget(rem_title)
        rem_layout.addStretch()
        rem_layout.addWidget(self.remaining_lbl)
        partial_layout.addWidget(self.remaining_card)

        # Kalan Bakiye İçin Yeni Son Ödeme Tarihi Seçicisi
        new_due_layout = QHBoxLayout()
        new_due_lbl = QLabel("Kalan Bakiye İçin Yeni Son Ödeme Tarihi:")
        new_due_lbl.setStyleSheet("font-weight: bold; color: #FDE68A; font-size: 13px;")

        self.new_due_date_edit = QDateEdit()
        self.new_due_date_edit.setCalendarPopup(True)
        self.new_due_date_edit.setDisplayFormat("dd.MM.yyyy")
        self.new_due_date_edit.setStyleSheet("font-weight: bold; color: #F59E0B; font-size: 13px; padding: 6px;")

        # Varsayılan olarak mevcut son ödeme tarihi veya 7 gün sonrası
        cur_due = self.invoice.get("due_date")
        if cur_due:
            try:
                dt_d = datetime.strptime(str(cur_due)[:10], "%Y-%m-%d")
                self.new_due_date_edit.setDate(QDate(dt_d.year, dt_d.month, dt_d.day))
            except Exception:
                self.new_due_date_edit.setDate(QDate.currentDate().addDays(7))
        else:
            self.new_due_date_edit.setDate(QDate.currentDate().addDays(7))

        new_due_layout.addWidget(new_due_lbl)
        new_due_layout.addWidget(self.new_due_date_edit)
        partial_layout.addLayout(new_due_layout)

        pay_form.addRow(self.partial_container)
        layout.addWidget(self.payment_frame)

        scroll_area.setWidget(content_widget)
        root_layout.addWidget(scroll_area, 1)

        # Sabit Alt Butonlar
        btn_frame = QFrame()
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(8, 4, 8, 4)
        btn_layout.setSpacing(12)

        self.delete_btn = QPushButton("🗑️ Faturayı Sil")
        self.delete_btn.setObjectName("dangerBtn")
        self.delete_btn.clicked.connect(self._on_delete_clicked)

        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setObjectName("secondaryBtn")
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("✓ Değişiklikleri Kaydet")
        self.save_btn.setObjectName("successBtn")
        self.save_btn.clicked.connect(self.accept)

        btn_layout.addWidget(self.delete_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        root_layout.addWidget(btn_frame)

        # Başlangıç durumunu uygula
        self._on_status_radio_changed()
        self._update_remaining_calculation()

    def _on_delete_clicked(self):
        inv_no = self.invoice.get("invoice_number", "-")
        reply = QMessageBox.question(
            self,
            "Faturayı Silme Onayı",
            f"'{inv_no}' numaralı faturayı silmek ve PDF dosyasını 'Silinenler' klasörüne taşımak istediğinize emin misiniz?\n\nBu işlem faturayı veritabanından tamamen kaldıracaktır.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_requested = True
            self.accept()

    def _on_status_radio_changed(self):
        if self.radio_unpaid.isChecked():
            self.payment_frame.setVisible(False)
        elif self.radio_partial.isChecked():
            self.payment_frame.setVisible(True)
            self.partial_container.setVisible(True)
            # Eğer ödenen tutar tüm faturaya eşitse kullanıcı için yarısına veya varsayılan değere ayarla
            if abs(self.paid_amount_spin.value() - self.total_val) < 0.01:
                half_val = round(self.total_val / 2.0, 2)
                self.paid_amount_spin.setValue(half_val)
            self._update_remaining_calculation()
        elif self.radio_paid.isChecked():
            self.payment_frame.setVisible(True)
            self.partial_container.setVisible(False)
            self.paid_amount_spin.setValue(self.total_val)

    def _on_paid_amount_spin_changed(self, val: float):
        if self.radio_partial.isChecked():
            self._update_remaining_calculation()
        elif self.radio_paid.isChecked():
            # Kullanıcı tam ödendi seçiliyken tutarı azaltırsa parçalı ödemeye otomatik geçiş öner
            if val < (self.total_val - 0.01):
                self.radio_partial.setChecked(True)

    def _update_remaining_calculation(self):
        paid = self.paid_amount_spin.value()
        remaining = max(0.0, self.total_val - paid)
        self.remaining_lbl.setText(f"{remaining:,.2f} {self.currency}")

    def get_result(self) -> Dict[str, Any]:
        contact_name = self.contact_name_edit.text().strip()
        contact_phone = self.contact_phone_edit.text().strip()

        # Temel vade tarihi
        qdate_due = self.due_date_edit.date()
        due_date_str = f"{qdate_due.year():04d}-{qdate_due.month():02d}-{qdate_due.day():02d}"

        result: Dict[str, Any] = {
            "due_date": due_date_str,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
        }

        if self.radio_paid.isChecked():
            qdate_pay = self.payment_date_edit.date()
            pay_date_str = f"{qdate_pay.year():04d}-{qdate_pay.month():02d}-{qdate_pay.day():02d}"
            result.update({
                "status": "paid",
                "payment_date": pay_date_str,
                "paid_amount": round(self.paid_amount_spin.value(), 2),
                "remaining_amount": 0.0,
            })
        elif self.radio_partial.isChecked():
            qdate_pay = self.payment_date_edit.date()
            pay_date_str = f"{qdate_pay.year():04d}-{qdate_pay.month():02d}-{qdate_pay.day():02d}"
            qdate_new_due = self.new_due_date_edit.date()
            new_due_str = f"{qdate_new_due.year():04d}-{qdate_new_due.month():02d}-{qdate_new_due.day():02d}"

            paid_val = round(self.paid_amount_spin.value(), 2)
            rem_val = round(max(0.0, self.total_val - paid_val), 2)

            if rem_val <= 0.01:
                # Tutarın tamamı ödenmişse statüyü paid yap
                result.update({
                    "status": "paid",
                    "payment_date": pay_date_str,
                    "paid_amount": paid_val,
                    "remaining_amount": 0.0,
                })
            else:
                result.update({
                    "status": "partial",
                    "payment_date": pay_date_str,
                    "paid_amount": paid_val,
                    "remaining_amount": rem_val,
                    # Kalan bakiye için seçilen yeni son ödeme tarihi faturanın vade tarihi olur
                    "due_date": new_due_str,
                    "partial_payment_date": pay_date_str,
                })
        else:
            # Ödenmedi (Aktif)
            result.update({
                "status": "active",
                "payment_date": None,
                "paid_amount": None,
                "remaining_amount": None,
            })

        return result


class NakitGirisDialog(BaseResponsiveDialog):
    """
    Manuel Nakit Girişi Pop-up'ı:
    - PDF zorunluluğu olmaksızın sadece nakit alınan işlemlerin sisteme girilmesini sağlar.
    - Fatura Numarası (ID) otomatik olarak 'Nakit' şeklinde atanır.
    - Gizli İletişim Bilgileri (İsim & Telefon) eklenebilir.
    - Vergi Hariç, KDV ve Toplam Tutar 3'lü yapısını destekler.
    """

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("💵 Manuel Nakit Girişi (PDF'siz İşlem)")
        self.setMinimumWidth(500)
        self.setup_ui()

    def setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(8)
        root_layout.setContentsMargins(16, 16, 16, 12)

        # Kaydırılabilir Alan (QScrollArea)
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(14)
        layout.setContentsMargins(8, 6, 8, 6)

        # Başlık ve Açıklama
        title_lbl = QLabel("💵 Manuel Nakit İşlem Girişi")
        title_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: #10B981;")
        sub_lbl = QLabel("PDF belgesi bulunmayan doğrudan nakit tahsilatları veya ödemeleri kaydedebilirsiniz.")
        sub_lbl.setStyleSheet("color: #94A3B8; font-size: 12px;")
        layout.addWidget(title_lbl)
        layout.addWidget(sub_lbl)

        # Form Kartı
        form_frame = QFrame()
        form_frame.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 14px;"
        )
        form_layout = QFormLayout(form_frame)
        form_layout.setSpacing(10)

        # 1. Fatura / İşlem Numarası (Sabit 'Nakit')
        self.inv_no_edit = QLineEdit("Nakit")
        self.inv_no_edit.setReadOnly(True)
        self.inv_no_edit.setStyleSheet("font-weight: bold; color: #10B981; background-color: #0F172A; padding: 6px;")
        form_layout.addRow("İşlem Türü / No:", self.inv_no_edit)

        # 2. Firma İsmi
        self.company_edit = QLineEdit()
        self.company_edit.setPlaceholderText("İşlem Yapılan Firma İsmi (Zorunlu)")
        self.company_edit.setStyleSheet("padding: 6px; font-size: 13px;")
        self.company_edit.editingFinished.connect(self._on_company_editing_finished)
        form_layout.addRow("Firma İsmi *:", self.company_edit)

        # 3. İşlem Tarihi
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setStyleSheet("padding: 6px; font-size: 13px;")
        form_layout.addRow("İşlem Tarihi:", self.date_edit)

        # 4. Fiyat Alanları (3'lü Yapı: Vergi Hariç, KDV, Toplam)
        self.tax_ex_spin = QDoubleSpinBox()
        self.tax_ex_spin.setRange(0.0, 999999999.0)
        self.tax_ex_spin.setDecimals(2)
        self.tax_ex_spin.setSuffix(" TL")
        self.tax_ex_spin.setStyleSheet("color: #38BDF8; font-weight: bold; padding: 6px;")
        self.tax_ex_spin.valueChanged.connect(self._recalc_total_from_parts)

        self.kdv_spin = QDoubleSpinBox()
        self.kdv_spin.setRange(0.0, 999999999.0)
        self.kdv_spin.setDecimals(2)
        self.kdv_spin.setSuffix(" TL")
        self.kdv_spin.setStyleSheet("color: #F59E0B; font-weight: bold; padding: 6px;")
        self.kdv_spin.valueChanged.connect(self._recalc_total_from_parts)

        self.total_spin = QDoubleSpinBox()
        self.total_spin.setRange(0.0, 999999999.0)
        self.total_spin.setDecimals(2)
        self.total_spin.setSuffix(" TL")
        self.total_spin.setStyleSheet("color: #10B981; font-weight: bold; font-size: 14px; padding: 6px;")
        self.total_spin.valueChanged.connect(self._on_total_spin_changed)

        form_layout.addRow("Vergi Hariç Tutar:", self.tax_ex_spin)
        form_layout.addRow("Vergi (KDV Tutarı):", self.kdv_spin)
        form_layout.addRow("Toplam Fiyat (Vergiler Dahil) *:", self.total_spin)

        layout.addWidget(form_frame)

        # Ödeme Durumu
        status_box = QGroupBox("Tahsilat / Ödeme Durumu")
        status_box.setStyleSheet(f"font-weight: bold; color: {COLORS['text_primary']};")
        status_layout = QVBoxLayout(status_box)

        self.radio_cash_paid = QRadioButton("✓ Nakit Tahsil Edildi (Ödendi)")
        self.radio_cash_paid.setStyleSheet("color: #10B981; font-weight: bold;")
        self.radio_cash_paid.setChecked(True)

        self.radio_cash_pending = QRadioButton("⏳ Nakit Bekleniyor (Vadesi Var)")
        self.radio_cash_pending.setStyleSheet("color: #F59E0B; font-weight: bold;")

        status_layout.addWidget(self.radio_cash_paid)
        status_layout.addWidget(self.radio_cash_pending)

        # Vade Tarihi Alanı (Bekleniyor seçildiğinde)
        self.due_container = QWidget()
        due_row = QHBoxLayout(self.due_container)
        due_row.setContentsMargins(0, 4, 0, 0)
        due_row.addWidget(QLabel("Nakit Vade Tarihi:"))
        self.cash_due_date_edit = QDateEdit()
        self.cash_due_date_edit.setCalendarPopup(True)
        self.cash_due_date_edit.setDisplayFormat("dd.MM.yyyy")
        self.cash_due_date_edit.setDate(QDate.currentDate().addDays(7))
        due_row.addWidget(self.cash_due_date_edit)
        self.due_container.setVisible(False)

        self.radio_cash_pending.toggled.connect(lambda checked: self.due_container.setVisible(checked))
        status_layout.addWidget(self.due_container)

        layout.addWidget(status_box)

        # Gizli İletişim Bilgileri (İsim ve Telefon)
        contact_box = QGroupBox("📞 Firma İletişim Bilgileri (Gizli Alan)")
        contact_box.setStyleSheet(
            f"QGroupBox {{ font-weight: bold; color: #38BDF8; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 10px; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        contact_layout = QFormLayout(contact_box)
        contact_layout.setSpacing(8)

        self.contact_name_edit = QLineEdit()
        self.contact_name_edit.setPlaceholderText("Yetkili Adı Soyadı")
        self.contact_name_edit.setStyleSheet("padding: 6px; font-size: 13px;")

        self.contact_phone_edit = QLineEdit()
        self.contact_phone_edit.setPlaceholderText("Telefon Numarası (05xx xxx xx xx)")
        self.contact_phone_edit.setStyleSheet("padding: 6px; font-size: 13px;")

        contact_layout.addRow("Yetkili İsim:", self.contact_name_edit)
        contact_layout.addRow("Telefon Numarası:", self.contact_phone_edit)
        layout.addWidget(contact_box)

        # Not / Açıklama
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("İşlem açıklaması veya not (Opsiyonel)")
        self.notes_edit.setStyleSheet("padding: 6px; font-size: 13px;")
        layout.addWidget(self.notes_edit)

        scroll_area.setWidget(content_widget)
        root_layout.addWidget(scroll_area, 1)

        # Sabit Alt Butonlar
        btn_frame = QFrame()
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(8, 4, 8, 4)
        btn_layout.setSpacing(12)

        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setObjectName("secondaryBtn")
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("✓ Nakit İşlemi Kaydet")
        self.save_btn.setObjectName("successBtn")
        self.save_btn.clicked.connect(self._on_save)

        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        root_layout.addWidget(btn_frame)

    def _recalc_total_from_parts(self):
        tax_ex = self.tax_ex_spin.value()
        kdv = self.kdv_spin.value()
        self.total_spin.blockSignals(True)
        self.total_spin.setValue(round(tax_ex + kdv, 2))
        self.total_spin.blockSignals(False)

    def _on_total_spin_changed(self, total: float):
        if self.tax_ex_spin.value() == 0.0 and self.kdv_spin.value() == 0.0:
            self.tax_ex_spin.blockSignals(True)
            self.tax_ex_spin.setValue(total)
            self.tax_ex_spin.blockSignals(False)

    def _on_company_editing_finished(self):
        comp = self.company_edit.text().strip()
        if comp and self.db:
            # Daha önce kayıtlı iletişim bilgisi varsa getir
            c_name, c_phone = self.db.get_company_contact(comp)
            if c_name and not self.contact_name_edit.text().strip():
                self.contact_name_edit.setText(c_name)
            if c_phone and not self.contact_phone_edit.text().strip():
                self.contact_phone_edit.setText(c_phone)

    def _on_save(self):
        comp = self.company_edit.text().strip()
        if not comp:
            QMessageBox.warning(self, "Eksik Alan", "Lütfen bir firma ismi giriniz.")
            self.company_edit.setFocus()
            return

        if self.total_spin.value() <= 0:
            QMessageBox.warning(self, "Eksik Tutar", "Lütfen geçerli bir toplam tutar giriniz.")
            self.total_spin.setFocus()
            return

        self.accept()

    def get_result(self) -> Dict[str, Any]:
        qdate = self.date_edit.date()
        date_str = f"{qdate.year():04d}-{qdate.month():02d}-{qdate.day():02d}"

        tax_ex = round(self.tax_ex_spin.value(), 2)
        kdv = round(self.kdv_spin.value(), 2)
        total = round(self.total_spin.value(), 2)

        if tax_ex == 0.0 and kdv == 0.0:
            tax_ex = total

        is_paid = self.radio_cash_paid.isChecked()
        if is_paid:
            status = "paid"
            pay_date = date_str
            due_date = date_str
            paid_amt = total
        else:
            status = "active"
            pay_date = None
            paid_amt = None
            q_due = self.cash_due_date_edit.date()
            due_date = f"{q_due.year():04d}-{q_due.month():02d}-{q_due.day():02d}"

        return {
            "invoice_number": "Nakit",
            "company_name": self.company_edit.text().strip(),
            "invoice_date": date_str,
            "tax_excluded_amount": tax_ex,
            "kdv_amount": kdv,
            "total_amount": total,
            "currency": "TL",
            "status": status,
            "payment_date": pay_date,
            "paid_amount": paid_amt,
            "due_date": due_date,
            "contact_name": self.contact_name_edit.text().strip(),
            "contact_phone": self.contact_phone_edit.text().strip(),
            "notes": self.notes_edit.text().strip(),
            "is_cash": True,
        }


class TopluVadeDialog(BaseResponsiveDialog):
    """
    Toplu Vade Değiştirme Pop-up'ı:
    Seçilen faturalar için tek bir tarih seçici penceresi açıp
    hepsinin vadesini (son ödeme tarihini) aynı anda günceller.
    """

    def __init__(self, invoice_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📅 Toplu Vade Belirleme")
        self.setFixedWidth(460)
        self.invoice_count = invoice_count
        self.selected_date = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header = QLabel(f"Seçilen {self.invoice_count} adet fatura için yeni son ödeme tarihini (vade) seçiniz:")
        header.setWordWrap(True)
        header.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(12)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setMinimumDate(QDate(1900, 1, 1))
        today_dt = datetime.today()
        future_dt = today_dt + timedelta(days=30)
        self.date_edit.setDate(QDate(future_dt.year, future_dt.month, future_dt.day))
        if self.date_edit.calendarWidget():
            self.date_edit.calendarWidget().setGridVisible(True)

        form.addRow("Yeni Son Ödeme Tarihi:", self.date_edit)
        layout.addLayout(form)

        # Hızlı Vade Butonları
        quick_layout = QHBoxLayout()
        quick_layout.setSpacing(6)
        lbl_quick = QLabel("Hızlı Ekle:")
        lbl_quick.setStyleSheet("color: #94A3B8; font-size: 11px;")
        quick_layout.addWidget(lbl_quick)

        for days, label in [(7, "+7 Gün"), (15, "+15 Gün"), (30, "+30 Gün"), (45, "+45 Gün"), (60, "+60 Gün")]:
            btn = QPushButton(label)
            btn.setObjectName("secondaryBtn")
            btn.setStyleSheet("padding: 4px 8px; font-size: 11px;")
            btn.clicked.connect(lambda _, d=days: self._add_days(d))
            quick_layout.addWidget(btn)
        quick_layout.addStretch()
        layout.addLayout(quick_layout)

        # Butonlar
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("İptal")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("✓ Vadeyi Güncelle")
        self.btn_save.setObjectName("successBtn")
        self.btn_save.clicked.connect(self._on_save)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def _add_days(self, days: int):
        cur = self.date_edit.date()
        self.date_edit.setDate(cur.addDays(days))

    def _on_save(self):
        d = self.date_edit.date()
        self.selected_date = f"{d.year():04d}-{d.month():02d}-{d.day():02d}"
        self.accept()

    def get_selected_date(self) -> str:
        return self.selected_date or ""

    def get_selected_date_display(self) -> str:
        d = self.date_edit.date()
        return f"{d.day():02d}.{d.month():02d}.{d.year()}"


class TopluOdemeDialog(BaseResponsiveDialog):
    """
    Toplu Ödendi İşaretleme Pop-up'ı:
    Seçilen faturaların statüsünü tek seferde "Ödendi" olarak değiştirmek için
    ödeme tarihini seçtirir ve onay alır.
    """

    def __init__(self, invoice_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("✅ Toplu Ödendi İşaretle")
        self.setFixedWidth(440)
        self.invoice_count = invoice_count
        self.selected_date = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        info = QLabel(f"Seçilen {self.invoice_count} adet fatura 'Ödendi' statüsüne alınacaktır.\nÖdeme tarihini onaylayınız:")
        info.setWordWrap(True)
        info.setStyleSheet("font-size: 13px; font-weight: 600; color: #10B981;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(12)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setMinimumDate(QDate(1900, 1, 1))
        today_dt = datetime.today()
        self.date_edit.setDate(QDate(today_dt.year, today_dt.month, today_dt.day))
        if self.date_edit.calendarWidget():
            self.date_edit.calendarWidget().setGridVisible(True)

        form.addRow("Ödeme Tarihi:", self.date_edit)
        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("İptal")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("✓ Onayla ve Ödendi Yap")
        self.btn_save.setObjectName("successBtn")
        self.btn_save.clicked.connect(self._on_save)

        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

    def _on_save(self):
        d = self.date_edit.date()
        self.selected_date = f"{d.year():04d}-{d.month():02d}-{d.day():02d}"
        self.accept()

    def get_selected_date(self) -> str:
        return self.selected_date or datetime.today().strftime("%Y-%m-%d")

    def get_selected_date_display(self) -> str:
        d = self.date_edit.date()
        return f"{d.day():02d}.{d.month():02d}.{d.year()}"


class GiderYonetimiWidget(QWidget):
    """
    Gider Yönetimi ve Gelir - Gider Özeti Modülü (Ana Pencereye Gömülü Bileşen):
    3 Sekmeli Modern Panel:
    1. Gider Türü Düzenleme: Kategori ekleme, liste üzerinden anlık düzenleme ve silme.
    2. Gider Ekle: Gider türü, tarih, tutar ve açıklama girişi (yerele ve Dropbox'a anında kayıt).
    3. Gelir - Gider Özeti: Tarih aralıklı dinamik gösterge paneli (Dashboard); Toplam Gelir,
       Toplam Gider, Net Durum (kâr: yeşil, zarar: kırmızı), oran göstergesi ve kategori dağılımı.
    """

    def __init__(self, db, expense_db: Optional[ExpenseDatabase] = None, dropbox_sync=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.expense_db = expense_db or ExpenseDatabase()
        self.dropbox_sync = dropbox_sync

        self._setup_ui()
        self.refresh_all()

    def refresh_all(self):
        """Tüm sekmelerdeki verileri diskten ve veritabanından yeniler."""
        self._refresh_categories_table()
        self._refresh_categories_combo()
        self._refresh_recent_expenses()
        self._calculate_summary()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 14)
        root_layout.setSpacing(10)

        # Üst Başlık ve Bilgi Çubuğu
        header_frame = QFrame()
        header_frame.setStyleSheet(
            f"background-color: {COLORS['bg_card']}; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 10px 14px;"
        )
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(3)
        lbl_title = QLabel("📊 GİDER YÖNETİMİ & GELİR - GİDER ANALİZİ")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.5px;")
        lbl_sub = QLabel("Gider türlerini yönetin, yeni harcama kaydedin ve finansal net durumunuzu anlık izleyin.")
        lbl_sub.setStyleSheet("font-size: 11px; color: #94A3B8;")
        title_vbox.addWidget(lbl_title)
        title_vbox.addWidget(lbl_sub)
        header_layout.addLayout(title_vbox)
        header_layout.addStretch()

        root_layout.addWidget(header_frame)

        # 3 Sekmeli QTabWidget
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #334155; background-color: #1E293B; border-radius: 8px; top: -1px; } "
            "QTabBar::tab { background-color: #0F172A; color: #94A3B8; padding: 9px 20px; font-weight: bold; border: 1px solid #334155; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; } "
            "QTabBar::tab:selected { background-color: #1E293B; color: #FFFFFF; border-bottom: 2px solid #38BDF8; }"
        )

        # Sekme 1: Gider Türü Düzenleme
        self.tab_cat = QWidget()
        self._setup_tab_categories()
        self.tab_widget.addTab(self.tab_cat, "⚙️ Gider Türü Düzenleme")

        # Sekme 2: Gider Ekle
        self.tab_add = QWidget()
        self._setup_tab_add_expense()
        self.tab_widget.addTab(self.tab_add, "➕ Gider Ekle")

        # Sekme 3: Gelir - Gider Özeti
        self.tab_sum = QWidget()
        self._setup_tab_summary()
        self.tab_widget.addTab(self.tab_sum, "📈 Gelir - Gider Özeti")

        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        root_layout.addWidget(self.tab_widget, 1)

    def _on_tab_changed(self, idx: int):
        if idx == 0:
            self._refresh_categories_table()
        elif idx == 1:
            self._refresh_categories_combo()
            self._refresh_recent_expenses()
        elif idx == 2:
            self._calculate_summary()

    # =========================================================================
    # SEKME 1: GİDER TÜRÜ DÜZENLEME
    # =========================================================================
    def _setup_tab_categories(self):
        layout = QVBoxLayout(self.tab_cat)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Üst Ekleme Çerçevesi
        add_frame = QFrame()
        add_frame.setStyleSheet(
            "background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; padding: 10px;"
        )
        add_layout = QHBoxLayout(add_frame)
        add_layout.setContentsMargins(6, 4, 6, 4)
        add_layout.setSpacing(10)

        lbl = QLabel("Yeni Gider Türü:")
        lbl.setStyleSheet("font-weight: bold; color: #E2E8F0; font-size: 12px;")
        add_layout.addWidget(lbl)

        self.input_new_category = QLineEdit()
        self.input_new_category.setPlaceholderText("Gider türü adı girin (Örn: Yakıt, Otoyol, Lastik, Sigorta)...")
        self.input_new_category.setStyleSheet("padding: 6px 10px; font-size: 13px; background-color: #1E293B;")
        self.input_new_category.returnPressed.connect(self._add_category)
        add_layout.addWidget(self.input_new_category, 1)

        btn_add = QPushButton("➕ Yeni Tür Ekle")
        btn_add.setStyleSheet(
            "background-color: #0284C7; color: #FFFFFF; font-weight: bold; padding: 7px 16px; border-radius: 6px;"
        )
        btn_add.clicked.connect(self._add_category)
        add_layout.addWidget(btn_add)
        layout.addWidget(add_frame)

        # Gider Türleri Tablosu
        self.table_categories = QTableWidget()
        self.table_categories.setColumnCount(4)
        self.table_categories.setHorizontalHeaderLabels(["Gider Türü Adı", "Kayıtlı Harcama Adedi", "Toplam Harcama Tutarı", "İŞLEMLER"])
        self.table_categories.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_categories.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_categories.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_categories.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table_categories.setColumnWidth(3, 220)
        self.table_categories.verticalHeader().setDefaultSectionSize(40)
        self.table_categories.verticalHeader().setVisible(False)
        self.table_categories.setAlternatingRowColors(True)
        self.table_categories.setStyleSheet(
            "QTableWidget { background-color: #0F172A; border: 1px solid #334155; border-radius: 6px; } "
            "QTableWidget::item { padding: 6px 10px; }"
        )
        layout.addWidget(self.table_categories, 1)

        hint = QLabel("💡 İpucu: Listelenen gider türlerini anlık olarak 'Düzenle' ile değiştirebilir veya 'Sil' butonuyla kaldırabilirsiniz.")
        hint.setStyleSheet("font-size: 11px; color: #94A3B8; font-style: italic;")
        layout.addWidget(hint)

    def _refresh_categories_table(self):
        categories = self.expense_db.get_categories()
        all_expenses = self.expense_db.get_expenses()

        # Kategori başına kullanım ve tutar hesabı
        counts: Dict[str, int] = {}
        totals: Dict[str, float] = {}
        for exp in all_expenses:
            cat = str(exp.get("category", "")).strip()
            counts[cat] = counts.get(cat, 0) + 1
            totals[cat] = totals.get(cat, 0.0) + float(exp.get("amount") or 0.0)

        self.table_categories.setRowCount(len(categories))
        for row, cat in enumerate(categories):
            self.table_categories.setRowHeight(row, 40)

            # 0: İsim
            item_name = QTableWidgetItem(cat)
            item_name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_categories.setItem(row, 0, item_name)

            # 1: Harcama Adedi
            c_cnt = counts.get(cat, 0)
            item_count = QTableWidgetItem(f"{c_cnt} Adet")
            item_count.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_count.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_categories.setItem(row, 1, item_count)

            # 2: Toplam Harcama Tutarı
            c_tot = totals.get(cat, 0.0)
            item_tot = QTableWidgetItem(f"{c_tot:,.2f} TL")
            item_tot.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_tot.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_categories.setItem(row, 2, item_tot)

            # 3: Aksiyon Butonları (Düzenle & Sil)
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(6, 4, 6, 4)
            action_layout.setSpacing(8)
            action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            btn_edit = QPushButton("✏️ Düzenle")
            btn_edit.setMinimumWidth(85)
            btn_edit.setFixedHeight(28)
            btn_edit.setStyleSheet(
                "QPushButton { padding: 4px 10px; font-size: 11px; font-weight: bold; background-color: #334155; color: #FFFFFF; border-radius: 4px; border: 1px solid #475569; } "
                "QPushButton:hover { background-color: #475569; }"
            )
            btn_edit.clicked.connect(lambda _, c=cat: self._edit_category(c))

            btn_del = QPushButton("🗑️ Sil")
            btn_del.setMinimumWidth(75)
            btn_del.setFixedHeight(28)
            btn_del.setStyleSheet(
                "QPushButton { padding: 4px 10px; font-size: 11px; font-weight: bold; background-color: #EF4444; color: #FFFFFF; border-radius: 4px; border: 1px solid #DC2626; } "
                "QPushButton:hover { background-color: #DC2626; }"
            )
            btn_del.clicked.connect(lambda _, c=cat: self._delete_category(c))

            action_layout.addWidget(btn_edit)
            action_layout.addWidget(btn_del)
            self.table_categories.setCellWidget(row, 3, action_widget)

    def _add_category(self):
        name = self.input_new_category.text().strip()
        if not name:
            QMessageBox.warning(self, "Uyarı", "Lütfen bir gider türü adı giriniz.")
            return

        success = self.expense_db.add_category(name)
        if success:
            if self.dropbox_sync:
                self.dropbox_sync.trigger_instant_upload_expenses()
            self.input_new_category.clear()
            self._refresh_categories_table()
            self._refresh_categories_combo()
        else:
            QMessageBox.information(self, "Bilgi", f"'{name}' gider türü zaten mevcut.")

    def _edit_category(self, old_name: str):
        new_name, ok = QInputDialog.getText(
            self,
            "Gider Türünü Düzenle",
            f"'{old_name}' gider türü için yeni bir isim giriniz:",
            text=old_name
        )
        if ok and new_name.strip() and new_name.strip() != old_name:
            clean_new = new_name.strip()
            success = self.expense_db.update_category(old_name, clean_new)
            if success:
                if self.dropbox_sync:
                    self.dropbox_sync.trigger_instant_upload_expenses()
                self._refresh_categories_table()
                self._refresh_categories_combo()
                self._refresh_recent_expenses()
                self._calculate_summary()
            else:
                QMessageBox.warning(self, "Hata", "Gider türü güncellenemedi veya bu isimde bir tür zaten var.")

    def _delete_category(self, cat_name: str):
        all_exp = self.expense_db.get_expenses()
        used_count = sum(1 for e in all_exp if str(e.get("category", "")).strip().lower() == cat_name.lower())

        msg = f"'{cat_name}' gider türünü silmek istediğinize emin misiniz?"
        if used_count > 0:
            msg += f"\n\n⚠️ Bu türe ait kayıtlı {used_count} adet harcama bulunmaktadır. Tür silinirse bu harcamalar 'Diğer' olarak korunacaktır."

        reply = QMessageBox.question(
            self,
            "Gider Türü Silme Onayı",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.expense_db.delete_category(cat_name)
            if self.dropbox_sync:
                self.dropbox_sync.trigger_instant_upload_expenses()
            self._refresh_categories_table()
            self._refresh_categories_combo()
            self._calculate_summary()

    # =========================================================================
    # SEKME 2: GİDER EKLE
    # =========================================================================
    def _setup_tab_add_expense(self):
        layout = QVBoxLayout(self.tab_add)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Form Kartı
        form_card = QFrame()
        form_card.setStyleSheet(
            "background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px;"
        )
        form_layout = QFormLayout(form_card)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(0, 0, 0, 0)

        # 1. Gider Türü
        self.combo_expense_cat = QComboBox()
        self.combo_expense_cat.setView(QListView())
        self.combo_expense_cat.setStyleSheet(
            "QComboBox { background-color: #1E293B; color: #FFFFFF; border: 1px solid #475569; border-radius: 6px; padding: 6px 12px; font-weight: bold; } "
            "QComboBox QAbstractItemView { background-color: #1E293B; color: #FFFFFF; selection-background-color: #0284C7; }"
        )
        form_layout.addRow("Gider Türü *:", self.combo_expense_cat)

        # 2. Gider Tarihi
        today = datetime.today()
        self.date_expense = QDateEdit()
        self.date_expense.setCalendarPopup(True)
        self.date_expense.setDisplayFormat("dd.MM.yyyy")
        self.date_expense.setDate(QDate(today.year, today.month, today.day))
        self.date_expense.setStyleSheet("background-color: #1E293B; padding: 6px 10px; border-radius: 6px;")
        if self.date_expense.calendarWidget():
            self.date_expense.calendarWidget().setGridVisible(True)
        form_layout.addRow("Gider Tarihi *:", self.date_expense)

        # 3. Tutar Girişi
        self.spin_expense_amount = QDoubleSpinBox()
        self.spin_expense_amount.setRange(0.01, 999999999.00)
        self.spin_expense_amount.setDecimals(2)
        self.spin_expense_amount.setSuffix(" TL")
        self.spin_expense_amount.setValue(0.00)
        self.spin_expense_amount.setStyleSheet(
            "background-color: #1E293B; color: #F59E0B; font-size: 15px; font-weight: bold; padding: 6px 10px; border-radius: 6px;"
        )
        form_layout.addRow("Harcama Tutarı *:", self.spin_expense_amount)

        # 4. Açıklama / Belge / Not
        self.input_expense_desc = QLineEdit()
        self.input_expense_desc.setPlaceholderText("Açıklama, fiş/fatura detayı, plaka veya not (isteğe bağlı)...")
        self.input_expense_desc.setStyleSheet("background-color: #1E293B; padding: 6px 10px; border-radius: 6px;")
        self.input_expense_desc.returnPressed.connect(self._save_expense)
        form_layout.addRow("Açıklama / Not:", self.input_expense_desc)

        # Buton ve Durum Bildirimi
        save_layout = QHBoxLayout()
        self.lbl_save_status = QLabel("")
        self.lbl_save_status.setStyleSheet("color: #10B981; font-weight: bold; font-size: 11px;")

        self.btn_save_expense = QPushButton("💾 Gideri Kaydet (Yerel & Dropbox)")
        self.btn_save_expense.setObjectName("successBtn")
        self.btn_save_expense.setStyleSheet(
            "background-color: #10B981; color: white; padding: 8px 24px; font-size: 13px; font-weight: bold; border-radius: 6px;"
        )
        self.btn_save_expense.clicked.connect(self._save_expense)

        save_layout.addWidget(self.lbl_save_status)
        save_layout.addStretch()
        save_layout.addWidget(self.btn_save_expense)
        form_layout.addRow("", save_layout)

        layout.addWidget(form_card)

        # Alt Bölüm: Son Eklenen Giderler Tablosu
        lbl_recent = QLabel("📋 Son Eklenen Gider Kayıtları (En Yeni İlk)")
        lbl_recent.setStyleSheet("font-size: 12px; font-weight: bold; color: #E2E8F0; margin-top: 4px;")
        layout.addWidget(lbl_recent)

        self.table_recent_expenses = QTableWidget()
        self.table_recent_expenses.setColumnCount(5)
        self.table_recent_expenses.setHorizontalHeaderLabels(["Tarih", "Gider Türü", "Tutar", "Açıklama / Not", "İşlem"])
        self.table_recent_expenses.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_recent_expenses.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_recent_expenses.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_recent_expenses.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table_recent_expenses.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table_recent_expenses.setColumnWidth(4, 90)
        self.table_recent_expenses.verticalHeader().setVisible(False)
        self.table_recent_expenses.setAlternatingRowColors(True)
        self.table_recent_expenses.setStyleSheet(
            "QTableWidget { background-color: #0F172A; border: 1px solid #334155; border-radius: 6px; } "
            "QTableWidget::item { padding: 6px 10px; }"
        )
        layout.addWidget(self.table_recent_expenses, 1)

    def _refresh_categories_combo(self):
        current_cat = self.combo_expense_cat.currentText()
        categories = self.expense_db.get_categories()
        self.combo_expense_cat.clear()
        self.combo_expense_cat.addItems(categories)
        if current_cat in categories:
            self.combo_expense_cat.setCurrentText(current_cat)

    def _refresh_recent_expenses(self):
        expenses = self.expense_db.get_expenses()
        self.table_recent_expenses.setRowCount(len(expenses))

        for row, exp in enumerate(expenses):
            exp_id = str(exp.get("id", ""))

            # 0: Tarih
            dt_str = str(exp.get("date", ""))
            parsed = parse_date_obj(dt_str)
            disp_date = parsed.strftime("%d.%m.%Y") if parsed else dt_str
            item_d = QTableWidgetItem(disp_date)
            item_d.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_recent_expenses.setItem(row, 0, item_d)

            # 1: Kategori
            item_c = QTableWidgetItem(str(exp.get("category", "")))
            item_c.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_recent_expenses.setItem(row, 1, item_c)

            # 2: Tutar
            amt = float(exp.get("amount") or 0.0)
            item_a = QTableWidgetItem(f"{amt:,.2f} TL")
            item_a.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_a.setForeground(Qt.GlobalColor.yellow)
            self.table_recent_expenses.setItem(row, 2, item_a)

            # 3: Açıklama
            desc = str(exp.get("description", ""))
            item_desc = QTableWidgetItem(desc)
            self.table_recent_expenses.setItem(row, 3, item_desc)

            # 4: Sil Butonu
            btn_del = QPushButton("🗑️ Sil")
            btn_del.setStyleSheet("padding: 3px 8px; font-size: 11px; background-color: #EF4444; color: #FFFFFF;")
            btn_del.clicked.connect(lambda _, eid=exp_id: self._delete_expense(eid))
            self.table_recent_expenses.setCellWidget(row, 4, btn_del)

    def _save_expense(self):
        cat = self.combo_expense_cat.currentText().strip()
        if not cat:
            QMessageBox.warning(self, "Uyarı", "Lütfen bir gider türü seçiniz.")
            return

        amount = self.spin_expense_amount.value()
        if amount <= 0:
            QMessageBox.warning(self, "Uyarı", "Lütfen sıfırdan büyük geçerli bir harcama tutarı giriniz.")
            return

        qdate = self.date_expense.date()
        date_str = f"{qdate.year():04d}-{qdate.month():02d}-{qdate.day():02d}"
        desc = self.input_expense_desc.text().strip()

        expense_data = {
            "category": cat,
            "date": date_str,
            "amount": amount,
            "description": desc,
        }

        success = self.expense_db.add_expense(expense_data)
        if success:
            if self.dropbox_sync:
                self.dropbox_sync.trigger_instant_upload_expenses()

            self.spin_expense_amount.setValue(0.00)
            self.input_expense_desc.clear()
            self.lbl_save_status.setText(f"✓ {cat} ({amount:,.2f} TL) kaydedildi ve Dropbox'a yüklendi.")
            self._refresh_recent_expenses()
            self._refresh_categories_table()
            self._calculate_summary()
        else:
            QMessageBox.critical(self, "Hata", "Gider kaydedilirken bir hata oluştu.")

    def _delete_expense(self, exp_id: str):
        reply = QMessageBox.question(
            self,
            "Gider Silme Onayı",
            "Bu harcama kaydını silmek istediğinize emin misiniz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.expense_db.delete_expense(exp_id)
            if self.dropbox_sync:
                self.dropbox_sync.trigger_instant_upload_expenses()
            self._refresh_recent_expenses()
            self._refresh_categories_table()
            self._calculate_summary()

    # =========================================================================
    # SEKME 3: GELİR - GİDER ÖZETİ (DASHBOARD)
    # =========================================================================
    def _setup_tab_summary(self):
        layout = QVBoxLayout(self.tab_sum)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # 1. Filtreleme ve Tarih Çubuğu
        filter_frame = QFrame()
        filter_frame.setStyleSheet(
            "background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; padding: 8px 12px;"
        )
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)

        lbl_from = QLabel("Başlangıç:")
        lbl_from.setStyleSheet("font-weight: bold; color: #94A3B8; font-size: 11px;")
        filter_layout.addWidget(lbl_from)

        today = datetime.today()
        first_day_of_month = datetime(today.year, today.month, 1)

        self.dash_date_from = QDateEdit()
        self.dash_date_from.setCalendarPopup(True)
        self.dash_date_from.setDisplayFormat("dd.MM.yyyy")
        self.dash_date_from.setDate(QDate(first_day_of_month.year, first_day_of_month.month, first_day_of_month.day))
        self.dash_date_from.setStyleSheet("background-color: #1E293B; padding: 4px 8px;")
        filter_layout.addWidget(self.dash_date_from)

        lbl_to = QLabel("Bitiş:")
        lbl_to.setStyleSheet("font-weight: bold; color: #94A3B8; font-size: 11px;")
        filter_layout.addWidget(lbl_to)

        self.dash_date_to = QDateEdit()
        self.dash_date_to.setCalendarPopup(True)
        self.dash_date_to.setDisplayFormat("dd.MM.yyyy")
        self.dash_date_to.setDate(QDate(today.year, today.month, today.day))
        self.dash_date_to.setStyleSheet("background-color: #1E293B; padding: 4px 8px;")
        filter_layout.addWidget(self.dash_date_to)

        # Hızlı Aralık Butonları
        btn_this_month = QPushButton("Bu Ay")
        btn_this_month.setStyleSheet("padding: 4px 8px; font-size: 11px; background-color: #334155;")
        btn_this_month.clicked.connect(self._preset_this_month)
        filter_layout.addWidget(btn_this_month)

        btn_last_30 = QPushButton("Son 30 Gün")
        btn_last_30.setStyleSheet("padding: 4px 8px; font-size: 11px; background-color: #334155;")
        btn_last_30.clicked.connect(self._preset_last_30_days)
        filter_layout.addWidget(btn_last_30)

        btn_this_year = QPushButton("Bu Yıl")
        btn_this_year.setStyleSheet("padding: 4px 8px; font-size: 11px; background-color: #334155;")
        btn_this_year.clicked.connect(self._preset_this_year)
        filter_layout.addWidget(btn_this_year)

        btn_all_time = QPushButton("Tüm Zamanlar")
        btn_all_time.setStyleSheet("padding: 4px 8px; font-size: 11px; background-color: #334155;")
        btn_all_time.clicked.connect(self._preset_all_time)
        filter_layout.addWidget(btn_all_time)

        btn_calc = QPushButton("🔄 Hesapla")
        btn_calc.setStyleSheet("background-color: #0284C7; color: white; font-weight: bold; padding: 5px 14px;")
        btn_calc.clicked.connect(self._calculate_summary)
        filter_layout.addWidget(btn_calc)

        layout.addWidget(filter_frame)

        # 2. Üç Büyük Özet Gösterge Kartı (Gelir, Gider, Net Durum)
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)

        # Kart 1: Toplam Gelir
        self.card_income_frame = QFrame()
        self.card_income_frame.setStyleSheet(
            "QFrame { background-color: #064E3B; border: 1px solid #059669; border-radius: 8px; padding: 12px; }"
        )
        c1_layout = QVBoxLayout(self.card_income_frame)
        c1_layout.setSpacing(4)
        c1_title = QLabel("📈 TOPLAM GELİR (TAHSİLAT)")
        c1_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #A7F3D0; text-transform: uppercase;")
        self.lbl_income_val = QLabel("0.00 TL")
        self.lbl_income_val.setStyleSheet("font-size: 20px; font-weight: 800; color: #10B981;")
        self.lbl_income_sub = QLabel("0 Adet Ödenmiş Fatura/Nakit")
        self.lbl_income_sub.setStyleSheet("font-size: 11px; color: #6EE7B7;")
        c1_layout.addWidget(c1_title)
        c1_layout.addWidget(self.lbl_income_val)
        c1_layout.addWidget(self.lbl_income_sub)
        cards_layout.addWidget(self.card_income_frame)

        # Kart 2: Toplam Gider
        self.card_expense_frame = QFrame()
        self.card_expense_frame.setStyleSheet(
            "QFrame { background-color: #451A03; border: 1px solid #D97706; border-radius: 8px; padding: 12px; }"
        )
        c2_layout = QVBoxLayout(self.card_expense_frame)
        c2_layout.setSpacing(4)
        c2_title = QLabel("📉 TOPLAM GİDER (HARCAMA)")
        c2_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #FDE68A; text-transform: uppercase;")
        self.lbl_expense_val = QLabel("0.00 TL")
        self.lbl_expense_val.setStyleSheet("font-size: 20px; font-weight: 800; color: #F59E0B;")
        self.lbl_expense_sub = QLabel("0 Adet Harcama Kaydı")
        self.lbl_expense_sub.setStyleSheet("font-size: 11px; color: #FCD34D;")
        c2_layout.addWidget(c2_title)
        c2_layout.addWidget(self.lbl_expense_val)
        c2_layout.addWidget(self.lbl_expense_sub)
        cards_layout.addWidget(self.card_expense_frame)

        # Kart 3: Net Durum (Kâr / Zarar)
        self.card_net_frame = QFrame()
        self.card_net_frame.setStyleSheet(
            "QFrame { background-color: #064E3B; border: 1px solid #10B981; border-radius: 8px; padding: 12px; }"
        )
        c3_layout = QVBoxLayout(self.card_net_frame)
        c3_layout.setSpacing(4)
        self.lbl_net_title = QLabel("⚖️ NET DURUM (KÂR / ZARAR)")
        self.lbl_net_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #E2E8F0; text-transform: uppercase;")
        self.lbl_net_val = QLabel("0.00 TL")
        self.lbl_net_val.setStyleSheet("font-size: 20px; font-weight: 800; color: #10B981;")
        self.lbl_net_sub = QLabel("Dengede")
        self.lbl_net_sub.setStyleSheet("font-size: 11px; color: #CBD5E1;")
        c3_layout.addWidget(self.lbl_net_title)
        c3_layout.addWidget(self.lbl_net_val)
        c3_layout.addWidget(self.lbl_net_sub)
        cards_layout.addWidget(self.card_net_frame)

        layout.addLayout(cards_layout)

        # 3. Görsel Finansal Oran Göstergesi (Gelir vs Gider Dağılım Çubuğu)
        ratio_frame = QFrame()
        ratio_frame.setStyleSheet("background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; padding: 10px 14px;")
        ratio_layout = QVBoxLayout(ratio_frame)
        ratio_layout.setSpacing(6)

        ratio_header = QHBoxLayout()
        self.lbl_ratio_text = QLabel("Finansal Dağılım Oranı (Gelir vs Gider):")
        self.lbl_ratio_text.setStyleSheet("font-size: 11px; font-weight: bold; color: #CBD5E1;")
        self.lbl_ratio_percent = QLabel("Gelir: %100  |  Gider: %0")
        self.lbl_ratio_percent.setStyleSheet("font-size: 11px; font-weight: bold; color: #38BDF8;")
        ratio_header.addWidget(self.lbl_ratio_text)
        ratio_header.addStretch()
        ratio_header.addWidget(self.lbl_ratio_percent)
        ratio_layout.addLayout(ratio_header)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(50)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #F59E0B; border-radius: 6px; border: none; } "
            "QProgressBar::chunk { background-color: #10B981; border-radius: 6px; }"
        )
        ratio_layout.addWidget(self.progress_bar)
        layout.addWidget(ratio_frame)

        # 4. Kategori Bazlı Gider Dağılımı Tablosu
        lbl_tbl_title = QLabel("📊 Kategori Bazlı Harcama Dağılımı (Seçilen Tarih Aralığı)")
        lbl_tbl_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #E2E8F0; margin-top: 4px;")
        layout.addWidget(lbl_tbl_title)

        self.table_breakdown = QTableWidget()
        self.table_breakdown.setColumnCount(4)
        self.table_breakdown.setHorizontalHeaderLabels(["Gider Kategorisi", "Harcama Adedi", "Toplam Tutar", "Giderdeki Payı"])
        self.table_breakdown.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_breakdown.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_breakdown.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_breakdown.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_breakdown.verticalHeader().setVisible(False)
        self.table_breakdown.setAlternatingRowColors(True)
        self.table_breakdown.setStyleSheet(
            "QTableWidget { background-color: #0F172A; border: 1px solid #334155; border-radius: 6px; } "
            "QTableWidget::item { padding: 6px 10px; }"
        )
        layout.addWidget(self.table_breakdown, 1)

    def _preset_this_month(self):
        today = datetime.today()
        first_day = datetime(today.year, today.month, 1)
        self.dash_date_from.setDate(QDate(first_day.year, first_day.month, first_day.day))
        self.dash_date_to.setDate(QDate(today.year, today.month, today.day))
        self._calculate_summary()

    def _preset_last_30_days(self):
        today = datetime.today()
        past = today - timedelta(days=30)
        self.dash_date_from.setDate(QDate(past.year, past.month, past.day))
        self.dash_date_to.setDate(QDate(today.year, today.month, today.day))
        self._calculate_summary()

    def _preset_this_year(self):
        today = datetime.today()
        first_day = datetime(today.year, 1, 1)
        self.dash_date_from.setDate(QDate(first_day.year, first_day.month, first_day.day))
        self.dash_date_to.setDate(QDate(today.year, today.month, today.day))
        self._calculate_summary()

    def _preset_all_time(self):
        today = datetime.today()
        self.dash_date_from.setDate(QDate(2020, 1, 1))
        self.dash_date_to.setDate(QDate(today.year, today.month, today.day))
        self._calculate_summary()

    def _calculate_summary(self):
        q_from = self.dash_date_from.date()
        q_to = self.dash_date_to.date()
        start_dt = date(q_from.year(), q_from.month(), q_from.day())
        end_dt = date(q_to.year(), q_to.month(), q_to.day())

        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt

        # 1. GELİR HESABI (Ödenmiş Faturalar ve Nakit Tahsilatlar)
        all_invoices = self.db.load_all()
        total_income = 0.0
        income_count = 0

        for inv in all_invoices:
            st = str(inv.get("status", "")).strip().lower()
            if st in ["paid", "ödendi", "odendi"]:
                p_dt = parse_date_obj(inv.get("payment_date")) or parse_date_obj(inv.get("invoice_date"))
                if p_dt and (start_dt <= p_dt <= end_dt):
                    income_count += 1
                    tot = float(
                        inv.get("total_amount")
                        if inv.get("total_amount") is not None
                        else ((inv.get("tax_excluded_amount") or 0.0) + (inv.get("kdv_amount") or 0.0))
                    )
                    total_income += tot

        # 2. GİDER HESABI (expenses.json)
        expenses_in_range = self.expense_db.get_expenses(start_dt, end_dt)
        total_expense = sum(float(e.get("amount") or 0.0) for e in expenses_in_range)
        expense_count = len(expenses_in_range)

        # 3. NET DURUM HESABI
        net_amount = total_income - total_expense

        # Kartları Güncelle
        self.lbl_income_val.setText(f"{total_income:,.2f} TL")
        self.lbl_income_sub.setText(f"{income_count} Adet Ödenmiş İşlem ({start_dt.strftime('%d.%m')} - {end_dt.strftime('%d.%m.%Y')})")

        self.lbl_expense_val.setText(f"{total_expense:,.2f} TL")
        self.lbl_expense_sub.setText(f"{expense_count} Adet Harcama Kaydı")

        if net_amount >= 0:
            # KÂRDA (Yeşil)
            self.card_net_frame.setStyleSheet(
                "QFrame { background-color: #064E3B; border: 2px solid #10B981; border-radius: 8px; padding: 12px; }"
            )
            self.lbl_net_title.setText("⚖️ NET DURUM (KÂRDA)")
            self.lbl_net_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #A7F3D0;")
            self.lbl_net_val.setText(f"+{net_amount:,.2f} TL")
            self.lbl_net_val.setStyleSheet("font-size: 20px; font-weight: 800; color: #10B981;")
            margin = (net_amount / total_income * 100.0) if total_income > 0 else 100.0
            self.lbl_net_sub.setText(f"✓ Kâr Marjı: %{margin:.1f}")
            self.lbl_net_sub.setStyleSheet("font-size: 11px; color: #6EE7B7; font-weight: bold;")
        else:
            # ZARARDA (Kırmızı)
            self.card_net_frame.setStyleSheet(
                "QFrame { background-color: #450A0A; border: 2px solid #EF4444; border-radius: 8px; padding: 12px; }"
            )
            self.lbl_net_title.setText("⚖️ NET DURUM (ZARARDA)")
            self.lbl_net_title.setStyleSheet("font-size: 11px; font-weight: 800; color: #FECACA;")
            self.lbl_net_val.setText(f"{net_amount:,.2f} TL")
            self.lbl_net_val.setStyleSheet("font-size: 20px; font-weight: 800; color: #EF4444;")
            self.lbl_net_sub.setText("⚠️ Giderler toplam geliri aştı!")
            self.lbl_net_sub.setStyleSheet("font-size: 11px; color: #FCA5A5; font-weight: bold;")

        # Oran Çubuğunu Güncelle
        grand_total = total_income + total_expense
        if grand_total > 0:
            income_pct = int((total_income / grand_total) * 100)
            expense_pct = 100 - income_pct
            self.progress_bar.setValue(income_pct)
            self.lbl_ratio_percent.setText(f"Gelir: %{income_pct} (Yeşil)  |  Gider: %{expense_pct} (Turuncu)")
        else:
            self.progress_bar.setValue(50)
            self.lbl_ratio_percent.setText("Gelir: %0  |  Gider: %0")

        # 4. Kategori Bazlı Dağılım Tablosu
        cat_counts: Dict[str, int] = {}
        cat_totals: Dict[str, float] = {}
        for e in expenses_in_range:
            c = str(e.get("category", "")).strip() or "Diğer"
            cat_counts[c] = cat_counts.get(c, 0) + 1
            cat_totals[c] = cat_totals.get(c, 0.0) + float(e.get("amount") or 0.0)

        sorted_cats = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)
        self.table_breakdown.setRowCount(len(sorted_cats))

        for row, (c_name, c_tot) in enumerate(sorted_cats):
            # 0: Kategori
            item_c = QTableWidgetItem(c_name)
            item_c.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_breakdown.setItem(row, 0, item_c)

            # 1: Adet
            cnt = cat_counts.get(c_name, 0)
            item_cnt = QTableWidgetItem(f"{cnt} Harcama")
            item_cnt.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_cnt.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_breakdown.setItem(row, 1, item_cnt)

            # 2: Toplam Tutar
            item_t = QTableWidgetItem(f"{c_tot:,.2f} TL")
            item_t.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_t.setForeground(Qt.GlobalColor.yellow)
            item_t.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_breakdown.setItem(row, 2, item_t)

            # 3: Gider Payı (%)
            share = (c_tot / total_expense * 100.0) if total_expense > 0 else 0.0
            item_s = QTableWidgetItem(f"%{share:.1f}")
            item_s.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_s.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_breakdown.setItem(row, 3, item_s)






class GiderYonetimiDialog(BaseResponsiveDialog):
    """Gider Yönetimi diyalog penceresi sarmalayıcısı (Modal diyalog ihtiyacı için)."""

    def __init__(self, db, expense_db: Optional[ExpenseDatabase] = None, dropbox_sync=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Gider Yönetimi & Gelir - Gider Özeti")
        self.setMinimumWidth(860)
        self.setMinimumHeight(640)
        dlg_layout = QVBoxLayout(self)
        dlg_layout.setContentsMargins(10, 10, 10, 10)
        self.widget = GiderYonetimiWidget(db, expense_db, dropbox_sync, parent=self)
        dlg_layout.addWidget(self.widget, 1)

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch()
        btn_close = QPushButton("Kapat")
        btn_close.setObjectName("secondaryBtn")
        btn_close.setStyleSheet("padding: 7px 20px; font-weight: bold;")
        btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(btn_close)
        dlg_layout.addLayout(bottom_layout)
