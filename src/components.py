from datetime import datetime
from typing import Any, List, Optional
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
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
    """

    def paint(self, painter: QPainter, option, index):
        painter.save()

        # Faturanın durum türü 0. sütunun UserRole + 2 verisinden okunur
        status_type = "normal"
        sibling = index.siblingAtColumn(0)
        if sibling.isValid():
            val = sibling.data(Qt.ItemDataRole.UserRole + 2)
            if val:
                status_type = str(val)

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        # Renk Kuralları:
        # Seçili değilken:
        # - normal: Beyaz zemin (#FFFFFF), koyu metin (#0F172A)
        # - yellow: Açık sarı zemin (#FEF08A), koyu sarı metin (#713F12)
        # - orange: Açık turuncu zemin (#FED7AA), koyu turuncu metin (#7C2D12)
        # - red: Açık kırmızı zemin (#FECACA), koyu kırmızı metin (#7F1D1D)
        # - paid: Açık yeşil zemin (#BBF7D0), koyu yeşil metin (#065F46)
        #
        # Seçili iken (Mavi arka plan #1D4ED8):
        # - red: Kırmızı metin (#FCA5A5) -> "BUGÜN SON GÜN" faturası asla beyaz kalmaz!
        # - orange: Turuncu metin (#FED7AA)
        # - yellow: Sarı metin (#FEF08A)
        # - paid: Yeşil metin (#86EFAC)
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

        # 2. Metni boya
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
    sağ tık menüsü ve boş alana tıklandığında seçimi temizleme yeteneği içeren tablo.
    """

    # Kopyalama bildirimi sinyali
    copied_to_clipboard = pyqtSignal(str)

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
        self.verticalHeader().setDefaultSectionSize(40)

        # Sütun ve Ekran Optimizasyonu: Yatay kaydırma çubuğuna ihtiyaç bırakmayacak şekilde
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.column_weights: Optional[List[float]] = None

        # Sağ tık menüsü (Context Menu) yetkisi
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # Seçim değiştiğinde görünümü güncelle
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def mousePressEvent(self, event):
        """
        Seçimi Temizleme (Clear Selection Event): Tablo bileşeninde veri olmayan
        boş bir alana tıklandığında mevcut satır seçimi (selection) iptal edilir.
        """
        item = self.itemAt(event.pos())
        if item is None:
            self.clearSelection()
            self.setCurrentItem(None)
        super().mousePressEvent(event)

    def _on_selection_changed(self):
        """Seçim değiştiğinde viewport'u anında yeniden çiz."""
        self.viewport().update()

    def set_column_weights(self, weights: List[float]):
        """Sütun genişliklerini ana ekran genişliğine orantılı (weight) olarak ayarlar."""
        self.column_weights = weights
        self.apply_proportional_widths()

    def apply_proportional_widths(self):
        """
        Tablo sütunlarını, ana ekran genişliğine orantılı (stretch/weight) olarak dağıtır.
        Tüm içerik tek ekranda taşmadan görüntülenir.
        """
        if not self.column_weights or len(self.column_weights) != self.columnCount():
            return

        total_w = self.viewport().width()
        if total_w <= 0:
            total_w = self.width() - 4
        if total_w < 100:
            return

        total_weight = sum(self.column_weights)
        allocated = 0
        for col, weight in enumerate(self.column_weights):
            if col == len(self.column_weights) - 1:
                col_w = max(total_w - allocated, 50)
            else:
                col_w = int(total_w * (weight / total_weight))
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
        """
        Madde 5: Standart klavye kısayolları (Ctrl+C / Cmd+C) ile panoya kopyalama.
        """
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection_to_clipboard()
            event.accept()
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

        # Varsa Şirket İsmi (0) ve Fatura No (1)
        company_item = self.item(current_row, 0)
        inv_item = self.item(current_row, 1)

        company = company_item.text() if company_item else ""
        inv_no = inv_item.text() if inv_item else ""

        # O an tıklanmış olan aktif hücre
        current_col = self.currentColumn()
        active_item = self.item(current_row, current_col)
        text_to_copy = active_item.text() if active_item else f"{company} - {inv_no}"

        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text_to_copy)
            self.copied_to_clipboard.emit(f"Panoya Kopyalandı: {text_to_copy}")

    def _show_context_menu(self, pos: QPoint):
        """
        Madde 5: Sağ tık menüsü ile Şirket İsmi, Fatura No veya Satır kopyalama.
        """
        row = self.rowAt(pos.y())
        col = self.columnAt(pos.x())
        if row < 0:
            return

        menu = QMenu(self)

        company_item = self.item(row, 0)
        inv_item = self.item(row, 1)
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
        if not clipboard or not action:
            return

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
            row_data = [self.item(row, c).text() if self.item(row, c) else "" for c in range(self.columnCount())]
            row_str = "\t".join(row_data)
            clipboard.setText(row_str)
            self.copied_to_clipboard.emit(f"Tüm Satır Panoya Kopyalandı: {inv_text}")

    def filter_by_text(self, text: str, search_columns: Optional[List[int]] = None):
        """
        Belirtilen metne göre satırları filtreler (Canlı arama).
        search_columns verilmezse ilk iki sütunda (genelde Şirket İsmi ve Fatura No) arar.
        """
        if search_columns is None:
            # Şirket İsmi (0) ve Fatura No (1)
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
