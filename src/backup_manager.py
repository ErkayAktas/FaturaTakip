import hashlib
import json
import logging
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.database import get_app_base_dir

logger = logging.getLogger(__name__)

MAX_SNAPSHOTS_PER_CATEGORY = 50


class BackupManager:
    """
    Yerel Otomatik Sürüm Kaydı (Gelir ve Gider Snapshot Sistemi):
    - backups/infos/ (gelir / fatura kayıtları için)
    - backups/expenses/ (gider kayıtları için)
    Her kayıtta veya buluttan birleştirmeden önce zaman damgalı kopya oluşturur.
    Standartlaştırılmış JSON hash kontrolü ile içeriği birebir aynı olan tekrarları engeller.
    En güncel 50 sürümü saklar, eskileri otomatik temizler.
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or get_app_base_dir()
        self.backups_root = os.path.join(self.base_dir, "backups")
        self.infos_dir = os.path.join(self.backups_root, "infos")
        self.expenses_dir = os.path.join(self.backups_root, "expenses")

        # Otomatik klasör oluşturma
        os.makedirs(self.infos_dir, exist_ok=True)
        os.makedirs(self.expenses_dir, exist_ok=True)

    def get_backup_dir(self, category: str) -> str:
        """Kategoriye göre yedekleme klasörünü döner ('infos' veya 'expenses')."""
        cat = category.lower().strip()
        if "exp" in cat or "gider" in cat:
            d = self.expenses_dir
        else:
            d = self.infos_dir
        os.makedirs(d, exist_ok=True)
        return d

    @staticmethod
    def _calculate_json_content_hash(file_path: str) -> Optional[str]:
        """
        JSON dosyasının semantik içeriğini json.dumps(data, sort_keys=True) ile
        standartlaştırarak SHA-256 hash özetini hesaplar.
        Böylece anahtar sırası, boşluk veya girinti farkları nedeniyle
        aynı içeriğin tekrar yedeklenmesi engellenir.
        """
        if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            standardized = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
            return hashlib.sha256(standardized).hexdigest()
        except Exception as e:
            logger.warning(f"Standartlaştırılmış JSON hash hesaplama hatası ({file_path}): {e}")
            try:
                hasher = hashlib.sha256()
                with open(file_path, "rb") as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
                return hasher.hexdigest()
            except Exception:
                return None

    def create_snapshot(self, category: str, source_path: str) -> Optional[str]:
        """
        Kaynak dosyanın içeriği değiştiyse zaman damgalı bir snapshot (sürüm) oluşturur.
        Dönüş: Oluşturulan snapshot dosya yolu (veya değişiklik yoksa/hata varsa None).
        """
        if not source_path or not os.path.exists(source_path) or os.path.getsize(source_path) == 0:
            return None

        current_hash = self._calculate_json_content_hash(source_path)
        if not current_hash:
            return None

        dest_dir = self.get_backup_dir(category)
        cat_prefix = "expenses" if "exp" in category.lower() or "gider" in category.lower() else "infos"

        # backups/ klasöründeki en son yedek dosyasının hash'i ile birebir aynıysa yeni yedek dosyası oluşturma
        existing_files = self._get_sorted_backup_files(dest_dir)
        if existing_files:
            latest_backup = existing_files[0]
            latest_hash = self._calculate_json_content_hash(latest_backup)
            if latest_hash and latest_hash == current_hash:
                # İçerik tamamen aynı, mükerrer snapshot oluşturma!
                return None

        # Yeni zaman damgalı snapshot dosya adı
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target_filename = f"{cat_prefix}_{timestamp_str}.json"
        target_path = os.path.join(dest_dir, target_filename)

        # Aynı saniye içinde ikinci bir snapshot istenirse çakışmayı önle
        counter = 1
        while os.path.exists(target_path):
            target_filename = f"{cat_prefix}_{timestamp_str}_{counter}.json"
            target_path = os.path.join(dest_dir, target_filename)
            counter += 1

        try:
            # shutil.copyfile kullanılarak mtime metadata kopyalanması engellenir
            temp_copy = target_path + ".tmp"
            shutil.copyfile(source_path, temp_copy)
            shutil.move(temp_copy, target_path)
            logger.info(f"[Backup] Yeni {cat_prefix} sürümü kaydedildi: {target_filename}")

            # En fazla 50 sürüm sakla, eskileri otomatik temizle
            self._prune_old_backups(dest_dir, MAX_SNAPSHOTS_PER_CATEGORY)
            return target_path
        except Exception as e:
            logger.error(f"[Backup Hatası] Snapshot oluşturulamadı ({target_path}): {e}")
            if os.path.exists(temp_copy):
                try:
                    os.remove(temp_copy)
                except Exception:
                    pass
            return None

    def _get_sorted_backup_files(self, folder: str) -> List[str]:
        """Klasördeki .json yedek dosyalarını dosya adındaki zaman damgasına göre en yeniden en eskiye sıralı döner."""
        if not os.path.exists(folder):
            return []
        files = []
        for f in os.listdir(folder):
            if f.lower().endswith(".json") and not f.startswith("."):
                full_p = os.path.join(folder, f)
                if os.path.isfile(full_p):
                    files.append(full_p)
        # Dosya adı zaman damgalı (YYYY-MM-DD_HH-MM-SS) olduğundan ters sıralama en yeniyi ilk yapar
        files.sort(key=lambda x: os.path.basename(x), reverse=True)
        return files

    def _prune_old_backups(self, folder: str, max_count: int = MAX_SNAPSHOTS_PER_CATEGORY):
        """Klasördeki dosya sayısı max_count değerini aşıyorsa en eski olanları siler."""
        files = self._get_sorted_backup_files(folder)
        if len(files) > max_count:
            to_remove = files[max_count:]
            for old_file in to_remove:
                try:
                    os.remove(old_file)
                    logger.info(f"[Backup Temizlik] Eski sürüm temizlendi: {os.path.basename(old_file)}")
                except Exception as e:
                    logger.warning(f"Eski sürüm silinemedi ({old_file}): {e}")

    @staticmethod
    def _parse_datetime_from_filename(filename: str, file_path: Optional[str] = None) -> str:
        """
        Dosya adındaki YYYY-MM-DD_HH-MM-SS zaman damgasını parse ederek
        'DD.MM.YYYY HH:MM:SS' biçiminde okunabilir metne dönüştürür.
        Böylece listedeki saat ile dosya adındaki saat birebir tutar.
        """
        try:
            base_name = os.path.splitext(filename)[0]
            parts = base_name.split("_")
            if len(parts) >= 3:
                date_str = parts[1]
                time_str = parts[2]
                dt = datetime.strptime(f"{date_str}_{time_str}", "%Y-%m-%d_%H-%M-%S")
                return dt.strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            pass

        # Parse edilemezse mtime fallback
        if file_path and os.path.exists(file_path):
            try:
                return datetime.fromtimestamp(os.path.getmtime(file_path)).strftime("%d.%m.%Y %H:%M:%S")
            except Exception:
                pass
        return "-"

    def list_snapshots(self, category: str) -> List[Dict[str, Any]]:
        """
        Seçilen kategoriye ait yedekleri detay bilgileriyle döner:
        - Tarih / Saat (doğrudan dosya adından okunur)
        - Dosya Adı
        - Dosya Boyutu (KB / MB)
        - Kayıt Adedi (JSON içindeki öğe sayısı)
        - Dosya Yolu
        """
        dest_dir = self.get_backup_dir(category)
        files = self._get_sorted_backup_files(dest_dir)
        results = []

        is_expense = "exp" in category.lower() or "gider" in category.lower()

        for f_path in files:
            fname = os.path.basename(f_path)
            dt_str = self._parse_datetime_from_filename(fname, f_path)

            # Dosya boyutu
            try:
                size_bytes = os.path.getsize(f_path)
                if size_bytes >= 1024 * 1024:
                    size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
                else:
                    size_str = f"{size_bytes / 1024:.1f} KB"
            except Exception:
                size_bytes = 0
                size_str = "0 KB"

            # JSON içi kayıt adedi
            item_count = 0
            try:
                with open(f_path, "r", encoding="utf-8") as jf:
                    data = json.load(jf)
                    if is_expense:
                        if isinstance(data, dict):
                            item_count = len(data.get("expenses", []))
                    else:
                        if isinstance(data, list):
                            item_count = len(data)
                        elif isinstance(data, dict):
                            item_count = len(data.get("invoices", []))
            except Exception:
                item_count = 0

            results.append({
                "path": f_path,
                "filename": fname,
                "datetime": dt_str,
                "size_bytes": size_bytes,
                "size_str": size_str,
                "item_count": item_count,
            })

        return results

    def restore_snapshot(self, category: str, snapshot_path: str, target_active_path: str) -> bool:
        """
        Seçili sürümü geri yükler:
        1. Önce aktif dosyanın son durumunun bir yedeğini alır.
        2. Snapshot dosyasını aktif dosyanın üzerine güvenli bir şekilde yazar.
        """
        if not os.path.exists(snapshot_path):
            logger.error(f"[Restore Hatası] Yedek dosyası bulunamadı: {snapshot_path}")
            return False

        # 1. Aktif dosyanın son halini yedekle
        if os.path.exists(target_active_path):
            self.create_snapshot(category, target_active_path)

        # 2. Seçili sürümü aktif dosyanın üzerine yaz
        target_dir = os.path.dirname(target_active_path)
        os.makedirs(target_dir, exist_ok=True)
        temp_target = target_active_path + ".restore.tmp"
        try:
            shutil.copyfile(snapshot_path, temp_target)
            shutil.move(temp_target, target_active_path)
            logger.info(f"[Restore Başarılı] {os.path.basename(snapshot_path)} -> {target_active_path}")
            return True
        except Exception as e:
            logger.error(f"[Restore Hatası] Dosya üzerine yazılamadı: {e}")
            if os.path.exists(temp_target):
                try:
                    os.remove(temp_target)
                except Exception:
                    pass
            return False


# Global singleton instance
backup_manager = BackupManager()
