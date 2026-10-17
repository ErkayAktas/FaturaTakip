import os
from datetime import datetime, timedelta
import pymupdf


def create_invoice_pdf(
    file_path: str,
    company_name: str,
    invoice_no: str,
    invoice_date_str: str,
    amount_str: str,
    due_date_str: str = None,
):
    """PyMuPDF ile standart kurumsal e-Fatura formatında test PDF'i üretir."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4 boyutu

    # Başlık ve Tasarım
    # Üst banner
    page.draw_rect(pymupdf.Rect(40, 40, 555, 90), color=(0.15, 0.25, 0.45), fill=(0.15, 0.25, 0.45))
    page.insert_text(pymupdf.Point(55, 72), "E-ARŞİV FATURA / TAŞIMA BELGESİ", fontsize=15, color=(1, 1, 1))

    # Şirket ve Alıcı Bilgileri
    y = 120
    page.insert_text(pymupdf.Point(50, y), f"ALICI / FİRMA: {company_name}", fontsize=11, color=(0, 0, 0))
    y += 20
    page.insert_text(pymupdf.Point(50, y), "VKN / TCKN: 9876543210  |  Ticaret Sicil No: 123456", fontsize=9, color=(0.3, 0.3, 0.3))
    y += 15
    page.insert_text(pymupdf.Point(50, y), "Adres: Lojistik Merkez Mah. Taşıma Cad. No: 42 İstanbul", fontsize=9, color=(0.3, 0.3, 0.3))

    # Fatura Detay Kutusu
    page.draw_rect(pymupdf.Rect(340, 105, 555, 200), color=(0.7, 0.7, 0.7), width=1)
    page.insert_text(pymupdf.Point(350, 125), f"Fatura No: {invoice_no}", fontsize=10, color=(0, 0, 0))
    page.insert_text(pymupdf.Point(350, 145), f"Fatura Tarihi: {invoice_date_str}", fontsize=10, color=(0, 0, 0))
    page.insert_text(pymupdf.Point(350, 165), "Düzenleme Saati: 14:32:10", fontsize=9, color=(0.3, 0.3, 0.3))

    if due_date_str:
        page.insert_text(pymupdf.Point(350, 185), f"Son Ödeme Tarihi: {due_date_str}", fontsize=10, color=(0.8, 0, 0))

    # Taşıma Hizmet Kalemleri Tablosu
    y = 230
    page.draw_rect(pymupdf.Rect(40, y, 555, y + 25), color=(0.9, 0.9, 0.9), fill=(0.9, 0.9, 0.9))
    page.insert_text(pymupdf.Point(50, y + 17), "Hizmet / Mal Açıklaması", fontsize=9, color=(0, 0, 0))
    page.insert_text(pymupdf.Point(320, y + 17), "Miktar", fontsize=9, color=(0, 0, 0))
    page.insert_text(pymupdf.Point(400, y + 17), "Birim Fiyat", fontsize=9, color=(0, 0, 0))
    page.insert_text(pymupdf.Point(490, y + 17), "Tutar", fontsize=9, color=(0, 0, 0))

    y += 40
    page.insert_text(pymupdf.Point(50, y), "Şehirlerarası Karayolu Taşıma Bedeli", fontsize=9, color=(0, 0, 0))
    page.insert_text(pymupdf.Point(330, y), "1 Sefer", fontsize=9, color=(0, 0, 0))
    page.insert_text(pymupdf.Point(400, y), f"{amount_str}", fontsize=9, color=(0, 0, 0))
    page.insert_text(pymupdf.Point(490, y), f"{amount_str}", fontsize=9, color=(0, 0, 0))

    # Toplam ve Ödenecek Tutar
    y = 330
    page.draw_rect(pymupdf.Rect(340, y, 555, y + 60), color=(0.85, 0.9, 0.95), fill=(0.85, 0.9, 0.95))
    page.insert_text(pymupdf.Point(350, y + 22), "Toplam Tutar: " + amount_str, fontsize=10, color=(0, 0, 0))
    page.insert_text(pymupdf.Point(350, y + 45), "Ödenecek Tutar: " + amount_str, fontsize=11, color=(0, 0.2, 0.6))

    doc.save(file_path)
    doc.close()
    print(f"Oluşturuldu: {file_path}")


def generate_samples(target_dir: str):
    os.makedirs(target_dir, exist_ok=True)
    today = datetime.now().date()

    # 1. sig.pdf (Gereksinimde özellikle belirtilen: Son Ödeme Tarihi OLMAYAN fatura)
    create_invoice_pdf(
        file_path=os.path.join(target_dir, "sig.pdf"),
        company_name="SİGMA TAŞIMACILIK VE LOJİSTİK A.Ş.",
        invoice_no="SIG2026000000101",
        invoice_date_str=today.strftime("%d.%m.%Y"),
        amount_str="24.850,00 TL",
        due_date_str=None,  # Son Ödeme Tarihi YOK -> Düzenlenecek Faturalar
    )

    # 2. Vadesine 2 gün kalan fatura (Sarı Uyarı Testi)
    due_in_2 = today + timedelta(days=2)
    create_invoice_pdf(
        file_path=os.path.join(target_dir, "fatura_vade_2gun.pdf"),
        company_name="ANADOLU NAKLİYAT VE DAĞITIM LTD. ŞTİ.",
        invoice_no="ANA2026000000202",
        invoice_date_str=(today - timedelta(days=10)).strftime("%d.%m.%Y"),
        amount_str="18.400,50 TL",
        due_date_str=due_in_2.strftime("%d.%m.%Y"),
    )

    # 3. Vadesine 1 gün kalan fatura (Turuncu Uyarı Testi)
    due_in_1 = today + timedelta(days=1)
    create_invoice_pdf(
        file_path=os.path.join(target_dir, "fatura_vade_1gun.pdf"),
        company_name="MARMARA KARGO VE HIZLI LOJİSTİK A.Ş.",
        invoice_no="MAR2026000000303",
        invoice_date_str=(today - timedelta(days=14)).strftime("%d.%m.%Y"),
        amount_str="32.100,00 TL",
        due_date_str=due_in_1.strftime("%d.%m.%Y"),
    )

    # 4. Vadesi geçmiş fatura (Kırmızı Uyarı Testi)
    due_past = today - timedelta(days=3)
    create_invoice_pdf(
        file_path=os.path.join(target_dir, "fatura_vadesi_gecmis.pdf"),
        company_name="EGE TAŞIMA VE DEPOLAMA HİZMETLERİ",
        invoice_no="EGE2026000000404",
        invoice_date_str=(today - timedelta(days=25)).strftime("%d.%m.%Y"),
        amount_str="12.750,75 TL",
        due_date_str=due_past.strftime("%d.%m.%Y"),
    )

    # 5. Normal vadeli fatura (Örn: 20 gün sonra)
    due_normal = today + timedelta(days=20)
    create_invoice_pdf(
        file_path=os.path.join(target_dir, "fatura_normal_vade.pdf"),
        company_name="GLOBAL EKSPRES LOJİSTİK A.Ş.",
        invoice_no="GLB2026000000505",
        invoice_date_str=today.strftime("%d.%m.%Y"),
        amount_str="45.000,00 TL",
        due_date_str=due_normal.strftime("%d.%m.%Y"),
    )


if __name__ == "__main__":
    from src.database import get_app_base_dir

    target = os.path.join(get_app_base_dir(), "TasımaBelgeler", "TasımaFaturaları")
    generate_samples(target)
