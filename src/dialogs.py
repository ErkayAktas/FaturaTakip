from datetime import date, datetime
from typing import Any, Dict, Optional
from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import (
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
    QSpinBox,
    QVBoxLayout,
)
from src.holiday_service import holiday_service
from src.styles import COLORS


class VadeGirisDialog(QDialog):
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

        self.setWindowTitle("Vade Belirle - " + str(invoice.get("invoice_number", "")))
        self.setMinimumWidth(480)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

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

        amount_val = float(self.invoice.get("amount", 0.0))
        currency = str(self.invoice.get("currency", "TL"))
        amount_lbl = QLabel(f"{amount_val:,.2f} {currency}")
        amount_lbl.setStyleSheet("font-weight: bold; color: #34D399; font-size: 14px;")

        info_layout.addRow("Şirket İsmi:", company_lbl)
        info_layout.addRow("Fatura No:", inv_no_lbl)
        info_layout.addRow("Kesim Tarihi:", date_lbl)
        info_layout.addRow("Fatura Tutarı:", amount_lbl)

        layout.addWidget(info_frame)

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
        self.work_days_spin.setValue(15)  # Varsayılan 15 iş günü
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

        # Butonlar
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setObjectName("secondaryBtn")
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("✓ Kaydet ve Tüm Faturalara Taşı")
        self.save_btn.setObjectName("successBtn")
        self.save_btn.clicked.connect(self._on_save)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        # İlk hesaplamayı çalıştır
        self._recalculate_preview()

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
        }


class OdemeGirisDialog(QDialog):
    """
    Sekme 2 ve Sekme 3 için Ödeme Durumu Belirleme ve Düzenleme Pop-up'ı.
    - Ödenmemiş faturayı Ödendi statüsüne alma (ödeme tarihi ve tutarı girerek)
    - Yanlış girilmiş durumları tekrar Ödenmedi (Aktif) veya düzeltilmiş tutara çevirme
    """

    def __init__(self, invoice: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.invoice = invoice
        self.setWindowTitle(f"Fatura Durumu Düzenle - {invoice.get('invoice_number')}")
        self.setMinimumWidth(460)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        # Başlık
        title_lbl = QLabel("Fatura Ödeme Durumu ve Bilgileri")
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
        info_layout.addRow("Fatura No:", QLabel(str(self.invoice.get("invoice_number", "-"))))
        
        amt = float(self.invoice.get("amount", 0.0))
        cur = str(self.invoice.get("currency", "TL"))
        amt_lbl = QLabel(f"{amt:,.2f} {cur}")
        amt_lbl.setStyleSheet("color: #34D399; font-weight: bold;")
        info_layout.addRow("Fatura Tutarı:", amt_lbl)

        # Son Ödeme Tarihi (Vade) - Kullanıcı tarafından güncellenebilir
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

        info_layout.addRow("Son Ödeme Tarihi (Vade):", self.due_date_edit)

        layout.addWidget(info_frame)

        # Durum Seçim Grubu
        status_box = QGroupBox("Ödeme Durumu")
        status_box.setStyleSheet(f"font-weight: bold; color: {COLORS['text_primary']};")
        status_layout = QVBoxLayout(status_box)

        self.radio_paid = QRadioButton("Ödendi")
        self.radio_paid.setStyleSheet("color: #10B981; font-weight: bold;")
        self.radio_unpaid = QRadioButton("Ödenmedi (Aktif)")
        self.radio_unpaid.setStyleSheet("color: #F59E0B; font-weight: bold;")

        # Mevcut durum
        current_status = self.invoice.get("status")
        if current_status == "paid":
            self.radio_paid.setChecked(True)
        else:
            self.radio_unpaid.setChecked(True)

        self.radio_paid.toggled.connect(self._toggle_payment_fields)

        status_layout.addWidget(self.radio_paid)
        status_layout.addWidget(self.radio_unpaid)
        layout.addWidget(status_box)

        # Ödeme Detay Alanları
        self.payment_frame = QFrame()
        self.payment_frame.setStyleSheet(
            f"background-color: #1E293B; border: 1px solid {COLORS['border']}; border-radius: 8px; padding: 12px;"
        )
        pay_form = QFormLayout(self.payment_frame)
        pay_form.setSpacing(10)

        # Ödeme Tarihi
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

        # Ödenen Tutar
        self.paid_amount_spin = QDoubleSpinBox()
        self.paid_amount_spin.setRange(0.0, 999999999.0)
        self.paid_amount_spin.setDecimals(2)
        self.paid_amount_spin.setSuffix(f" {cur}")
        existing_paid_amt = self.invoice.get("paid_amount")
        if existing_paid_amt is not None:
            self.paid_amount_spin.setValue(float(existing_paid_amt))
        else:
            self.paid_amount_spin.setValue(amt)

        pay_form.addRow("Ödeme Tarihi:", self.payment_date_edit)
        pay_form.addRow("Ödenen Tutar:", self.paid_amount_spin)

        layout.addWidget(self.payment_frame)

        # Butonlar
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.cancel_btn = QPushButton("İptal")
        self.cancel_btn.setObjectName("secondaryBtn")
        self.cancel_btn.clicked.connect(self.reject)

        self.save_btn = QPushButton("Değişiklikleri Kaydet")
        self.save_btn.setObjectName("successBtn")
        self.save_btn.clicked.connect(self.accept)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)

        self._toggle_payment_fields()

    def _toggle_payment_fields(self):
        is_paid = self.radio_paid.isChecked()
        self.payment_frame.setEnabled(is_paid)
        self.payment_frame.setVisible(is_paid)

    def get_result(self) -> Dict[str, Any]:
        qdate_due = self.due_date_edit.date()
        due_date_str = f"{qdate_due.year():04d}-{qdate_due.month():02d}-{qdate_due.day():02d}"

        result: Dict[str, Any] = {
            "due_date": due_date_str,
        }

        if self.radio_paid.isChecked():
            qdate = self.payment_date_edit.date()
            pay_date_str = f"{qdate.year():04d}-{qdate.month():02d}-{qdate.day():02d}"
            result.update({
                "status": "paid",
                "payment_date": pay_date_str,
                "paid_amount": round(self.paid_amount_spin.value(), 2),
            })
        else:
            result.update({
                "status": "active",
                "payment_date": None,
                "paid_amount": None,
            })
        return result
