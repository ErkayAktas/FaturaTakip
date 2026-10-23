from datetime import date, datetime
from typing import Any, Dict, Optional
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCalendarWidget,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
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

