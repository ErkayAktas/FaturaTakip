import os
import time
from typing import Callable, Optional
from PyQt6.QtCore import QObject, pyqtSignal
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from src.database import InvoiceDatabase
from src.pdf_extractor import PDFExtractor


class InvoiceFileHandler(FileSystemEventHandler):
    """TasımaBelgeler/TasımaFaturaları klasöründeki dosya hareketlerini dinleyen dinleyici."""

    def __init__(self, callback: Callable[[str], None]):
        super().__init__()
        self.callback = callback
        self.processed_files = set()

    def _handle_file(self, file_path: str):
        if not file_path.lower().endswith(".pdf"):
            return

        # Geçici veya gizli dosyaları atla
        base_name = os.path.basename(file_path)
        if base_name.startswith(".") or base_name.startswith("~"):
            return

        # Dosyanın yazılmasının tamamlanması için bekleme ve kontrol
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    # Dosyayı okumayı dene
                    with open(file_path, "rb") as f:
                        f.read(10)
                    time.sleep(0.5)  # Tam yazılma için güvenli pay
                    self.callback(file_path)
                    break
            except (OSError, PermissionError):
                time.sleep(0.5)
            except Exception:
                time.sleep(0.5)

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            self._handle_file(event.src_path)

    def on_moved(self, event: FileSystemEvent):
        if not event.is_directory:
            dest = getattr(event, "dest_path", None)
            if dest:
                self._handle_file(dest)

    def on_deleted(self, event: FileSystemEvent):
        # KURAL: "PDF dosyası dizinden silinse dahi, veri JSON dosyasında muhafaza edilecektir."
        # Bu nedenle dosya silindiğinde veritabanından ASLA silinmez.
        pass


class WatcherService(QObject):
    """PyQt6 sinyalleri ile entegre Watchdog dosya izleme servisi."""

    # Sinyaller
    new_invoice_detected = pyqtSignal(dict)  # Yeni fatura eklendiğinde
    duplicate_invoice_skipped = pyqtSignal(str, str)  # (Fatura No, Dosya Adı)
    scan_finished = pyqtSignal(int, int)  # (Eklenen Sayısı, Toplam PDF)
    log_message = pyqtSignal(str)

    def __init__(self, db: InvoiceDatabase, extractor: PDFExtractor, watch_dir: Optional[str] = None):
        super().__init__()
        self.db = db
        self.extractor = extractor
        if watch_dir is None:
            self.watch_dir = os.path.join(self.db.base_dir, "TasımaBelgeler", "TasımaFaturaları")
        else:
            self.watch_dir = watch_dir

        os.makedirs(self.watch_dir, exist_ok=True)
        self.observer: Optional[Observer] = None
        self._is_running = False

    def start(self) -> bool:
        """Dizin izlemeyi başlatır."""
        if self._is_running:
            return True

        try:
            handler = InvoiceFileHandler(self._process_single_pdf)
            self.observer = Observer()
            self.observer.schedule(handler, path=self.watch_dir, recursive=False)
            self.observer.start()
            self._is_running = True
            self.log_message.emit(f"Dizin izleme aktif: {self.watch_dir}")
            return True
        except Exception as e:
            self.log_message.emit(f"Dizin izleme başlatılamadı: {e}")
            return False

    def stop(self):
        """Dizin izlemeyi durdurur."""
        if self.observer and self._is_running:
            try:
                self.observer.stop()
                self.observer.join(timeout=2.0)
            except Exception:
                pass
            self._is_running = False
            self.log_message.emit("Dizin izleme durduruldu.")

    def _process_single_pdf(self, pdf_path: str):
        """Tek bir PDF dosyasını okuyup veritabanına ekler."""
        try:
            inv_data = self.extractor.process_pdf(pdf_path)
            inv_no = inv_data.get("invoice_number", "")
            file_name = os.path.basename(pdf_path)

            # Mükerrer kontrolü
            if self.db.is_duplicate(inv_no):
                self.duplicate_invoice_skipped.emit(inv_no, file_name)
                self.log_message.emit(f"Mükerrer fatura atlandı: {inv_no} ({file_name})")
                return

            # Veritabanına ekle
            success = self.db.add_invoice(inv_data)
            if success:
                self.new_invoice_detected.emit(inv_data)
                self.log_message.emit(f"Yeni fatura kaydedildi: {inv_no} - {inv_data.get('company_name')}")
        except Exception as e:
            self.log_message.emit(f"PDF işleme hatası ({pdf_path}): {e}")

    def scan_existing_files(self) -> tuple[int, int]:
        """
        TasımaFaturaları klasöründeki mevcut tüm PDF dosyalarını tarar.
        (Eklenen Fatura Sayısı, Taranan PDF Sayısı) döner.
        """
        if not os.path.exists(self.watch_dir):
            return 0, 0

        pdf_files = [
            os.path.join(self.watch_dir, f)
            for f in os.listdir(self.watch_dir)
            if f.lower().endswith(".pdf") and not f.startswith(".")
        ]

        added_count = 0
        for pdf_path in pdf_files:
            try:
                inv_data = self.extractor.process_pdf(pdf_path)
                inv_no = inv_data.get("invoice_number", "")
                if not self.db.is_duplicate(inv_no):
                    if self.db.add_invoice(inv_data):
                        added_count += 1
                        self.new_invoice_detected.emit(inv_data)
            except Exception as e:
                self.log_message.emit(f"Tarama hatası ({pdf_path}): {e}")

        self.scan_finished.emit(added_count, len(pdf_files))
        return added_count, len(pdf_files)
