import os
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import pymupdf  # PyMuPDF
import pdfplumber


class PDFExtractor:
    """PDF fatura ve taşıma belgelerinden veri ayrıştırıcı (Extractor)."""

    def __init__(self):
        # 16 Haneli e-Fatura / e-Arşiv deseni (3 harf/rakam + 4 yıl + 9 sıra)
        self.invoice_no_standard_regex = re.compile(r"\b([A-Z0-9]{3}20\d{2}\d{9})\b")

        # Fatura No etiketli aramalar
        self.invoice_no_labels = [
            re.compile(r"Fatura\s+No(?:su)?\s*[:\-\s]+([A-Z0-9\-\/]{6,25})", re.IGNORECASE),
            re.compile(r"Fatura\s+Numarası\s*[:\-\s]+([A-Z0-9\-\/]{6,25})", re.IGNORECASE),
            re.compile(r"Belge\s+No(?:su)?\s*[:\-\s]+([A-Z0-9\-\/]{6,25})", re.IGNORECASE),
            re.compile(r"İrsaliye\s+No(?:su)?\s*[:\-\s]+([A-Z0-9\-\/]{6,25})", re.IGNORECASE),
            re.compile(r"Invoice\s+No(?:umber)?\s*[:\-\s]+([A-Z0-9\-\/]{6,25})", re.IGNORECASE),
        ]

        # Tarih desenleri
        self.date_regex = re.compile(r"\b(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})\b")

        # Fatura Tarihi etiketleri
        self.invoice_date_labels = [
            re.compile(r"Fatura\s+Tarihi\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"Düzenleme\s+Tarihi\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"Belge\s+Tarihi\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"İrsaliye\s+Tarihi\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"Invoice\s+Date\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"Tarih\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
        ]

        # Son Ödeme Tarihi (Vade) etiketleri
        self.due_date_labels = [
            re.compile(r"Son\s+Ödeme\s+Tarihi\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"Ödeme\s+Vadesi\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"Vade\s+Tarihi\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"Vadesi\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"Due\s+Date\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
            re.compile(r"Payment\s+Due\s*[:\-\s]+(\d{1,2}\s*[\.\/\-]\s*\d{1,2}\s*[\.\/\-]\s*\d{4})", re.IGNORECASE),
        ]

        # Tutar etiketleri
        self.amount_labels = [
            re.compile(r"Ödenecek\s+Tutar\s*[:\-\s]*([0-9\.,\s]+(?:TL|TRY|USD|EUR)?)\b", re.IGNORECASE),
            re.compile(r"Genel\s+Toplam\s*[:\-\s]*([0-9\.,\s]+(?:TL|TRY|USD|EUR)?)\b", re.IGNORECASE),
            re.compile(r"Toplam\s+Tutar\s*[:\-\s]*([0-9\.,\s]+(?:TL|TRY|USD|EUR)?)\b", re.IGNORECASE),
            re.compile(r"Vergiler\s+Dahil\s+Toplam\s*[:\-\s]*([0-9\.,\s]+(?:TL|TRY|USD|EUR)?)\b", re.IGNORECASE),
            re.compile(r"Fatura\s+Tutarı\s*[:\-\s]*([0-9\.,\s]+(?:TL|TRY|USD|EUR)?)\b", re.IGNORECASE),
            re.compile(r"Total\s+Amount\s*[:\-\s]*([0-9\.,\s]+(?:TL|TRY|USD|EUR)?)\b", re.IGNORECASE),
            re.compile(r"TOPLAM\s*[:\-\s]*([0-9\.,\s]+(?:TL|TRY|USD|EUR)?)\b", re.IGNORECASE),
        ]

        # Şirket / Kurumsal ibareleri
        self.company_keywords = [
            "TİC", "SAN", "LTD", "ŞTİ", "A.Ş", "ANONİM", "LİMİTED", "LOJİSTİK",
            "NAKLİYAT", "TAŞIMACILIK", "KARGO", "DAĞITIM", "HOLDİNG", "HİZMETLERİ"
        ]

    def extract_text_pymupdf(self, pdf_path: str) -> str:
        """PyMuPDF ile metin çıkarma."""
        text = ""
        try:
            doc = pymupdf.open(pdf_path)
            for page in doc:
                text += page.get_text() + "\n"
            doc.close()
        except Exception as e:
            print(f"[PDF Extract] PyMuPDF hatası ({pdf_path}): {e}")
        return text

    def extract_text_pdfplumber(self, pdf_path: str) -> str:
        """pdfplumber ile metin çıkarma."""
        text = ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
        except Exception as e:
            print(f"[PDF Extract] pdfplumber hatası ({pdf_path}): {e}")
        return text

    def get_full_text(self, pdf_path: str) -> str:
        """PDF dosyasından en iyi metni çıkarır."""
        text = self.extract_text_pymupdf(pdf_path)
        if len(text.strip()) < 50:
            plumber_text = self.extract_text_pdfplumber(pdf_path)
            if len(plumber_text.strip()) > len(text.strip()):
                text = plumber_text
        return text

    def normalize_date(self, date_str: str) -> Optional[str]:
        """Tarih dizgesini YYYY-MM-DD formatına çevirir."""
        if not date_str:
            return None
        clean = re.sub(r"\s+", "", date_str).strip().replace("/", ".").replace("-", ".")
        parts = clean.split(".")
        if len(parts) == 3:
            try:
                # Gün ve Ay tespiti
                if len(parts[0]) == 4:  # YYYY.MM.DD
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                else:  # DD.MM.YYYY
                    day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                dt = datetime(year, month, day)
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
        return None

    def parse_amount(self, amount_str: str) -> Tuple[float, str]:
        """
        Para tutarını float sayıya ve para birimine ayrıştırır.
        Örnekler: '14.500,50 TL', '14,500.50 TRY', '1250.00', '1.250,00'
        """
        currency = "TL"
        if "USD" in amount_str.upper() or "$" in amount_str:
            currency = "USD"
        elif "EUR" in amount_str.upper() or "€" in amount_str:
            currency = "EUR"

        # Para birimi ve harfleri temizle
        clean = re.sub(r"[^\d,\.]", "", amount_str).strip()
        if not clean:
            return 0.0, currency

        try:
            # Durum 1: 14.500,50 (Türk standardı: Binlik nokta, ondalık virgül)
            if "." in clean and "," in clean:
                if clean.rfind(",") > clean.rfind("."):
                    clean = clean.replace(".", "").replace(",", ".")
                else:  # 14,500.50 (İngiliz standardı: Binlik virgül, ondalık nokta)
                    clean = clean.replace(",", "")
            # Durum 2: Sadece virgül var -> 14500,50
            elif "," in clean:
                clean = clean.replace(",", ".")
            # Durum 3: Sadece nokta var -> 14.500 (binlik) ya da 14500.50 (ondalık)
            elif "." in clean:
                parts = clean.split(".")
                if len(parts) == 2 and len(parts[1]) == 3 and float(clean) < 1000:
                    # 1.500 -> 1500
                    clean = clean.replace(".", "")
                # diğer durumlarda standart float bırakılır

            val = float(clean)
            return round(val, 2), currency
        except Exception:
            return 0.0, currency

    def clean_text_encoding(self, text: str) -> str:
        """PDF font encoding kaynaklı bozuk Türkçe karakterleri düzeltir."""
        replacements = {
            "A.·.": "A.Ş.",
            "A.·": "A.Ş.",
            "·T·": "ŞTİ",
            "TA·IMACILIK": "TAŞIMACILIK",
            "DA·ITIM": "DAĞITIM",
            "LOJ·ST·K": "LOJİSTİK",
            "NAKL·YAT": "NAKLİYAT",
            "S·GMA": "SİGMA",
            "F·RMA": "FİRMA",
        }
        for bad, good in replacements.items():
            text = text.replace(bad, good)
        return text

    def _is_address_or_tax_line(self, line: str) -> bool:
        """Satırın adres, vergi dairesi, kimlik no veya belge başlığı olup olmadığını kontrol eder."""
        u = line.upper().strip()

        # Vergi dairesi, TCKN, VKN, ETTN veya e-belge meta verileri
        tax_keywords = [
            "VERGİ DAİRESİ", "VERGI DAIRESI", "VERGİ NO", "VERGI NO",
            "TCKN", "VKN", "T.C. KİMLİK", "T.C.K.N",
            "ETTN", "E-FATURA", "E-ARŞİV", "ÖZELLEŞTİRME NO", "SENARYO",
            "FATURA TİPİ", "FATURA TIPI", "OLUŞMA ZAMANI", "DÜZENLEME SAATİ",
            "SIRA NO", "MAL HİZMET", "BİRİM FİYAT", "KDV ORANI", "KDV TUTARI"
        ]
        if any(k in u for k in tax_keywords):
            return True

        # İlçe/İl ayracı kalıbı (Örn: "gebze/ KOCAELİ", "Merkez/ AFYONKARAHİSAR", "PENDİK/ İSTANBUL")
        if "/" in line and not any(k in u for k in ["A.Ş", "LTD", "ŞTİ", "SAN", "TİC"]):
            parts = [p.strip() for p in line.split("/") if p.strip()]
            if len(parts) == 2 and len(parts[0]) <= 30 and len(parts[1]) <= 30:
                return True

        # Yaygın adres terimleri
        addr_keywords = [
            "MAH.", "MAHALLESİ", "MAHALLESI", "CAD.", "CADDESİ", "CADDESI",
            "SOK.", "SOKAK", "SOKAĞI", "NO:", "KAPI NO", "BULV.", "BULVARI",
            "SİTESİ", "SITESI", "KAT:", "DAİRE:", "DAIRE:", "POSTA KODU", "PK:",
            "TÜRKİYE", "TURKEY", "TEL:", "E-POSTA:", "EMAIL:"
        ]
        if any(k in u for k in addr_keywords):
            return True

        return False

    def _is_numeric_or_invoice_meta(self, line: str) -> bool:
        """Satırın sırf rakamlardan (TCKN/VKN/Fatura No) veya meta veriden oluşup oluşmadığını denetler."""
        clean = re.sub(r"[\s\.\,\-\/\:\_]", "", line).strip()
        # Sadece rakamlardan oluşuyorsa (örneğin 21749652220 veya 7601137411)
        if clean.isdigit():
            return True
        # Çok az harf, çok fazla rakam varsa
        letters = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]", line)
        digits = re.findall(r"\d", line)
        if digits and len(digits) >= 10 and len(letters) < 4:
            return True
        return False

    def _is_valid_company_or_person_name(self, name: str) -> bool:
        """İsmin geçerli bir şahıs veya şirket adı olup olmadığını doğrular."""
        if not name or len(name.strip()) < 3:
            return False
        clean = name.strip()
        # Rakam kontrolü: İsmin tamamı veya büyük kısmı rakam olamaz
        digits = re.findall(r"\d", clean)
        letters = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]", clean)
        if len(letters) < 3:
            return False
        if len(digits) > len(letters):
            return False
        # TCKN veya VKN benzeri 10-11 haneli seri rakam içeriyorsa
        if re.search(r"\b\d{10,11}\b", clean):
            return False
        return True

    def find_company_name(self, text: str, file_name: str = "") -> str:
        """
        PDF içerisindeki 'SAYIN' kelimesinden hemen sonraki satırdan başlayarak,
        adres bilgisi veya 'Vergi Dairesi' ibaresine kadar olan şirket/şahıs adını ayıklar.
        TCKN/VKN gibi rakamlardan oluşan kimliklerin atanmasını kesinlikle engeller.
        """
        text = self.clean_text_encoding(text)
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # 1. ÖNCELİKLİ YÖNTEM: 'SAYIN' kelimesi ve altındaki alan
        for i, line in enumerate(lines):
            line_clean = line.strip()
            line_upper = line_clean.upper()

            if line_upper == "SAYIN" or line_upper.startswith("SAYIN ") or line_upper.startswith("SAYIN:"):
                collected_parts = []

                # Eğer aynı satırda "SAYIN MEHMET ŞAHİN" gibi metin varsa:
                after_sayin = re.sub(r"^SAYIN\s*[:\-\s]*", "", line_clean, flags=re.IGNORECASE).strip()
                if after_sayin and not self._is_address_or_tax_line(after_sayin):
                    collected_parts.append(after_sayin)

                # SAYIN'dan sonraki satırları tara (en fazla 6 satır)
                for next_line in lines[i + 1 : i + 7]:
                    next_clean = next_line.strip()
                    if not next_clean:
                        continue

                    # Adres, Vergi Dairesi, TCKN/VKN veya fatura meta verisine geldiysek dur
                    if self._is_address_or_tax_line(next_clean) or self._is_numeric_or_invoice_meta(next_clean):
                        break

                    collected_parts.append(next_clean)

                if collected_parts:
                    full_name = " ".join(collected_parts).strip()
                    full_name = re.sub(r"\s+", " ", full_name)
                    if self._is_valid_company_or_person_name(full_name):
                        return full_name

        # 2. İKİNCİL YÖNTEM: Alıcı/Müşteri etiketli satırlar
        for line in lines[:45]:
            clean_l = line.strip()
            m = re.search(r"^(?:ALICI\s*(?:\/|\-)?\s*F[İI]RMA|ALICI|MÜŞTER[İI]|F[İI]RMA\s*ADI|[UÜ]NVAN)\s*[:\-\/\s]+(.*)", clean_l, re.IGNORECASE)
            if m:
                extracted = m.group(1).strip()
                extracted = re.sub(r"^[/\-:\s]+", "", extracted).strip()
                if self._is_valid_company_or_person_name(extracted) and not self._is_address_or_tax_line(extracted):
                    return extracted

        # 3. ÜÇÜNCÜ YÖNTEM: Kurumsal unvan içeren satırlar (LTD, ŞTİ, A.Ş.)
        candidate_lines = []
        for line in lines[:45]:
            clean_l = line.strip()
            line_upper = clean_l.upper()
            score = sum(1 for kw in self.company_keywords if kw in line_upper)
            if score > 0 and 5 < len(clean_l) < 120:
                if not any(ex in line_upper for ex in ["FATURA NO", "VERGİ DAİRESİ", "E-FATURA", "E-ARŞİV", "ÖDENECEK TUTAR", "GENEL TOPLAM"]):
                    cleaned = re.sub(r"^(?:ALICI|SATICI|F[İI]RMA|MÜŞTER[İI]|\/)\s*[:\-\/\s]+", "", clean_l, flags=re.IGNORECASE).strip()
                    if self._is_valid_company_or_person_name(cleaned):
                        candidate_lines.append((score, cleaned))

        if candidate_lines:
            candidate_lines.sort(key=lambda x: x[0], reverse=True)
            return candidate_lines[0][1]

        # 4. KESİN KURAL: Dosya adı asla TCKN/VKN rakamlarından oluşuyorsa isim olarak kullanılmaz!
        clean_file = os.path.splitext(os.path.basename(file_name))[0]
        # Eğer dosya adı formatı TCKN_ISIM_FATURANO şeklindeyse (Örn: 56965408542_SADIK UYANIK_EAA2026000000001.pdf):
        fn_parts = clean_file.split("_")
        if len(fn_parts) >= 2:
            for p in fn_parts:
                p_strip = p.strip()
                if self._is_valid_company_or_person_name(p_strip) and not self.invoice_no_standard_regex.search(p_strip):
                    return p_strip.upper()

        # Eğer dosya adı rakamlarla başlıyorsa (örn: 21749652220_AAA...):
        clean_file = re.sub(r"^\d+[\_\-]*", "", clean_file).strip()
        clean_file = clean_file.replace("_", " ").replace("-", " ")
        if self._is_valid_company_or_person_name(clean_file):
            return clean_file.title()

        return "Bilinmeyen Müşteri / Şirket"

    def find_invoice_number(self, text: str, file_name: str = "") -> str:
        """Fatura numarasını tespit eder (GİB 16 hane standardı veya etiketli)."""
        # 1. Standart 16 haneli e-Fatura / e-Arşiv numarası (Örn: ABC2026000001234, EAA2026000000001)
        m_std = self.invoice_no_standard_regex.search(text)
        if m_std:
            return m_std.group(1).strip()

        # 1.1 Dosya adında standart 16 haneli e-Fatura / e-Arşiv numarası var mı?
        if file_name:
            m_fn = self.invoice_no_standard_regex.search(file_name)
            if m_fn:
                return m_fn.group(1).strip()

        # 2. Etiketli aramalar
        for pattern in self.invoice_no_labels:
            m = pattern.search(text)
            if m:
                inv_no = m.group(1).strip()
                # Geçersiz karakterleri temizle
                inv_no = re.sub(r"[^\w\-\/]", "", inv_no)
                if len(inv_no) >= 4:
                    return inv_no

        # 3. Dosya adından fatura no çıkarma fallback
        base = os.path.splitext(os.path.basename(file_name))[0]
        # Eğer dosya adı fatura no formatındaysa (FTR123, 2026001 vb.)
        clean_base = re.sub(r"[^\w\-]", "", base)
        if len(clean_base) >= 4:
            return clean_base.upper()

        # Son çare: Zaman damgalı unique kod
        return f"FTR-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def find_invoice_date(self, text: str) -> str:
        """Fatura kesim tarihini bulur."""
        for pattern in self.invoice_date_labels:
            m = pattern.search(text)
            if m:
                norm = self.normalize_date(m.group(1))
                if norm:
                    return norm

        # Etiket yoksa ilk geçerli tarihi al
        matches = self.date_regex.findall(text)
        for d in matches:
            norm = self.normalize_date(d)
            if norm:
                return norm

        # Fallback: Bugün
        return datetime.now().strftime("%Y-%m-%d")

    def find_due_date(self, text: str) -> Optional[str]:
        """
        Son Ödeme Tarihini bulur.
        Eğer metinde Son Ödeme Tarihi yoksa None döner (örnek: sig.pdf).
        """
        for pattern in self.due_date_labels:
            m = pattern.search(text)
            if m:
                norm = self.normalize_date(m.group(1))
                if norm:
                    return norm
        return None

    def find_amount(self, text: str) -> Tuple[float, str]:
        """Ödenecek tutarı bulur."""
        for pattern in self.amount_labels:
            m = pattern.search(text)
            if m:
                raw_amt = m.group(1).strip()
                amt, cur = self.parse_amount(raw_amt)
                if amt > 0:
                    return amt, cur

        # Tablodan veya metinden "Toplam" sonrası gelen sayıları ara
        lines = text.split("\n")
        for line in reversed(lines):  # Toplamlar genellikle sayfanın altındadır
            if any(k in line.upper() for k in ["TOPLAM", "TUTAR", "ÖDENECEK"]):
                numbers = re.findall(r"[\d\.,]+", line)
                for num_str in reversed(numbers):
                    amt, cur = self.parse_amount(num_str)
                    if amt > 0:
                        return amt, cur

        return 0.0, "TL"

    def _extract_monetary_value_from_line(self, line: str, next_lines: list = None) -> Tuple[float, str]:
        """
        Bir etiket satırından veya takip eden satırlardan para tutarını ayrıştırır.
        %20, %18, %10 gibi vergi oranlarını veya yüzdeleri filtreler, asıl parasal tutarı bulur.
        """
        clean_line = line.strip()

        # 1. Satırda ':' varsa sağ tarafını kontrol et
        if ":" in clean_line:
            after_colon = clean_line.split(":", 1)[1].strip()
            # %20 gibi oranları temizle
            after_colon_clean = re.sub(r"%\s*\d+", "", after_colon).strip()
            val, cur = self.parse_amount(after_colon_clean)
            if val > 0:
                return val, cur

        # 2. Satırdaki tüm sayıları incele (%20 gibi oranları eleyerek)
        without_percent = re.sub(r"%\s*\d+", "", clean_line)
        numbers = re.findall(r"[\d\.,]+", without_percent)
        for num_str in reversed(numbers):
            val, cur = self.parse_amount(num_str)
            if val > 0:
                for c in ["TL", "TRY", "USD", "EUR"]:
                    if c in line.upper():
                        cur = c
                return val, cur

        # 3. Sonraki satırlara bak (en fazla 3 satır)
        if next_lines:
            for nxt in next_lines[:3]:
                nxt_clean = nxt.strip()
                if not nxt_clean:
                    continue
                # Eğer satır sadece yüzde veya oran ise (%20, 20 vb.) atla
                if nxt_clean.startswith("%") or (nxt_clean.isdigit() and int(nxt_clean) in (1, 8, 10, 18, 20)):
                    continue
                clean_nxt = re.sub(r"%\s*\d+", "", nxt_clean)
                nxt_numbers = re.findall(r"[\d\.,]+", clean_nxt)
                for num_str in reversed(nxt_numbers):
                    val, cur = self.parse_amount(num_str)
                    if val > 0:
                        for c in ["TL", "TRY", "USD", "EUR"]:
                            if c in nxt.upper():
                                cur = c
                        return val, cur

        return 0.0, ""

    def find_all_amounts(self, text: str, file_name: str = "") -> Tuple[float, float, float, str]:
        """
        PDF içerisinden:
        1. Toplam Fiyat (Vergiler Dahil Toplam Tutar)
        2. Vergi Hariç Tutar (Mal Hizmet Toplam Tutarı / KDV Matrahı)
        3. KDV Tutarı (Hesaplanan KDV)
        ve Para Birimini tam eşleşme (Regex/Split) ve tutarlılık doğrulaması ile ayrıştırır.
        (total_amount, tax_excluded_amount, kdv_amount, currency) döner.
        """
        text_clean = self.clean_text_encoding(text)
        lines = [line.strip() for line in text_clean.splitlines() if line.strip()]

        total_amount = 0.0
        tax_excluded = 0.0
        kdv_amt = 0.0
        currency = "TL"

        # 1. SATIR SATIR TAM EŞLEŞME (SPLIT VE ETİKET TARAMA)
        for i, line in enumerate(lines):
            line_up = line.upper()
            next_slice = lines[i + 1 : i + 4] if i + 1 < len(lines) else []

            # Tablo sütun başlığı satırlarını atla (Örn: "Sıra No Mal Hizmet Miktar Birim Fiyat KDV Oranı KDV Tutarı")
            if any(h in line_up for h in ["BİRİM FİYAT", "BIRIM FIYAT", "MAL HİZMET", "MAL HIZMET"]) and any(h in line_up for h in ["SIRA", "MİKTAR", "MIKTAR", "ORANI"]):
                continue

            # A. KDV Tutarı ("Hesaplanan KDV", "HesaplananKDV", "KDV Tutarı", "Toplam KDV")
            # Öncelikli tam eşleşme: "Hesaplanan KDV" (boşluklu veya bitişik)
            if re.search(r"Hesaplanan\s*KDV", line, re.IGNORECASE) or any(k in line_up for k in ["HESAPLANAN KDV", "HESAPLANANKDV", "KDV TUTARI", "TOPLAM KDV", "VERGİ TUTARI", "VERGI TUTARI"]):
                if kdv_amt == 0.0:
                    val, cur = self._extract_monetary_value_from_line(line, next_slice)
                    if val > 0:
                        kdv_amt = val
                        if cur: currency = cur

            # B. Vergi Hariç Tutar ("Vergi Hariç Tutar", "VergiHariçTutar", "Mal Hizmet Toplam Tutarı", "KDV Matrahı")
            if re.search(r"Vergi\s*Hari[çc]", line, re.IGNORECASE) or any(k in line_up for k in ["VERGİ HARİÇ", "VERGI HARIC", "VERGİHARİÇ", "VERGIHARIC", "MAL HİZMET TOPLAM", "MAL HIZMET TOPLAM", "KDV MATRAHI", "MATRAH", "ARA TOPLAM"]):
                if tax_excluded == 0.0:
                    val, cur = self._extract_monetary_value_from_line(line, next_slice)
                    if val > 0:
                        tax_excluded = val
                        if cur: currency = cur

            # C. Toplam Fiyat / Vergiler Dahil ("Vergiler Dahil Toplam Tutar", "VergilerDahilToplamTutar", "Ödenecek Tutar", "Genel Toplam")
            if re.search(r"Vergiler\s*Dahil", line, re.IGNORECASE) or any(k in line_up for k in ["VERGİLER DAHİL TOPLAM", "VERGILER DAHIL TOPLAM", "VERGİLER DAHİL", "VERGILER DAHIL", "VERGİLERDAHİL", "VERGILERDAHIL", "ÖDENECEK TUTAR", "ODENECEK TUTAR", "GENEL TOPLAM"]):
                if total_amount == 0.0:
                    val, cur = self._extract_monetary_value_from_line(line, next_slice)
                    if val > 0:
                        total_amount = val
                        if cur: currency = cur

        # 2. REGEX İLE TAM VE GÜVENLİ ARAMA (FALLBACK)
        # KDV Tutarı Regex (özellikle %20 oranını atlayıp asıl KDV tutarını yakalar)
        if kdv_amt == 0.0:
            patterns_kdv = [
                re.compile(r"Hesaplanan\s+KDV(?:\s*\(?\s*%\s*\d+\s*\)?)?\s*[:\-\s]*([0-9\.,]+(?:\s*(?:TL|TRY|USD|EUR))?)", re.IGNORECASE),
                re.compile(r"(?:KDV\s+Tutar[ıi]|Toplam\s+KDV|Vergi\s+Tutar[ıi])\s*(?:\([^\)]*\))?\s*[:\-\s]*([0-9\.,]+(?:\s*(?:TL|TRY|USD|EUR))?)", re.IGNORECASE),
            ]
            for pat in patterns_kdv:
                m = pat.search(text_clean)
                if m:
                    raw_val = re.sub(r"%\s*\d+", "", m.group(1)).strip()
                    val, cur = self.parse_amount(raw_val)
                    if val > 0:
                        kdv_amt = val
                        if cur: currency = cur
                        break

        # Vergi Hariç Tutar Regex
        if tax_excluded == 0.0:
            patterns_tax_ex = [
                re.compile(r"(?:Vergi\s+Hariç\s+Tutar[ıi]?|Vergi\s+Haric\s+Tutar[ıi]?)\s*[:\-\s]*([0-9\.,]+(?:\s*(?:TL|TRY|USD|EUR))?)", re.IGNORECASE),
                re.compile(r"(?:Mal\s+Hizmet\s+Toplam\s+Tutar[ıi]?|Mal\s+Hizmet\s+Toplam[ıi]?|KDV\s+Matrah[ıi]?|Ara\s+Toplam)\s*[:\-\s]*([0-9\.,]+(?:\s*(?:TL|TRY|USD|EUR))?)", re.IGNORECASE),
            ]
            for pat in patterns_tax_ex:
                m = pat.search(text_clean)
                if m:
                    val, cur = self.parse_amount(m.group(1))
                    if val > 0:
                        tax_excluded = val
                        if cur: currency = cur
                        break

        # Toplam Fiyat / Vergiler Dahil Tutar Regex
        if total_amount == 0.0:
            patterns_total = [
                re.compile(r"(?:Vergiler\s+Dahil\s+Toplam\s+Tutar[ıi]?|Vergiler\s+Dahil\s+Toplam)\s*[:\-\s]*([0-9\.,]+(?:\s*(?:TL|TRY|USD|EUR))?)", re.IGNORECASE),
                re.compile(r"(?:Ödenecek\s+Tutar|Odenecek\s+Tutar|Genel\s+Toplam|Toplam\s+Tutar|Fatura\s+Tutar[ıi]?)\s*[:\-\s]*([0-9\.,]+(?:\s*(?:TL|TRY|USD|EUR))?)", re.IGNORECASE),
            ]
            for pat in patterns_total:
                m = pat.search(text_clean)
                if m:
                    val, cur = self.parse_amount(m.group(1))
                    if val > 0:
                        total_amount = val
                        if cur: currency = cur
                        break

        # Genel miktar araması fallback
        if total_amount == 0.0:
            gen_amt, gen_cur = self.find_amount(text_clean)
            if gen_amt > 0:
                total_amount = gen_amt
                if gen_cur: currency = gen_cur

        # 3. MATEMATİKSEL TUTARLILIK VE DENGELEME
        if total_amount > 0 and tax_excluded > 0 and kdv_amt == 0.0:
            kdv_amt = round(max(0.0, total_amount - tax_excluded), 2)
        elif tax_excluded > 0 and kdv_amt > 0 and total_amount == 0.0:
            total_amount = round(tax_excluded + kdv_amt, 2)
        elif total_amount > 0 and kdv_amt > 0 and tax_excluded == 0.0:
            tax_excluded = round(max(0.0, total_amount - kdv_amt), 2)
        elif total_amount > 0 and tax_excluded == 0.0 and kdv_amt == 0.0:
            # Standart KDV %20 varsayımı ile matrah ve KDV
            tax_excluded = round(total_amount / 1.20, 2)
            kdv_amt = round(total_amount - tax_excluded, 2)

        # Eğer vergi hariç + kdv toplam tutara eşit değilse ve toplam 0 değilse doğrula
        if tax_excluded > 0 and kdv_amt > 0:
            calc_total = round(tax_excluded + kdv_amt, 2)
            if total_amount == 0.0 or abs(calc_total - total_amount) > 0.05:
                if total_amount < tax_excluded:
                    total_amount = calc_total

        return round(total_amount, 2), round(tax_excluded, 2), round(kdv_amt, 2), currency

    def find_tax_amounts(self, text: str) -> Tuple[float, float, str]:
        """Geriye dönük uyumluluk: (Vergi Hariç Tutar, KDV Tutarı, Para Birimi) döner."""
        _, tax_ex, kdv, cur = self.find_all_amounts(text)
        return tax_ex, kdv, cur

    def process_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """
        PDF dosyasını okuyup tüm fatura verilerini çıkartır:
        1. Şirket / Şahıs İsmi
        2. Fatura No (Unique Key - GİB 16 hane standardı)
        3. Fatura Kesim Tarihi
        4. Toplam Fiyat (Vergiler Dahil)
        5. Vergi Hariç Tutar
        6. KDV Tutarı
        7. Son Ödeme Tarihi
        """
        file_name = os.path.basename(pdf_path)
        text = self.get_full_text(pdf_path)

        company_name = self.find_company_name(text, file_name)
        invoice_no = self.find_invoice_number(text, file_name)
        invoice_date = self.find_invoice_date(text)
        total_amount, tax_excluded_amount, kdv_amount, currency = self.find_all_amounts(text, file_name)
        due_date = self.find_due_date(text)

        # Durum belirleme: Son Ödeme Tarihi yoksa pending_due_date
        if due_date is None:
            status = "pending_due_date"
        else:
            status = "active"

        return {
            "invoice_number": invoice_no,
            "company_name": company_name,
            "invoice_date": invoice_date,
            "total_amount": total_amount,
            "tax_excluded_amount": tax_excluded_amount,
            "kdv_amount": kdv_amount,
            "currency": currency,
            "due_date": due_date,
            "status": status,
            "work_days_added": None,
            "paid_amount": None,
            "payment_date": None,
            "file_name": file_name,
            "file_path": os.path.abspath(pdf_path),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }


# Global extractor örneği
pdf_extractor = PDFExtractor()
