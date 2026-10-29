from datetime import datetime
from typing import Any, List, Optional
from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeyEvent, QKeySequence, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from src.database import parse_date_obj
from src.styles import COLORS


class CustomInvoiceRowDelegate(QStyledItemDelegate):
    """
    Satırları faturanın vade uyarı durumuna göre hatasız boyayan,
    seçildiğinde arka planı mavi yapıp metin rengini ise faturanın
    kendi uyarı renginde (kırmızı, turuncu, sarı, yeşil, beyaz) gösteren delege.
    Ayrıca 0. sütundaki Checkbox onay kutusunu modern ve şık şekilde çizer.
    """

    def editorEvent(self, event, model, option, index):
        """Kullanıcı fare veya klavye ile onay kutusuna tıkladığında veya boşluk tuşuna bastığında durumu güncelle."""
        flags = model.flags(index)
        if not (flags & Qt.ItemFlag.ItemIsUserCheckable) or not (flags & Qt.ItemFlag.ItemIsEnabled):
            return super().editorEvent(event, model, option, index)

        if event.type() in (QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            check_state = index.data(Qt.ItemDataRole.CheckStateRole)
            is_checked = bool(check_state == Qt.CheckState.Checked or check_state == 2 or check_state == Qt.CheckState.Checked.value)
            new_state = Qt.CheckState.Unchecked if is_checked else Qt.CheckState.Checked
            res = model.setData(index, new_state.value if isinstance(check_state, int) else new_state, Qt.ItemDataRole.CheckStateRole)
            parent_table = self.parent()
            if parent_table and hasattr(parent_table, "viewport"):
                parent_table.viewport().update()
            return res
        return super().editorEvent(event, model, option, index)

    def paint(self, painter: QPainter, option, index):
        painter.save()

        # Faturanın durum türü 0. veya 1. sütunun UserRole + 2 verisinden okunur
        status_type = "normal"
        sibling = index.siblingAtColumn(0)
        if sibling.isValid():
            val = sibling.data(Qt.ItemDataRole.UserRole + 2)
            if val:
                status_type = str(val)
        if status_type == "normal":
            sibling1 = index.siblingAtColumn(1)
            if sibling1.isValid():
                val1 = sibling1.data(Qt.ItemDataRole.UserRole + 2)
                if val1:
                    status_type = str(val1)

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # Renk Kuralları:
        # Seçili değilken:
        # - normal: Beyaz zemin (#FFFFFF), koyu metin (#0F172A)
        # - yellow: Açık sarı zemin (#FEF08A), koyu sarı metin (#713F12)
        # - orange: Açık turuncu zemin (#FED7AA), koyu turuncu metin (#7C2D12)
        # - red: Açık kırmızı zemin (#FECACA), koyu kırmızı metin (#7F1D1D)
        # - paid: Açık yeşil zemin (#BBF7D0), koyu yeşil metin (#065F46)
        # - partial: Açık kehribar zemin (#FDE68A), koyu kehribar metin (#78350F)
        #
        # Seçili iken (Mavi arka plan #1D4ED8):
        # - red: Kırmızı metin (#FCA5A5) -> "BUGÜN SON GÜN" faturası asla beyaz kalmaz!
        # - orange: Turuncu metin (#FED7AA)
        # - yellow: Sarı metin (#FEF08A)
        # - paid: Yeşil metin (#86EFAC)
        # - partial: Kehribar metin (#FDE68A)
        # - normal: Beyaz metin (#FFFFFF)
        if status_type == "red":
            bg_color = QColor("#1D4ED8") if is_selected else QColor("#FECACA")
            txt_color = QColor("#FCA5A5") if is_selected else QColor("#7F1D1D")
        elif status_type == "orange":
            bg_color = QColor("#1D4ED8") if is_selected else QColor("#FED7AA")
            txt_color = QColor("#FED7AA") if is_selected else QColor("#7C2D12")
        elif status_type == "yellow":
            bg_color = QColor("#1D4ED8") if is_selected else QColor("#FEF08A")
            txt_color = QColor("#FEF08A") if is_selected else QColor("#713F12")
        elif status_type == "paid":
            bg_color = QColor("#1D4ED8") if is_selected else QColor("#BBF7D0")
            txt_color = QColor("#86EFAC") if is_selected else QColor("#065F46")
        elif status_type == "partial":
            # Kısmi / Parçalı Ödeme: Belirgin Kehribar / Sıcak Altın Sarısı tonu
            bg_color = QColor("#1D4ED8") if is_selected else QColor("#FDE68A")
            txt_color = QColor("#FDE68A") if is_selected else QColor("#78350F")
        else:
            bg_color = QColor("#1D4ED8") if is_selected else QColor("#FFFFFF")
            txt_color = QColor("#FFFFFF") if is_selected else QColor("#0F172A")

        # 1. Arka planı boya
        painter.fillRect(option.rect, bg_color)

        # Alt kenarlık çizgisi
        painter.setPen(QColor("#CBD5E1") if not is_selected else QColor("#2563EB"))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())

        # Checkbox Sütunu (Sütun 0 ve CheckStateRole tanımlıysa)
        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        if check_state is not None:
            box_size = 18
            cx = option.rect.x() + (option.rect.width() - box_size) // 2
            cy = option.rect.y() + (option.rect.height() - box_size) // 2
            box_rect = QRect(cx, cy, box_size, box_size)

            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            is_checked = bool(check_state == Qt.CheckState.Checked or check_state == Qt.CheckState.Checked.value or check_state == 2)

            if is_checked:
                painter.setBrush(QColor("#0284C7"))
                painter.setPen(QColor("#0284C7"))
                painter.drawRoundedRect(box_rect, 4, 4)

                painter.setPen(QColor("#FFFFFF"))
                pen = painter.pen()
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawLine(QPoint(cx + 4, cy + 9), QPoint(cx + 8, cy + 13))
                painter.drawLine(QPoint(cx + 8, cy + 13), QPoint(cx + 14, cy + 5))
            else:
                painter.setBrush(QColor("#1E293B" if is_selected else "#FFFFFF"))
                painter.setPen(QColor("#93C5FD" if is_selected else "#94A3B8"))
                painter.drawRoundedRect(box_rect, 4, 4)

            painter.restore()
            return

        # 2. Standart Metni boya
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.setPen(txt_color)

        font = option.font
        if is_selected or status_type in ["red", "orange", "yellow", "paid", "partial"]:
            font.setBold(True)
        painter.setFont(font)

        # Metin hizalaması
        text_align = index.data(Qt.ItemDataRole.TextAlignmentRole)
        if text_align is None:
            text_align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        else:
            text_align = Qt.AlignmentFlag(text_align)

        # Padding payı ile metin çizimi
        text_rect = option.rect.adjusted(10, 0, -10, 0)
        painter.drawText(text_rect, int(text_align), text)

        painter.restore()


class NumericTableWidgetItem(QTableWidgetItem):
    """Sayısal sıralamayı (Küçükten Büyüğe / Büyükten Küçüğe) doğru yapan tablo hücresi."""

    def __init__(self, value: float, display_text: str = ""):
        super().__init__(display_text if display_text else f"{value:,.2f}")
        self.numeric_value = float(value)

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)


class DateTableWidgetItem(QTableWidgetItem):
    """Tarihsel sıralamayı kronolojik yapan tablo hücresi."""

    def __init__(self, date_val: Any):
        display_str = "-"
        self.timestamp = 0.0
        dt = parse_date_obj(date_val)
        if dt:
            dt_full = datetime(dt.year, dt.month, dt.day)
            self.timestamp = dt_full.timestamp()
            display_str = dt.strftime("%d.%m.%Y")
        elif date_val:
            display_str = str(date_val).strip()
        super().__init__(display_str)

    def __lt__(self, other):
        if isinstance(other, DateTableWidgetItem):
            return self.timestamp < other.timestamp
        return super().__lt__(other)


class SortableTableWidget(QTableWidget):
    """
    Sütun başlıklarına tıklandığında alfabetik/sayısal sıralanabilen,
    arama filtresi destekli, otomatik sütun genişliği, pano (clipboard) kopyalama,
    sağ tık menüsü (Context Menu), çoklu seçim Checkbox altyapısı ve
    boş alana tıklandığında seçimi temizleme yeteneği içeren modern tablo bileşeni.
    """

    # Sinyaller
    copied_to_clipboard = pyqtSignal(str)
    bulk_delete_requested = pyqtSignal()
    bulk_due_date_requested = pyqtSignal()
    bulk_mark_paid_requested = pyqtSignal()

    def __init__(self, headers: List[str], parent=None):
        super().__init__(parent)
        self.headers = headers
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)

        # Tablo davranışları
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)

        # Özel Renk ve Seçim Delegesi
        self.row_delegate = CustomInvoiceRowDelegate(self)
        self.setItemDelegate(self.row_delegate)

        # Başlık özellikleri ve yatay kaydırma optimizasyonu
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.sectionClicked.connect(self._on_header_section_clicked)
        self.verticalHeader().setDefaultSectionSize(40)

        # Sütun ve Ekran Optimizasyonu
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.column_weights: Optional[List[float]] = None

        # Sağ tık menüsü (Context Menu) yetkisi
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # Seçim değiştiğinde görünümü güncelle
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def _on_header_section_clicked(self, logicalIndex: int):
        """Başlığa tıklandığında: Sütun 0 Checkbox sütunu ise tümünü seç / seçimi kaldır."""
        if logicalIndex == 0:
            hdr0 = self.horizontalHeaderItem(0)
            if hdr0 and hdr0.text() in ["✓", "Seç", ""]:
                self.toggle_all_checkboxes()

    def mousePressEvent(self, event):
        """
        - Sütun 0'a tıklandığında (Checkbox hücresi): Onay kutusunu doğrudan tersine çevirir.
        - Boş bir alana tıklandığında: Mevcut satır seçimini temizler.
        """
        item = self.itemAt(event.pos())
        if item and item.column() == 0:
            current_state = item.checkState()
            is_currently_checked = bool(current_state == Qt.CheckState.Checked or current_state == 2 or current_state == Qt.CheckState.Checked.value)
            new_state = Qt.CheckState.Unchecked if is_currently_checked else Qt.CheckState.Checked
            item.setCheckState(new_state)
            self.viewport().update()
            self.selectRow(item.row())
            return
        elif item is None:
            self.clearSelection()
            self.setCurrentItem(None)
        super().mousePressEvent(event)

    def _on_selection_changed(self):
        """Seçim değiştiğinde viewport'u anında yeniden çiz."""
        self.viewport().update()

    # --- ÇOKLU SEÇİM (CHECKBOX) YARDIMCI METOTLARI ---
    def get_checked_rows(self) -> List[int]:
        """İşaretlenmiş tüm satırların indeks listesini döner."""
        checked = []
        for r in range(self.rowCount()):
            item = self.item(r, 0)
            if item:
                st = item.checkState()
                if st == Qt.CheckState.Checked or st == 2 or st == Qt.CheckState.Checked.value:
                    checked.append(r)
        return checked

    def get_checked_invoice_ids(self) -> List[str]:
        """İşaretlenmiş tüm satırlara ait fatura ID'lerini (UserRole) döner."""
        ids = []
        for r in self.get_checked_rows():
            item = self.item(r, 0)
            if item:
                inv_id = item.data(Qt.ItemDataRole.UserRole)
                if inv_id:
                    ids.append(str(inv_id))
        return ids

    def select_all_checkboxes(self, checked: bool = True):
        """Görünür durumdaki tüm satırların onay kutularını işaretler veya kaldırır."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.blockSignals(True)
        for r in range(self.rowCount()):
            if not self.isRowHidden(r):
                item = self.item(r, 0)
                if item:
                    item.setCheckState(state)
        self.blockSignals(False)
        self.viewport().update()
        if self.rowCount() > 0 and self.item(0, 0):
            self.itemChanged.emit(self.item(0, 0))

    def toggle_all_checkboxes(self):
        """Tüm satırların işaret durumunu tersine çevirir (Select/Deselect All)."""
        checked_rows = self.get_checked_rows()
        all_checked = (len(checked_rows) == self.rowCount() and self.rowCount() > 0)
        self.select_all_checkboxes(not all_checked)

    def set_column_weights(self, weights: List[float]):
        """Sütun genişliklerini ana ekran genişliğine orantılı (weight) olarak ayarlar."""
        self.column_weights = weights
        self.apply_proportional_widths()

    def apply_proportional_widths(self):
        """
        Tablo sütunlarını, ana ekran genişliğine orantılı (stretch/weight) olarak dağıtır.
        0. sütun Checkbox ise sabit 42px ayrılır, kalan sütunlar orantılı dağıtılır.
        """
        if not self.column_weights or len(self.column_weights) != self.columnCount():
            return

        total_w = self.viewport().width()
        if total_w <= 0:
            total_w = self.width() - 4
        if total_w < 100:
            return

        hdr0 = self.horizontalHeaderItem(0)
        has_checkbox_col = bool(hdr0 and hdr0.text() in ["✓", "Seç", ""])

        if has_checkbox_col:
            checkbox_w = 42
            self.setColumnWidth(0, checkbox_w)
            usable_w = max(total_w - checkbox_w, 100)
            start_col = 1
            remaining_weights = self.column_weights[1:]
        else:
            usable_w = total_w
            start_col = 0
            remaining_weights = self.column_weights

        total_weight = sum(remaining_weights) if remaining_weights else 1.0
        allocated = 0
        for i, weight in enumerate(remaining_weights):
            col = start_col + i
            if col == self.columnCount() - 1:
                col_w = max(usable_w - allocated, 50)
            else:
                col_w = int(usable_w * (weight / total_weight))
                allocated += col_w
            self.setColumnWidth(col, col_w)

    def auto_fit_columns(self):
        """Orantılı sütun genişliklerini ekrana uygular."""
        if self.column_weights:
            self.apply_proportional_widths()
        else:
            self.resizeColumnsToContents()

    def resizeEvent(self, event):
        """Ekran boyutu değiştikçe sütunları orantılı olarak yeniden boyutlandırır."""
        super().resizeEvent(event)
        if self.column_weights:
            self.apply_proportional_widths()

    def keyPressEvent(self, event: QKeyEvent):
        """Standart klavye kısayolları (Ctrl+C / Cmd+C) ve Boşluk (Space) ile onay kutusu işaretleme."""
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection_to_clipboard()
            event.accept()
        elif event.key() == Qt.Key.Key_Space:
            curr_row = self.currentRow()
            if curr_row >= 0:
                item0 = self.item(curr_row, 0)
                if item0 and (item0.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                    st = item0.checkState()
                    is_chk = bool(st == Qt.CheckState.Checked or st == 2 or st == Qt.CheckState.Checked.value)
                    new_st = Qt.CheckState.Unchecked if is_chk else Qt.CheckState.Checked
                    item0.setCheckState(new_st)
                    self.viewport().update()
                    event.accept()
                    return
            super().keyPressEvent(event)
        else:
            super().keyPressEvent(event)

    def copy_selection_to_clipboard(self):
        """Seçili satır veya hücreyi panoya kopyalar."""
        selected_items = self.selectedItems()
        if not selected_items:
            return

        current_row = self.currentRow()
        if current_row < 0:
            return

        hdr0 = self.horizontalHeaderItem(0)
        is_chk = bool(hdr0 and hdr0.text() in ["✓", "Seç", ""])
        company_col = 1 if is_chk else 0
        inv_col = 2 if is_chk else 1

        company_item = self.item(current_row, company_col)
        inv_item = self.item(current_row, inv_col)

        company = company_item.text() if company_item else ""
        inv_no = inv_item.text() if inv_item else ""

        current_col = self.currentColumn()
        active_item = self.item(current_row, current_col)
        text_to_copy = active_item.text() if active_item else f"{company} - {inv_no}"

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text_to_copy)
            self.copied_to_clipboard.emit(f"Panoya Kopyalandı: {text_to_copy}")

    def _show_context_menu(self, pos: QPoint):
        """
        Sağ Tık Menüsü (Context Menu):
        1. Toplu İşlemler: Toplu Silme, Toplu Vade Değiştirme, Toplu Ödendi Yapma
        2. Kopyalama: Şirket İsmi, Fatura No, Hücre Metni veya Tüm Satır Bilgileri
        """
        row = self.rowAt(pos.y())
        col = self.columnAt(pos.x())
        if row < 0:
            return

        hdr0 = self.horizontalHeaderItem(0)
        is_chk = bool(hdr0 and hdr0.text() in ["✓", "Seç", ""])
        company_col = 1 if is_chk else 0
        inv_col = 2 if is_chk else 1

        clicked_chk = self.item(row, 0)
        checked_ids = self.get_checked_invoice_ids()
        # Eğer hiç seçim yoksa sağ tıklanan satırı otomatik olarak seçime dahil et
        if not checked_ids and clicked_chk:
            clicked_chk.setCheckState(Qt.CheckState.Checked)
            checked_ids = self.get_checked_invoice_ids()
            self.viewport().update()

        menu = QMenu(self)

        target_count = max(len(checked_ids), 1)

        # 1. TOPLU İŞLEMLER BÖLÜMÜ
        menu.addSection("⚡ Seçili Faturalar İçin Toplu İşlemler")
        act_bulk_paid = menu.addAction(f"✅ Seçiliyi 'Ödendi' Olarak İşaretle ({target_count} Fatura)")
        act_bulk_due = menu.addAction(f"📅 Seçili Vade Tarihini Değiştir ({target_count} Fatura)")
        act_bulk_del = menu.addAction(f"🗑️ Seçili Faturaları Sil ({target_count} Fatura)")
        menu.addSeparator()

        # 2. STANDART KOPYALAMA BÖLÜMÜ
        menu.addSection("📋 Kopyalama Seçenekleri")
        company_item = self.item(row, company_col)
        inv_item = self.item(row, inv_col)
        company_text = company_item.text() if company_item else ""
        inv_text = inv_item.text() if inv_item else ""

        act_company = menu.addAction(f"📋 Şirket İsmini Kopyala ({company_text[:20]}...)")
        act_inv = menu.addAction(f"📄 Fatura No Kopyala ({inv_text})")
        menu.addSeparator()

        current_cell_item = self.item(row, col)
        cell_text = current_cell_item.text() if current_cell_item else ""
        act_cell = menu.addAction(f"📑 Hücre Metnini Kopyala (\"{cell_text[:25]}\")")
        act_full_row = menu.addAction("📊 Tüm Satır Bilgilerini Kopyala")

        action = menu.exec(self.viewport().mapToGlobal(pos))
        clipboard = QApplication.clipboard()
        if not action:
            return

        if action == act_bulk_paid:
            self.bulk_mark_paid_requested.emit()
        elif action == act_bulk_due:
            self.bulk_due_date_requested.emit()
        elif action == act_bulk_del:
            self.bulk_delete_requested.emit()
        elif clipboard:
            if action == act_company:
                clipboard.setText(company_text)
                self.copied_to_clipboard.emit(f"Şirket İsmi Panoya Kopyalandı: {company_text}")
            elif action == act_inv:
                clipboard.setText(inv_text)
                self.copied_to_clipboard.emit(f"Fatura No Panoya Kopyalandı: {inv_text}")
            elif action == act_cell:
                clipboard.setText(cell_text)
                self.copied_to_clipboard.emit(f"Hücre Panoya Kopyalandı: {cell_text}")
            elif action == act_full_row:
                row_data = [
                    self.item(row, c).text() if self.item(row, c) else ""
                    for c in range(self.columnCount())
                    if c != 0 or not is_chk
                ]
                row_str = "\t".join(row_data)
                clipboard.setText(row_str)
                self.copied_to_clipboard.emit(f"Tüm Satır Panoya Kopyalandı: {inv_text}")

    def filter_by_text(self, text: str, search_columns: Optional[List[int]] = None):
        """
        Belirtilen metne göre satırları filtreler (Canlı arama).
        search_columns verilmezse Şirket İsmi ve Fatura No sütunlarında arar.
        """
        if search_columns is None:
            hdr0 = self.horizontalHeaderItem(0)
            if self.columnCount() > 2 and hdr0 and hdr0.text() in ["✓", "Seç", ""]:
                search_columns = [1, 2]
            else:
                search_columns = [0, 1]

        query = text.strip().lower()
        row_count = self.rowCount()

        for row in range(row_count):
            if not query:
                self.setRowHidden(row, False)
                continue

            match = False
            for col in search_columns:
                if col < self.columnCount():
                    item = self.item(row, col)
                    if item and query in item.text().lower():
                        match = True
                        break

            self.setRowHidden(row, not match)


class StatCard(QFrame):
    """Özet İstatistik Kartı Bileşeni."""

    def __init__(self, title: str, value: str = "0", color: str = "#3B82F6", parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #94A3B8; font-size: 11px; font-weight: 600; text-transform: uppercase;")

        self.value_label = QLabel(value)
        self.value_label.setStyleSheet(f"color: {color}; font-size: 17px; font-weight: 700;")

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, val: str):
        self.value_label.setText(str(val))
