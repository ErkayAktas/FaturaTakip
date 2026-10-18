import json
import os
import re
import shutil
import sys
import tempfile
import threading
from datetime import date, datetime
from typing import Any, Dict, List, Optional


def sanitize_date_str(val: Any) -> str:
    """
    macOS dosya sisteminden veya DatePicker bileşeninden gelen tarih stringlerindeki
    görünmeyen karakterleri (zero-width, non-breaking space, newline, tab) ve boşlukları temizler.
    """
    if val is None:
        return ""
    s = str(val)
    # macOS/Unicode boşluk ve görünmeyen karakterleri temizle
    for ch in ["\u200b", "\ufeff", "\u200e", "\u200f", "\xa0", "\r", "\n", "\t"]:
        s = s.replace(ch, " ")
    return s.strip()


def parse_date_obj(val: Any) -> Optional[date]:
    """
    Herhangi bir tarih formatını veya nesnesini datetime.date nesnesine çevirir.
    Desteklenenler:
    - datetime veya date nesnesi
    - PyQt6 QDate nesnesi
    - 'YYYY-MM-DD', 'DD-MM-YYYY', 'DD.MM.YYYY', 'DD/MM/YYYY', 'YYYY/MM/DD', 'YYYY.MM.DD'
    - ISO timestamp ('2026-10-17T18:22:36...')
    Veri Temizleme (Sanitization) ve Hata Yakalama (Try-Except) uygulanmıştır.
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val

    # QDate veya duck-typing tarih nesnesi
    if hasattr(val, "toPyDate"):
        try:
            return val.toPyDate()
        except Exception:
            pass
    if hasattr(val, "year") and hasattr(val, "month") and hasattr(val, "day") and callable(getattr(val, "year")):
        try:
            if hasattr(val, "isValid") and not val.isValid():
                return None
            return date(val.year(), val.month(), val.day())
        except Exception:
            pass

    # Veri Temizleme (Sanitization): Görünmeyen karakter ve boşlukları temizle
    s = sanitize_date_str(val)
    if not s or s.lower() in ["none", "null", ""]:
        return None

    # Zaman kısmını temizle (ISO format veya saat)
    s = s.split("T")[0].split(" ")[0].strip()

    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y.%m.%d",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    # Regex ile güvenli ayrıştırma (DD.MM.YYYY veya YYYY.MM.DD)
    try:
        m = re.match(r"^(\d{1,4})[\.\-\/](\d{1,2})[\.\-\/](\d{1,4})$", s)
        if m:
            p1, p2, p3 = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if p1 > 1000:  # YYYY-MM-DD
                return date(p1, p2, p3)
            elif p3 > 1000:  # DD-MM-YYYY
                return date(p3, p2, p1)
    except ValueError as ve:
        print(f"[Tarih Ayrıştırma Uyarısı] '{s}' değeri ayrıştırılamadı (ValueError): {ve}")
    except Exception as e:
        print(f"[Tarih Ayrıştırma Uyarısı] '{s}' ayrıştırılırken beklenmeyen hata: {e}")

    return None


def get_app_base_dir() -> str:
    """
    Uygulamanın çalıştığı ana dizini döner.
    PyInstaller ile --onefile parametresiyle (.exe) paketlendiğinde:
        Geçici sys._MEIPASS klasörü yerine doğrudan .exe dosyasının
        çalıştığı dizini (os.path.dirname(sys.executable)) referans alır.
    Normal Python (.py) çalıştırmasında:
        Projenin kök çalışma dizinini referans alır.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller .exe çalışma dizini (sys._MEIPASS yerine doğrudan .exe'nin bulunduğu klasör)
        return os.path.dirname(os.path.abspath(sys.executable))

    # Normal Python çalıştırması: src/ klasöründen proje ana dizinine çıkış
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class InvoiceDatabase:
    """TasımaBelgeler/infos.json dosyasını yöneten yerel JSON veritabanı sınıfı."""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = get_app_base_dir()
        self.base_dir = os.path.abspath(base_dir)
        self.storage_dir = os.path.join(self.base_dir, "TasımaBelgeler")
        self.json_path = os.path.join(self.storage_dir, "infos.json")
        self.lock = threading.RLock()

        self._ensure_storage_exists()

    def _ensure_storage_exists(self) -> None:
        """TasımaBelgeler dizini ve infos.json dosyasının varlığından emin olur."""
        os.makedirs(self.storage_dir, exist_ok=True)
        if not os.path.exists(self.json_path):
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    def load_all(self) -> List[Dict[str, Any]]:
        """Tüm fatura kayıtlarını JSON dosyasından okur."""
        with self.lock:
            try:
                if not os.path.exists(self.json_path):
                    self._ensure_storage_exists()
                with open(self.json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    items = []
                    if isinstance(data, list):
                        items = data
                    elif isinstance(data, dict) and "invoices" in data:
                        items = data["invoices"]

                    for inv in items:
                        if "total_amount" not in inv or inv.get("total_amount") is None:
                            tax_ex = float(inv.get("tax_excluded_amount") or 0.0)
                            kdv = float(inv.get("kdv_amount") or 0.0)
                            inv["total_amount"] = round(tax_ex + kdv, 2)
                    return items
            except (json.JSONDecodeError, OSError):
                return []

    def save_all(self, invoices: List[Dict[str, Any]]) -> bool:
        """Kayıtları güvenli ve atomik şekilde infos.json dosyasına kaydeder."""
        with self.lock:
            try:
                temp_file = tempfile.NamedTemporaryFile(
                    mode="w",
                    dir=self.storage_dir,
                    delete=False,
                    encoding="utf-8",
                )
                json.dump(invoices, temp_file, ensure_ascii=False, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_file.close()
                shutil.move(temp_file.name, self.json_path)
                return True
            except Exception as e:
                print(f"[Database Error] Kaydetme hatası: {e}")
                return False

    def is_duplicate(self, invoice_number: str) -> bool:
        """Fatura numarasının kayıtlı olup olmadığını kontrol eder (Mükerrer kontrolü)."""
        if not invoice_number:
            return False
        clean_no = invoice_number.strip().upper()
        invoices = self.load_all()
        for inv in invoices:
            if str(inv.get("invoice_number", "")).strip().upper() == clean_no:
                return True
        return False

    def get_invoice(self, invoice_number: str) -> Optional[Dict[str, Any]]:
        """Fatura numarasına göre faturayı bulur."""
        if not invoice_number:
            return None
        clean_no = invoice_number.strip().upper()
        invoices = self.load_all()
        for inv in invoices:
            if str(inv.get("invoice_number", "")).strip().upper() == clean_no:
                return inv
        return None

    def add_invoice(self, invoice_data: Dict[str, Any]) -> bool:
        """Yeni faturayı ekler. Mükerrer ise False döner."""
        inv_no = str(invoice_data.get("invoice_number", "")).strip()
        if not inv_no:
            return False

        with self.lock:
            # Mükerrer kontrolü
            invoices = self.load_all()
            for inv in invoices:
                if str(inv.get("invoice_number", "")).strip().upper() == inv_no.upper():
                    return False  # Mükerrer kayıt engeli

            # Statü kontrolü: Son ödeme tarihi yoksa Düzenlenecek Faturalar statüsü
            due_date = invoice_data.get("due_date")
            if not due_date or str(due_date).strip().lower() in ["", "none", "null"]:
                invoice_data["due_date"] = None
                invoice_data["status"] = "pending_due_date"
            else:
                if "status" not in invoice_data or invoice_data["status"] == "pending_due_date":
                    invoice_data["status"] = "active"

            if "total_amount" not in invoice_data or invoice_data.get("total_amount") is None:
                tax_ex = float(invoice_data.get("tax_excluded_amount") or 0.0)
                kdv = float(invoice_data.get("kdv_amount") or 0.0)
                invoice_data["total_amount"] = round(tax_ex + kdv, 2)

            if "created_at" not in invoice_data:
                invoice_data["created_at"] = datetime.now().isoformat()
            invoice_data["updated_at"] = datetime.now().isoformat()

            invoices.append(invoice_data)
            return self.save_all(invoices)

    def update_invoice(self, invoice_number: str, updates: Dict[str, Any]) -> bool:
        """Belirtilen faturayı günceller."""
        if not invoice_number:
            return False

        clean_no = invoice_number.strip().upper()
        invoices = self.load_all()
        found = False

        for i, inv in enumerate(invoices):
            if str(inv.get("invoice_number", "")).strip().upper() == clean_no:
                # Güncellemeleri uygula
                invoices[i].update(updates)
                invoices[i]["updated_at"] = datetime.now().isoformat()
                found = True
                break

        if found:
            return self.save_all(invoices)
        return False

    def delete_invoice(self, invoice_number: str) -> bool:
        """Faturayı siler (kullanıcı manuel arayüzden kaldırmak isterse)."""
        clean_no = invoice_number.strip().upper()
        invoices = self.load_all()
        filtered = [inv for inv in invoices if str(inv.get("invoice_number", "")).strip().upper() != clean_no]
        if len(filtered) != len(invoices):
            return self.save_all(filtered)
        return False

    # --- Filtrelenmiş Liste Fonksiyonları ---

    def get_pending_invoices(self) -> List[Dict[str, Any]]:
        """Sekme 1: Düzenlenecek Faturalar (Son ödeme tarihi eksik olanlar)."""
        invoices = self.load_all()
        result = []
        for inv in invoices:
            due = inv.get("due_date")
            status = inv.get("status")
            if status == "pending_due_date" or not due or str(due).strip().lower() in ["", "none", "null"]:
                result.append(inv)
        return result

    def get_all_complete_invoices(self) -> List[Dict[str, Any]]:
        """Sekme 2: Tüm Faturalar (Bilgileri tam olan tüm faturalar: Aktif ve Ödenmiş)."""
        invoices = self.load_all()
        result = []
        for inv in invoices:
            due = inv.get("due_date")
            status = inv.get("status")
            if due and str(due).strip().lower() not in ["", "none", "null"] and status != "pending_due_date":
                result.append(inv)
        return result

    def get_due_invoices(self, reference_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Sekme 3: Vadesi Gelmiş Faturalar (Vadesi bugüne eşit veya geçmiş, henüz ödenmemiş olanlar)."""
        ref_dt = parse_date_obj(reference_date) or datetime.now().date()

        invoices = self.load_all()
        result = []
        for inv in invoices:
            status = str(inv.get("status", "")).strip().lower()
            due = inv.get("due_date")
            # Ödenmemiş ve son ödeme tarihi var
            if status not in ["paid", "ödendi", "odendi"] and due and str(due).strip().lower() not in ["", "none", "null"] and status != "pending_due_date":
                due_dt = parse_date_obj(due)
                if due_dt and due_dt <= ref_dt:
                    result.append(inv)
        return result

    def get_paid_invoices(
        self,
        start_date: Any = None,
        end_date: Any = None
    ) -> List[Dict[str, Any]]:
        """
        Sekme 4: Ödenmiş Faturalar (Tarih filtreli).
        Eğer kullanıcı başlangıç veya bitiş tarihlerinden birini veya ikisini boş bırakırsa,
        program hata vermez; tüm 'Ödenmiş' faturaları filtresiz olarak tam liste halinde döndürür.
        Tarihler datetime nesnelerine dönüştürülerek matematiksel büyüklük/küçüklük
        karşılaştırması yapılır: start_date <= fatura/ödeme tarihi <= end_date.
        """
        invoices = self.load_all()
        paid_invoices = [
            inv for inv in invoices
            if str(inv.get("status", "")).strip().lower() in ["paid", "ödendi", "odendi"]
        ]

        start_dt = parse_date_obj(start_date)
        end_dt = parse_date_obj(end_date)

        # Boş Tarih Kontrolü (Hata Önleme):
        # Biri veya ikisi boş veya geçersiz ise, tüm ödenmiş faturaları filtresiz tam liste döndür
        if start_dt is None or end_dt is None:
            return paid_invoices

        # Tarihler ters seçilmişse düzelt
        if start_dt > end_dt:
            start_dt, end_dt = end_dt, start_dt

        result = []
        for inv in paid_invoices:
            inv_no = inv.get("invoice_number", "Bilinmeyen")
            try:
                p_date = parse_date_obj(inv.get("payment_date"))
                i_date = parse_date_obj(inv.get("invoice_date"))

                # Sadece Başlangıç Tarihi <= Fatura/Ödeme Tarihi <= Bitiş Tarihi şartını sağlayanlar
                in_range = False
                if p_date and (start_dt <= p_date <= end_dt):
                    in_range = True
                elif i_date and (start_dt <= i_date <= end_dt):
                    in_range = True

                if in_range:
                    result.append(inv)
            except ValueError as ve:
                print(f"[Tarih Karşılaştırma Hatası] Fatura No: {inv_no}, ValueError: {ve}, Ödeme: {inv.get('payment_date')}, Fatura: {inv.get('invoice_date')}")
            except Exception as e:
                print(f"[Tarih Karşılaştırma Hatası] Fatura No: {inv_no}, Hata: {e}")

        return result
