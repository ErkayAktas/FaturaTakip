import json
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.backup_manager import backup_manager
from src.database import get_app_base_dir

logger = logging.getLogger(__name__)


def format_currency(val: Any) -> str:
    """Para formatlama (1,234.56 TL)."""
    try:
        return f"{float(val or 0.0):,.2f} TL"
    except Exception:
        return str(val)


class DiffBadge(QLabel):
    """Fark türünü görselleştiren renkli durum rozeti."""

    def __init__(self, diff_type: str, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if diff_type == "deleted":
            self.setText("🗑️ Silinmiş (Yedekte Var)")
            self.setStyleSheet(
                "background-color: #064E3B; color: #10B981; border: 1px solid #059669; "
                "font-weight: 800; font-size: 11px; padding: 2px 10px; border-radius: 4px;"
            )
        elif diff_type == "modified":
            self.setText("✏️ Değiştirilmiş (Farklı Veri)")
            self.setStyleSheet(
                "background-color: #451A03; color: #F59E0B; border: 1px solid #D97706; "
                "font-weight: 800; font-size: 11px; padding: 2px 10px; border-radius: 4px;"
            )
        else:
            self.setText("➕ Yeni (Sadece Güncelde)")
            self.setStyleSheet(
                "background-color: #1E293B; color: #94A3B8; border: 1px solid #475569; "
                "font-weight: 800; font-size: 11px; padding: 2px 10px; border-radius: 4px;"
            )


class VersionHistoryPage(QWidget):
    """
    Sürüm Geçmişi ve Fark Analizi (Diff & Selective Restore) Sayfası:
    - backups/infos/ ve backups/expenses/ içindeki geçmiş sürümleri listeler.
    - Seçilen yedek ile mevcut veritabanı arasında otomatik fark analizi (diff) yapar.
    - Silinmiş, değiştirilmiş ve yeni kayıtları renkli rozetlerle ve detaylarıyla sunar.
    - Checkbox ile seçilen belirli kayıtları aktif veritabanına seçici olarak geri yükler.
    """

    def __init__(self, db, expense_db=None, dropbox_sync=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.expense_db = expense_db
        self.dropbox_sync = dropbox_sync
        self.base_dir = getattr(db, "base_dir", None) or get_app_base_dir()

        self.current_category = "infos"  # "infos" veya "expenses"
        self.current_diff_items: List[Dict[str, Any]] = []

        self._setup_ui()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 12, 14, 12)
        root_layout.setSpacing(10)

        # 1. ÜST KONTROL PANELİ (Control Card)
        ctrl_card = QFrame()
        ctrl_card.setObjectName("versionHistoryControlCard")
        ctrl_card.setStyleSheet(
            "QFrame#versionHistoryControlCard { background-color: #0F172A; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; }"
            "QLabel { border: none; background: transparent; }"
        )
        ctrl_vbox = QVBoxLayout(ctrl_card)
        ctrl_vbox.setContentsMargins(0, 0, 0, 0)
        ctrl_vbox.setSpacing(10)

        # Satır 1: Başlık, Kategori Geçişi (Toggle Buttons) ve Sürüm Seçici
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(12)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)
        lbl_title = QLabel("🕒 SÜRÜM GEÇMİŞİ & SEÇİCİ GERİ YÜKLEME")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: 800; color: #FFFFFF; letter-spacing: 0.5px;")
        lbl_sub = QLabel("Yedek sürümleri aktif verilerle karşılaştırın, farkları inceleyin ve dilediğiniz kayıtları geri yükleyin.")
        lbl_sub.setStyleSheet("font-size: 11px; color: #94A3B8;")
        title_vbox.addWidget(lbl_title)
        title_vbox.addWidget(lbl_sub)
        row1_layout.addLayout(title_vbox, 1)

        # Kategori Butonları (Segmented Toggle)
        self.btn_cat_infos = QPushButton("📄 Gelir / Faturalar (infos.json)")
        self.btn_cat_infos.setCheckable(True)
        self.btn_cat_infos.setChecked(True)
        self.btn_cat_infos.clicked.connect(lambda: self._set_category("infos"))

        self.btn_cat_expenses = QPushButton("📊 Giderler (expenses.json)")
        self.btn_cat_expenses.setCheckable(True)
        self.btn_cat_expenses.clicked.connect(lambda: self._set_category("expenses"))

        self.cat_group = QButtonGroup(self)
        self.cat_group.addButton(self.btn_cat_infos)
        self.cat_group.addButton(self.btn_cat_expenses)
        self.cat_group.setExclusive(True)

        cat_btn_box = QHBoxLayout()
        cat_btn_box.setSpacing(0)
        cat_btn_box.addWidget(self.btn_cat_infos)
        cat_btn_box.addWidget(self.btn_cat_expenses)
        self._update_category_buttons_style()
        row1_layout.addLayout(cat_btn_box)

        ctrl_vbox.addLayout(row1_layout)

        # Satır 2: Sürüm Dropdown Seçici + Özet Rozetleri + Filtre
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(12)

        lbl_select_ver = QLabel("📁 Karşılaştırılacak Sürüm:")
        lbl_select_ver.setStyleSheet("font-weight: bold; font-size: 12px; color: #E2E8F0;")
        row2_layout.addWidget(lbl_select_ver)

        self.combo_versions = QComboBox()
        self.combo_versions.setMinimumWidth(340)
        self.combo_versions.setStyleSheet(
            "QComboBox { background-color: #1E293B; color: #FFFFFF; font-weight: bold; padding: 6px 12px; border: 1px solid #334155; border-radius: 6px; } "
            "QComboBox::drop-down { border: none; } "
            "QComboBox QAbstractItemView { background-color: #1E293B; color: #FFFFFF; selection-background-color: #0284C7; }"
        )
        self.combo_versions.currentIndexChanged.connect(self._on_version_selected)
        row2_layout.addWidget(self.combo_versions)

        self.btn_refresh_snapshots = QPushButton("🔄")
        self.btn_refresh_snapshots.setToolTip("Yedek sürüm listesini yenile")
        self.btn_refresh_snapshots.setStyleSheet("background-color: #1E293B; color: #38BDF8; font-weight: bold; padding: 6px 10px; border: 1px solid #334155; border-radius: 6px;")
        self.btn_refresh_snapshots.clicked.connect(self._populate_versions_combo)
        row2_layout.addWidget(self.btn_refresh_snapshots)

        row2_layout.addStretch()

        # Özet Bilgi Rozetleri (Badges)
        self.badge_deleted = QLabel("Silinmiş: 0")
        self.badge_deleted.setStyleSheet(
            "background-color: #064E3B; color: #10B981; font-weight: 800; font-size: 11px; padding: 4px 10px; border-radius: 4px; border: 1px solid #059669;"
        )
        self.badge_modified = QLabel("Değiştirilmiş: 0")
        self.badge_modified.setStyleSheet(
            "background-color: #451A03; color: #F59E0B; font-weight: 800; font-size: 11px; padding: 4px 10px; border-radius: 4px; border: 1px solid #D97706;"
        )
        self.badge_total_diff = QLabel("Toplam Fark: 0")
        self.badge_total_diff.setStyleSheet(
            "background-color: #1E293B; color: #38BDF8; font-weight: 800; font-size: 11px; padding: 4px 10px; border-radius: 4px; border: 1px solid #0284C7;"
        )

        row2_layout.addWidget(self.badge_deleted)
        row2_layout.addWidget(self.badge_modified)
        row2_layout.addWidget(self.badge_total_diff)

        # Filtre Checkbox: Sadece Güncelde Olanları Göster
        self.chk_show_only_active = QCheckBox("Sadece Güncelde Olanları da Göster")
        self.chk_show_only_active.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 600;")
        self.chk_show_only_active.setToolTip("Yedekte bulunmayıp sadece güncel veritabanında var olan yeni kayıtları listeye dahil eder.")
        self.chk_show_only_active.setChecked(False)
        self.chk_show_only_active.toggled.connect(self._compute_and_render_diff)
        row2_layout.addWidget(self.chk_show_only_active)

        ctrl_vbox.addLayout(row2_layout)
        root_layout.addWidget(ctrl_card)

        # 2. SEÇİM VE EYLEM ÇUBUĞU (Action Bar)
        action_bar = QFrame()
        action_bar.setStyleSheet(
            "QFrame { background-color: #1E293B; border: 1px solid #334155; border-radius: 6px; padding: 4px 8px; }"
            "QLabel { border: none; background: transparent; }"
        )
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(10)

        self.btn_select_all = QPushButton("☑️ Tümünü Seç")
        self.btn_select_all.setStyleSheet("background-color: #0F172A; color: #E2E8F0; font-weight: bold; font-size: 11px; padding: 5px 12px; border-radius: 4px; border: 1px solid #334155;")
        self.btn_select_all.clicked.connect(self._select_all_diffs)
        action_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton("⬜ Seçimi Kaldır")
        self.btn_deselect_all.setStyleSheet("background-color: #0F172A; color: #94A3B8; font-weight: bold; font-size: 11px; padding: 5px 12px; border-radius: 4px; border: 1px solid #334155;")
        self.btn_deselect_all.clicked.connect(self._deselect_all_diffs)
        action_layout.addWidget(self.btn_deselect_all)

        self.lbl_selected_summary = QLabel("0 kayıt seçildi")
        self.lbl_selected_summary.setStyleSheet("color: #38BDF8; font-weight: bold; font-size: 11px;")
        action_layout.addWidget(self.lbl_selected_summary)

        action_layout.addStretch()

        self.btn_restore_selected = QPushButton("⏪ Seçili Kayıtları Geri Yükle (0)")
        self.btn_restore_selected.setEnabled(False)
        self.btn_restore_selected.setStyleSheet(
            "QPushButton { background-color: #F59E0B; color: #0F172A; font-weight: 800; font-size: 12px; padding: 6px 20px; border-radius: 6px; border: none; } "
            "QPushButton:hover { background-color: #D97706; } "
            "QPushButton:disabled { background-color: #334155; color: #64748B; }"
        )
        self.btn_restore_selected.setToolTip("Seçilen kayıtları aktif veritabanına işler (Diğer mevcut verilerinize dokunmaz).")
        self.btn_restore_selected.clicked.connect(self._restore_selected_diffs)
        action_layout.addWidget(self.btn_restore_selected)

        root_layout.addWidget(action_bar)

        # 3. FARK ANALİZİ TABLOSU (Diff QTableWidget)
        self.table_diff = QTableWidget()
        self.table_diff.setColumnCount(6)
        self.table_diff.setHorizontalHeaderLabels([
            "Seç",
            "Fark Durumu",
            "Kayıt Tanımı / Başlık",
            "Yedekteki Değer",
            "Günceldeki Değer",
            "Değişiklik Detayları (Fark Analizi)",
        ])

        header = self.table_diff.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table_diff.setColumnWidth(0, 50)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        self.table_diff.verticalHeader().setVisible(False)
        self.table_diff.verticalHeader().setDefaultSectionSize(36)
        self.table_diff.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_diff.setAlternatingRowColors(True)
        self.table_diff.setStyleSheet(
            "QTableWidget { background-color: #0F172A; border: 1px solid #334155; border-radius: 6px; } "
            "QTableWidget::item { padding: 4px 8px; color: #F8FAFC; } "
            "QTableWidget::item:selected { background-color: #1E293B; color: #FFFFFF; } "
            "QHeaderView::section { background-color: #1E293B; color: #94A3B8; font-weight: bold; padding: 6px; border: 1px solid #334155; }"
        )
        self.table_diff.itemChanged.connect(self._on_table_item_changed)
        root_layout.addWidget(self.table_diff, 1)

        # 4. BOŞ / FARKSINIZ BİLGİ AFİŞİ (Empty State Banner)
        self.frame_empty_state = QFrame()
        self.frame_empty_state.setStyleSheet(
            "background-color: #0F172A; border: 1px dashed #334155; border-radius: 8px; padding: 30px;"
        )
        empty_layout = QVBoxLayout(self.frame_empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(6)

        self.lbl_empty_icon = QLabel("✅")
        self.lbl_empty_icon.setStyleSheet("font-size: 28px; border: none; background: transparent;")
        self.lbl_empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_empty_msg = QLabel("Seçili sürüm ile mevcut veriler arasında hiçbir fark bulunmuyor.")
        self.lbl_empty_msg.setStyleSheet("font-size: 13px; font-weight: bold; color: #10B981; border: none; background: transparent;")
        self.lbl_empty_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_empty_sub = QLabel("Veritabanınız seçilen yedek noktasıyla birebir aynı durumdadır.")
        self.lbl_empty_sub.setStyleSheet("font-size: 11px; color: #94A3B8; border: none; background: transparent;")
        self.lbl_empty_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_layout.addWidget(self.lbl_empty_icon)
        empty_layout.addWidget(self.lbl_empty_msg)
        empty_layout.addWidget(self.lbl_empty_sub)
        self.frame_empty_state.setVisible(False)
        root_layout.addWidget(self.frame_empty_state)

        # İlk verileri yükle
        self._populate_versions_combo()

    def _update_category_buttons_style(self):
        """Kategori butonlarının aktif/pasif görünümlerini günceller."""
        is_infos = (self.current_category == "infos")
        style_active = "background-color: #0284C7; color: #FFFFFF; font-weight: 800; padding: 6px 14px; border: 1px solid #38BDF8;"
        style_inactive = "background-color: #1E293B; color: #94A3B8; font-weight: bold; padding: 6px 14px; border: 1px solid #334155;"

        self.btn_cat_infos.setStyleSheet(
            f"{style_active if is_infos else style_inactive} border-top-left-radius: 6px; border-bottom-left-radius: 6px;"
        )
        self.btn_cat_expenses.setStyleSheet(
            f"{style_active if not is_infos else style_inactive} border-top-right-radius: 6px; border-bottom-right-radius: 6px;"
        )

    def _set_category(self, cat: str):
        """Kategori geçişi yapar ('infos' veya 'expenses')."""
        if self.current_category != cat:
            self.current_category = cat
            self._update_category_buttons_style()
            self._populate_versions_combo()

    def refresh_page(self):
        """Sayfa açıldığında veya veritabanı yenilendiğinde verileri tazeler."""
        self._populate_versions_combo()

    def _populate_versions_combo(self):
        """Seçili kategoriye ait backups/ klasöründeki yedek dosyalarını ComboBox'a doldurur."""
        self.combo_versions.blockSignals(True)
        self.combo_versions.clear()

        snapshots = backup_manager.list_snapshots(self.current_category)

        if not snapshots:
            self.combo_versions.addItem("⚠️ Henüz kayıtlı yerel sürüm bulunmuyor", "")
            self.combo_versions.setEnabled(False)
        else:
            self.combo_versions.setEnabled(True)
            for s in snapshots:
                text = f"{s['datetime']}  |  {s['item_count']} Kayıt  |  {s['size_str']}  ({s['filename']})"
                self.combo_versions.addItem(text, s["path"])

        self.combo_versions.blockSignals(False)
        self._compute_and_render_diff()

    def _on_version_selected(self, index: int):
        """Yeni bir yedek sürüm seçildiğinde fark analizini baştan hesaplar."""
        self._compute_and_render_diff()

    # --- FARK (DIFF) HESAPLAMA MOTORU ---
    def _compute_and_render_diff(self):
        """Seçilen yedek JSON dosyası ile aktif veritabanını karşılaştırır ve tabloyu çizer."""
        snapshot_path = self.combo_versions.currentData()
        self.current_diff_items = []

        if not snapshot_path or not os.path.exists(snapshot_path):
            self._render_empty_or_no_diff("Yedek dosyası bulunamadı veya henüz sürüm oluşturulmamış.")
            return

        # 1. Yedek Verisini Yükle
        try:
            with open(snapshot_path, "r", encoding="utf-8") as f:
                backup_data = json.load(f)
        except Exception as e:
            logger.error(f"[Diff] Yedek dosyası okunamadı: {e}")
            self._render_empty_or_no_diff("Yedek JSON dosyası ayrıştırılamadı.")
            return

        # 2. Kategoriye Göre Aktif ve Yedek Karşılaştırması
        if self.current_category == "infos":
            self._compute_invoices_diff(backup_data)
        else:
            self._compute_expenses_diff(backup_data)

        # 3. Tabloyu ve Rozetleri Güncelle
        self._render_table()

    def _compute_invoices_diff(self, backup_data: Any):
        """Faturalar (infos.json) için fark analizi."""
        # Aktif faturalar
        active_invoices = self.db.load_all() if self.db else []
        backup_invoices = backup_data if isinstance(backup_data, list) else backup_data.get("invoices", [])

        def get_inv_key(inv: dict) -> str:
            # Benzersiz kimlik: id veya fatura_no veya file_name
            raw_id = str(inv.get("id") or "").strip().upper()
            raw_no = str(inv.get("invoice_number") or "").strip().upper()
            raw_fn = str(inv.get("file_name") or "").strip().lower()
            return raw_id or raw_no or raw_fn

        active_map = {get_inv_key(i): i for i in active_invoices if get_inv_key(i)}
        backup_map = {get_inv_key(i): i for i in backup_invoices if get_inv_key(i)}

        show_active_only = self.chk_show_only_active.isChecked()

        # 1. Silinmiş Kayıtlar (Yedekte var, aktifte yok)
        for b_key, b_inv in backup_map.items():
            if b_key not in active_map:
                inv_no = b_inv.get("invoice_number") or b_inv.get("id") or "Fatura"
                comp = b_inv.get("company_name", "")
                tot = format_currency(b_inv.get("total_amount"))
                self.current_diff_items.append({
                    "diff_type": "deleted",
                    "key": b_key,
                    "title": f"{inv_no} - {comp}",
                    "backup_val": tot,
                    "active_val": "(Silinmiş / Yok)",
                    "details": "Aktif veritabanında bulunmuyor. Yedekten geri eklenebilir.",
                    "backup_record": b_inv,
                    "active_record": None,
                })

        # 2. Değiştirilmiş Kayıtlar (İkisinde de var, alanlar farklı)
        for b_key, b_inv in backup_map.items():
            if b_key in active_map:
                a_inv = active_map[b_key]
                diffs = self._compare_invoice_fields(b_inv, a_inv)
                if diffs:
                    inv_no = b_inv.get("invoice_number") or b_inv.get("id") or "Fatura"
                    comp = b_inv.get("company_name", "")
                    b_tot = format_currency(b_inv.get("total_amount"))
                    a_tot = format_currency(a_inv.get("total_amount"))
                    self.current_diff_items.append({
                        "diff_type": "modified",
                        "key": b_key,
                        "title": f"{inv_no} - {comp}",
                        "backup_val": b_tot,
                        "active_val": a_tot,
                        "details": " | ".join(diffs),
                        "backup_record": b_inv,
                        "active_record": a_inv,
                    })

        # 3. İsteğe bağlı: Sadece Güncelde Olanlar (Aktifte var, yedekte yok)
        if show_active_only:
            for a_key, a_inv in active_map.items():
                if a_key not in backup_map:
                    inv_no = a_inv.get("invoice_number") or a_inv.get("id") or "Fatura"
                    comp = a_inv.get("company_name", "")
                    a_tot = format_currency(a_inv.get("total_amount"))
                    self.current_diff_items.append({
                        "diff_type": "created_in_active",
                        "key": a_key,
                        "title": f"{inv_no} - {comp}",
                        "backup_val": "(Yedekte Yok)",
                        "active_val": a_tot,
                        "details": "Yedek alındıktan sonra sisteme yeni eklenmiş kayıt.",
                        "backup_record": None,
                        "active_record": a_inv,
                    })

    def _compare_invoice_fields(self, b_inv: dict, a_inv: dict) -> List[str]:
        """İki fatura arasındaki alan değişikliklerini inceler."""
        diffs = []

        # Tutar Farkı
        b_tot = float(b_inv.get("total_amount") or 0.0)
        a_tot = float(a_inv.get("total_amount") or 0.0)
        if abs(b_tot - a_tot) > 0.009:
            diffs.append(f"Tutar: {format_currency(a_tot)} → {format_currency(b_tot)}")

        # Ödeme Durumu
        b_paid = bool(b_inv.get("payment_status") or b_inv.get("is_paid"))
        a_paid = bool(a_inv.get("payment_status") or a_inv.get("is_paid"))
        if b_paid != a_paid:
            b_s = "Ödendi" if b_paid else "Bekliyor"
            a_s = "Ödendi" if a_paid else "Bekliyor"
            diffs.append(f"Durum: {a_s} → {b_s}")

        # Vade Tarihi
        b_due = str(b_inv.get("due_date") or "").strip()
        a_due = str(a_inv.get("due_date") or "").strip()
        if b_due != a_due:
            diffs.append(f"Vade: {a_due or 'Yok'} → {b_due or 'Yok'}")

        # Fatura Tarihi
        b_date = str(b_inv.get("invoice_date") or "").strip()
        a_date = str(a_inv.get("invoice_date") or "").strip()
        if b_date != a_date:
            diffs.append(f"Tarih: {a_date or '-'} → {b_date or '-'}")

        # Not / Açıklama
        b_desc = str(b_inv.get("notes") or b_inv.get("description") or "").strip()
        a_desc = str(a_inv.get("notes") or a_inv.get("description") or "").strip()
        if b_desc != a_desc:
            diffs.append(f"Not: '{a_desc}' → '{b_desc}'")

        return diffs

    def _compute_expenses_diff(self, backup_data: Any):
        """Giderler (expenses.json) için fark analizi."""
        active_data = self.expense_db.load_data() if self.expense_db else {}
        active_expenses = active_data.get("expenses", [])
        backup_expenses = backup_data.get("expenses", []) if isinstance(backup_data, dict) else []

        def get_exp_key(exp: dict) -> str:
            raw_id = str(exp.get("id") or "").strip()
            if raw_id:
                return raw_id
            return f"{exp.get('date')}_{exp.get('category')}_{exp.get('amount')}"

        active_map = {get_exp_key(e): e for e in active_expenses}
        backup_map = {get_exp_key(e): e for e in backup_expenses}

        show_active_only = self.chk_show_only_active.isChecked()

        # 1. Silinmiş Giderler (Yedekte var, aktifte yok)
        for b_key, b_exp in backup_map.items():
            if b_key not in active_map:
                cat = b_exp.get("category", "Gider")
                dt = b_exp.get("date", "")
                tot = format_currency(b_exp.get("amount"))
                self.current_diff_items.append({
                    "diff_type": "deleted",
                    "key": b_key,
                    "title": f"{cat} ({dt})",
                    "backup_val": tot,
                    "active_val": "(Silinmiş / Yok)",
                    "details": "Aktif gider listesinde bulunmuyor. Yedekten geri eklenebilir.",
                    "backup_record": b_exp,
                    "active_record": None,
                })

        # 2. Değiştirilmiş Giderler (İkisinde de var, alanlar farklı)
        for b_key, b_exp in backup_map.items():
            if b_key in active_map:
                a_exp = active_map[b_key]
                diffs = self._compare_expense_fields(b_exp, a_exp)
                if diffs:
                    cat = b_exp.get("category", "Gider")
                    dt = b_exp.get("date", "")
                    b_tot = format_currency(b_exp.get("amount"))
                    a_tot = format_currency(a_exp.get("amount"))
                    self.current_diff_items.append({
                        "diff_type": "modified",
                        "key": b_key,
                        "title": f"{cat} ({dt})",
                        "backup_val": b_tot,
                        "active_val": a_tot,
                        "details": " | ".join(diffs),
                        "backup_record": b_exp,
                        "active_record": a_exp,
                    })

        # 3. İsteğe bağlı: Sadece Güncelde Olanlar
        if show_active_only:
            for a_key, a_exp in active_map.items():
                if a_key not in backup_map:
                    cat = a_exp.get("category", "Gider")
                    dt = a_exp.get("date", "")
                    a_tot = format_currency(a_exp.get("amount"))
                    self.current_diff_items.append({
                        "diff_type": "created_in_active",
                        "key": a_key,
                        "title": f"{cat} ({dt})",
                        "backup_val": "(Yedekte Yok)",
                        "active_val": a_tot,
                        "details": "Yedek alındıktan sonra sisteme yeni eklenmiş gider kaydı.",
                        "backup_record": None,
                        "active_record": a_exp,
                    })

    def _compare_expense_fields(self, b_exp: dict, a_exp: dict) -> List[str]:
        """İki gider kaydı arasındaki alan farklarını inceler."""
        diffs = []
        b_amt = float(b_exp.get("amount") or 0.0)
        a_amt = float(a_exp.get("amount") or 0.0)
        if abs(b_amt - a_amt) > 0.009:
            diffs.append(f"Tutar: {format_currency(a_amt)} → {format_currency(b_amt)}")

        b_cat = str(b_exp.get("category") or "").strip()
        a_cat = str(a_exp.get("category") or "").strip()
        if b_cat != a_cat:
            diffs.append(f"Tür: {a_cat} → {b_cat}")

        b_date = str(b_exp.get("date") or "").strip()
        a_date = str(a_exp.get("date") or "").strip()
        if b_date != a_date:
            diffs.append(f"Tarih: {a_date} → {b_date}")

        b_desc = str(b_exp.get("description") or "").strip()
        a_desc = str(a_exp.get("description") or "").strip()
        if b_desc != a_desc:
            diffs.append(f"Açıklama: '{a_desc}' → '{b_desc}'")

        return diffs

    # --- TABLO VE ROZETLERİN ÇİZİLMESİ ---
    def _render_table(self):
        """Hesaplanan farkları QTableWidget'a aktarır ve özet rozetlerini günceller."""
        del_count = sum(1 for d in self.current_diff_items if d["diff_type"] == "deleted")
        mod_count = sum(1 for d in self.current_diff_items if d["diff_type"] == "modified")
        tot_count = len(self.current_diff_items)

        self.badge_deleted.setText(f"Silinmiş: {del_count}")
        self.badge_modified.setText(f"Değiştirilmiş: {mod_count}")
        self.badge_total_diff.setText(f"Toplam Fark: {tot_count}")

        if tot_count == 0:
            self._render_empty_or_no_diff()
            return

        self.frame_empty_state.setVisible(False)
        self.table_diff.setVisible(True)

        self.table_diff.blockSignals(True)
        self.table_diff.setRowCount(tot_count)

        for row, item in enumerate(self.current_diff_items):
            # 0. Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            # Sadece yedekte olan veya değiştirilmiş kayıtlar varsayılan seçili gelsin
            if item["diff_type"] in ("deleted", "modified"):
                chk_item.setCheckState(Qt.CheckState.Checked)
            else:
                chk_item.setCheckState(Qt.CheckState.Unchecked)
            self.table_diff.setItem(row, 0, chk_item)

            # 1. Durum Rozeti
            badge = DiffBadge(item["diff_type"])
            self.table_diff.setCellWidget(row, 1, badge)

            # 2. Kayıt Tanımı / Başlık
            title_item = QTableWidgetItem(item["title"])
            title_item.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            self.table_diff.setItem(row, 2, title_item)

            # 3. Yedekteki Değer
            b_item = QTableWidgetItem(item["backup_val"])
            b_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            b_item.setForeground(QColor("#38BDF8"))
            self.table_diff.setItem(row, 3, b_item)

            # 4. Günceldeki Değer
            a_item = QTableWidgetItem(item["active_val"])
            a_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            a_item.setForeground(QColor("#94A3B8"))
            self.table_diff.setItem(row, 4, a_item)

            # 5. Değişiklik Detayları
            det_item = QTableWidgetItem(item["details"])
            if item["diff_type"] == "modified":
                det_item.setForeground(QColor("#F59E0B"))
            elif item["diff_type"] == "deleted":
                det_item.setForeground(QColor("#10B981"))
            self.table_diff.setItem(row, 5, det_item)

        self.table_diff.blockSignals(False)
        self._update_selection_count_label()

    def _render_empty_or_no_diff(self, custom_msg: Optional[str] = None):
        """Fark bulunmadığında veya yedek olmadığında afiş gösterir."""
        self.table_diff.setRowCount(0)
        self.table_diff.setVisible(False)
        self.frame_empty_state.setVisible(True)

        if custom_msg:
            self.lbl_empty_msg.setText(custom_msg)
            self.lbl_empty_icon.setText("ℹ️")
        else:
            self.lbl_empty_msg.setText("Seçili sürüm ile mevcut veriler arasında hiçbir fark bulunmuyor.")
            self.lbl_empty_icon.setText("✅")

        self.badge_deleted.setText("Silinmiş: 0")
        self.badge_modified.setText("Değiştirilmiş: 0")
        self.badge_total_diff.setText("Toplam Fark: 0")
        self._update_selection_count_label()

    def _on_table_item_changed(self, item: QTableWidgetItem):
        """Tablodaki checkbox durumu değiştiğinde butonları günceller."""
        if item.column() == 0:
            self._update_selection_count_label()

    def _select_all_diffs(self):
        """Tüm satırlardaki checkbox'ları işaretler."""
        self.table_diff.blockSignals(True)
        for r in range(self.table_diff.rowCount()):
            it = self.table_diff.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Checked)
        self.table_diff.blockSignals(False)
        self._update_selection_count_label()

    def _deselect_all_diffs(self):
        """Tüm seçimleri kaldırır."""
        self.table_diff.blockSignals(True)
        for r in range(self.table_diff.rowCount()):
            it = self.table_diff.item(r, 0)
            if it:
                it.setCheckState(Qt.CheckState.Unchecked)
        self.table_diff.blockSignals(False)
        self._update_selection_count_label()

    def _get_checked_indices(self) -> List[int]:
        """İşaretli olan satır indekslerini döner."""
        checked = []
        for r in range(self.table_diff.rowCount()):
            it = self.table_diff.item(r, 0)
            if it and it.checkState() == Qt.CheckState.Checked:
                checked.append(r)
        return checked

    def _update_selection_count_label(self):
        """Seçili kayıt sayısını buton ve etikette gösterir."""
        checked_rows = self._get_checked_indices()
        count = len(checked_rows)
        self.lbl_selected_summary.setText(f"{count} kayıt seçildi")
        self.btn_restore_selected.setText(f"⏪ Seçili Kayıtları Geri Yükle ({count})")
        self.btn_restore_selected.setEnabled(count > 0)

    # --- SEÇİCİ GERİ YÜKLEME (SELECTIVE RESTORE) İŞLEMİ ---
    def _restore_selected_diffs(self):
        """Checkbox ile işaretlenen kayıtları aktif veritabanına seçici olarak işler."""
        checked_rows = self._get_checked_indices()
        if not checked_rows:
            QMessageBox.warning(self, "Seçim Yapılmadı", "Lütfen geri yüklemek istediğiniz en az bir kaydı işaretleyin.")
            return

        cat_name = "Gelir / Fatura (infos.json)" if self.current_category == "infos" else "Gider Kayıtları (expenses.json)"
        reply = QMessageBox.question(
            self,
            "Seçici Geri Yükleme Onayı",
            f"Seçilen {len(checked_rows)} adet kayıt yedekteki haliyle aktif veritabanına geri yüklenecektir.\n\n"
            f"Kategori: {cat_name}\n\n"
            "İşlem öncesinde mevcut veritabanınızın son hali otomatik olarak yeni bir sürüm (snapshot) olarak yedeklenecektir.\n\n"
            "Devam etmek istiyor musunuz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 1. Aktif dosya yolu
        if self.current_category == "infos":
            target_path = getattr(self.db, "json_path", None) or os.path.join(self.base_dir, "TasımaBelgeler", "infos.json")
        else:
            target_path = getattr(self.expense_db, "json_path", None) or os.path.join(self.base_dir, "TasımaBelgeler", "expenses.json")

        # 2. İşlem öncesi otomatik güvenlik snapshot'ı al
        if os.path.exists(target_path):
            backup_manager.create_snapshot(self.current_category, target_path)

        # 3. Seçili kayıtları seçici olarak işle
        restored_count = 0
        try:
            if self.current_category == "infos":
                restored_count = self._apply_selective_invoices(checked_rows)
            else:
                restored_count = self._apply_selective_expenses(checked_rows)
        except Exception as e:
            logger.error(f"[Selective Restore Hatası] {e}")
            QMessageBox.critical(self, "Hata", f"Kayıtlar geri yüklenirken bir hata oluştu:\n{e}")
            return

        # 4. Arayüzü ve bellekteki verileri yenile
        try:
            parent_win = self.window()
            if hasattr(parent_win, "_on_cloud_data_reloaded"):
                parent_win._on_cloud_data_reloaded()
            else:
                if self.current_category == "infos" and self.db:
                    self.db.load_all()
                    if hasattr(parent_win, "refresh_all_tabs"):
                        parent_win.refresh_all_tabs()
                elif self.current_category == "expenses" and self.expense_db:
                    self.expense_db.reload()
                    if hasattr(parent_win, "expenses_widget"):
                        parent_win.expenses_widget.refresh_all()
        except Exception as rel_err:
            logger.warning(f"Arayüz yenileme uyarısı: {rel_err}")

        # 5. Dropbox'a bulut senkronizasyonu gönder
        try:
            if self.dropbox_sync and self.dropbox_sync.is_configured():
                if self.current_category == "infos":
                    self.dropbox_sync.trigger_instant_upload()
                else:
                    self.dropbox_sync.trigger_instant_upload_expenses()
        except Exception as sync_err:
            logger.warning(f"Dropbox senkronizasyon uyarısı: {sync_err}")

        # 6. Başarılı bildirimi ve fark tablosunun anında yeniden hesaplanması
        QMessageBox.information(
            self,
            "Geri Yükleme Başarılı",
            f"✓ {restored_count} adet kayıt başarıyla aktif veritabanına geri yüklendi!\n"
            "Veritabanı güncellendi ve Dropbox ile eşitlendi.",
        )

        # Fark tablosunu ve sürüm listesini yeniden hesapla
        self._compute_and_render_diff()

    def _apply_selective_invoices(self, checked_rows: List[int]) -> int:
        """Seçilen fatura kayıtlarını aktif veritabanına uygular."""
        active_invoices = self.db.load_all() if self.db else []

        def get_inv_key(inv: dict) -> str:
            raw_id = str(inv.get("id") or "").strip().upper()
            raw_no = str(inv.get("invoice_number") or "").strip().upper()
            raw_fn = str(inv.get("file_name") or "").strip().lower()
            return raw_id or raw_no or raw_fn

        # Mevcut kayıtları indeksle
        key_to_index = {get_inv_key(inv): idx for idx, inv in enumerate(active_invoices) if get_inv_key(inv)}
        restored = 0

        for row_idx in checked_rows:
            diff_item = self.current_diff_items[row_idx]
            b_rec = diff_item.get("backup_record")
            if not b_rec:
                continue

            k = diff_item["key"]
            if k in key_to_index:
                # Değiştirilmiş kayıt: Mevcut kaydı yedekteki verilerle güncelle
                target_idx = key_to_index[k]
                active_invoices[target_idx] = dict(b_rec)
                restored += 1
            else:
                # Silinmiş kayıt: Aktif listeye geri ekle
                active_invoices.append(dict(b_rec))
                restored += 1

        if self.db:
            self.db.save_all(active_invoices)
        return restored

    def _apply_selective_expenses(self, checked_rows: List[int]) -> int:
        """Seçilen gider kayıtlarını aktif veritabanına uygular."""
        active_data = self.expense_db.load_data() if self.expense_db else {}
        active_expenses = list(active_data.get("expenses", []))
        categories = list(active_data.get("categories", []))

        def get_exp_key(exp: dict) -> str:
            raw_id = str(exp.get("id") or "").strip()
            if raw_id:
                return raw_id
            return f"{exp.get('date')}_{exp.get('category')}_{exp.get('amount')}"

        key_to_index = {get_exp_key(e): idx for idx, e in enumerate(active_expenses)}
        restored = 0

        for row_idx in checked_rows:
            diff_item = self.current_diff_items[row_idx]
            b_rec = diff_item.get("backup_record")
            if not b_rec:
                continue

            k = diff_item["key"]
            # Kategori aktif kategorilerde yoksa ekle
            cat_name = b_rec.get("category")
            if cat_name and cat_name not in categories:
                categories.append(cat_name)

            if k in key_to_index:
                target_idx = key_to_index[k]
                active_expenses[target_idx] = dict(b_rec)
                restored += 1
            else:
                active_expenses.append(dict(b_rec))
                restored += 1

        active_data["expenses"] = active_expenses
        active_data["categories"] = categories

        if self.expense_db:
            self.expense_db.save_data(active_data)
        return restored
