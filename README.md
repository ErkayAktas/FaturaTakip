# 📄 Python Tabanlı Fatura Takip Uygulaması

Taşıma belgeleri ve lojistik faturalarının otomatik takibi, PDF'ten veri ayıklama, resmi tatil ve iş günü hesaplaması, durum uyarıları ve yerel JSON veritabanı yönetimi sağlayan modern masaüstü uygulaması.

---

## 🚀 Hızlı Başlangıç

### 1. Bağımlılıkların Yüklenmesi
Uygulama Python 3.10+ ve PyQt6 ile geliştirilmiştir. Gerekli kütüphaneleri yüklemek için:
```bash
cd /Users/erkayaktas/Desktop/Gravity/FaturaTakip
pip install -r requirements.txt
```

### 2. Uygulamanın Çalıştırılması
```bash
./baslat.sh
# veya
python3 main.py
```

---

## 📁 Dizin ve Veritabanı Yapısı

```
FaturaTakip/
├── TasımaBelgeler/
│   ├── infos.json                  # Yerel JSON veritabanı (Kalıcı kayıtlar)
│   └── TasımaFaturaları/           # Watchdog tarafından izlenen PDF klasörü
├── src/
│   ├── __init__.py
│   ├── database.py                 # infos.json okuma/yazma, mükerrer kontrolü, atomik kayıt
│   ├── holiday_service.py          # Türkiye resmi tatilleri + iş günü vade hesaplama
│   ├── pdf_extractor.py            # PyMuPDF ve pdfplumber ile akıllı veri ayıklama
│   ├── file_watcher.py             # Watchdog dizin izleme ve PyQt6 sinyal entegrasyonu
│   ├── dialogs.py                  # Vade Girişi Pop-up'ı & Ödeme Durumu Pop-up'ı
│   ├── components.py               # Sıralanabilir (Sortable) tablolar & KPI Kartları
│   └── styles.py                   # Modern Dark Obsidian QSS tema şablonu
├── main.py                         # Ana uygulama penceresi & sekmeler
├── generate_sample_pdfs.py         # Test faturaları ve sig.pdf üretici betik
├── baslat.sh                       # Tek tıkla başlatma betiği
└── requirements.txt                # Python bağımlılıkları
```

---

## 💡 Temel Özellikler ve Gereksinimlerin Karşılanması

### 1. Temel Altyapı ve Arayüz
- **PyQt6 & Modern Dark QSS**: Modern koyu tema, cam efektli kartlar, yüksek kontrastlı tipografi.
- **Dizin İzleme (Watchdog)**: `TasımaBelgeler/TasımaFaturaları` klasörü arka planda canlı izlenir. Yeni bir PDF geldiğinde otomatik olarak okunur ve sisteme dahil edilir.
- **Veri Muhafazası**: PDF dosyası dizinden silinse dahi, faturanın tüm bilgileri `TasımaBelgeler/infos.json` içinde güvenle ve kalıcı olarak muhafaza edilir.
- **Mükerrer Kayıt Engeli**: Fatura Numarası sistemde kayıtlıysa, aynı numaraya sahip belgeler otomatik olarak elenir ve mükerrer kayıt engellenir.

### 2. Veri Okuma ve İşleme (PDF Extraction)
PyMuPDF ve pdfplumber destekli akıllı regex motoru ile şu 5 temel veri otomatik ayrıştırılır:
1. **Şirket İsmi**: Alıcı, Müşteri, Sayın ve kurumsal şirket unvanları (A.Ş., Ltd. Şti., Lojistik vb.).
2. **Fatura No (Unique Key)**: 16 haneli e-Fatura standardı veya özel belge numaraları.
3. **Fatura Kesim Tarihi**: Gün.Ay.Yıl / Yıl-Ay-Gün formatları ISO standardına çevrilir.
4. **Ödenecek Tutar**: Para birimi (TL, USD, EUR) ve binlik/ondalık virgülleri doğru float sayıya dönüştürülür.
5. **Son Ödeme Tarihi**: Belgede vade tarihi varsa okunur; **yoksa** (örnek: `sig.pdf`), doğrudan **Düzenlenecek Faturalar** statüsüne atanır.

### 3. Ana Ekran ve Sekmeler

#### 📑 Sekme 1: Düzenlenecek Faturalar
- **İçerik**: Son ödeme tarihi eksik olan faturalar listelenir (`Şirket İsmi`, `Fatura No`, `Tarih`, `Ödenecek Tutar`).
- **Etkileşim**: Çift tıklandığında modern pop-up açılır.
- **Tatil ve Vade Hesabı**: Kullanıcıdan tam sayı olarak **Vade (Kaç İş Günü)** istenir. Türkiye'nin tatil takvimi (`holidays` kütüphanesi) kullanılarak Cumartesi, Pazar ve resmi tatiller (Cumhuriyet Bayramı, Ramazan/Kurban Bayramları vb.) otomatik atlanır.
- **Taşıma**: Onaylandığında veri `infos.json`'a kaydedilir, bu sekmeden silinir ve anında **Tüm Faturalar** sekmesine geçer.

#### 📑 Sekme 2: Tüm Faturalar
- **İçerik**: Bilgileri tam olan tüm faturalar (`Şirket İsmi`, `Fatura No`, `Tarih`, `Ödenecek Tutar`, `Son Ödeme Tarihi`, `Ödenme Durumu`, `Kalan Gün Sayısı`).
- **Uyarı Sistemi**:
  - 🟡 **Sarı Uyarı**: Vadesine 2 gün kalanlar
  - 🟠 **Turuncu Uyarı**: Vadesine 1 gün kalanlar
  - 🔴 **Kırmızı Uyarı**: Vadesi gelmiş / geçmiş olanlar
  - 🟢 **Yeşil**: Ödenmiş faturalar
- **Etkileşim**: Çift tıklanarak fatura **Ödendi** statüsüne alınabilir (Ödeme Tarihi ve Ödenen Tutar girilir). Yanlış girilmiş durumlar da bu ekrandan tekrar düzeltilebilir.

#### 📑 Sekme 3: Vadesi Gelmiş Faturalar
- **İçerik**: Vadesi bugüne eşit veya geçmiş, henüz ödenmemiş faturalar listelenir (`Şirket İsmi`, `Fatura No`, `Tarih`, `Ödenecek Tutar`, `Son Ödeme Tarihi`).
- Çift tıklanarak anında ödeme popup'ı açılır.

#### 📑 Sekme 4: Ödenmiş Faturalar
- **İçerik**: Ödemesi tamamlanan faturalar gösterilir (`Şirket İsmi`, `Fatura No`, `Tarih`, `Ödenmiş Tutar`, `Ödeme Tarihi`).
- **Araçlar**: Başlangıç ve Bitiş tarih seçicileri (`QDateEdit`) ve **Filtrele** / **Tümünü Göster** butonları.

### 4. Tablo ve Liste Özellikleri (Tüm Sekmeler İçin)
- **Sortable (Sıralanabilir Başlıklar)**: Sütun başlıklarına tıklandığında hem metinler alfabetik, hem tutarlar ve kalan günler sayısal, hem de tarihler kronolojik olarak küçükten büyüğe / büyükten küçüğe sıralanır.
- **Genel Arama Çubuğu (Search Bar)**: Üst barda yer alan global arama çubuğu ile Şirket İsmi veya Fatura No araması anında (canlı) filtreleme yapar.

---

## 🧪 Test Verileri
Örnek senaryoları hemen denemek için `generate_sample_pdfs.py` betiği hazır olarak sunulmuştur:
- `sig.pdf`: Vadesi olmayan (Düzenlenecek Faturalar sekmesini test etmek için)
- `fatura_vade_2gun.pdf`: Sarı uyarı testi
- `fatura_vade_1gun.pdf`: Turuncu uyarı testi
- `fatura_vadesi_gecmis.pdf`: Kırmızı uyarı testi
- `fatura_normal_vade.pdf`: Normal vadeli fatura
