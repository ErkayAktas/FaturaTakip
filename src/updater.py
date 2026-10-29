import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.database import get_app_base_dir

logger = logging.getLogger(__name__)

APP_VERSION = "v1.0.5"
CURRENT_VERSION = f"v{APP_VERSION}"


def get_github_token() -> str:
    """GitHub API erişim belirtecini (Token) yükler."""
    base_dir = get_app_base_dir()
    candidates = [
        os.path.join(base_dir, "FaturaTakipSifre"),
        os.path.join(base_dir, "..", "FaturaTakipSifre"),
        "/Users/erkayaktas/Desktop/Gravity/FaturaTakipSifre",
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    tok = f.read().strip()
                    if tok:
                        return tok
            except Exception:
                pass
    return ""


def is_newer_version(current: str, latest: str) -> bool:
    """Sürüm karşılaştırma fonksiyonu (SemVer uyumlu)."""
    c_str = current.lower().lstrip("v").strip()
    l_str = latest.lower().lstrip("v").strip()
    try:
        c_parts = [int(x) for x in c_str.split(".")]
        l_parts = [int(x) for x in l_str.split(".")]
        max_len = max(len(c_parts), len(l_parts))
        c_parts += [0] * (max_len - len(c_parts))
        l_parts += [0] * (max_len - len(l_parts))
        return l_parts > c_parts
    except Exception:
        return l_str > c_str


def cleanup_old_files(app_dir: Optional[str] = None) -> List[str]:
    """
    Uygulama ilk açılışında dizinde kalan eski .old uzantılı dosyaları bulup temizler.
    PyInstaller --onefile yapısında önceki güncellemeden kalan .old dosyalarını temizlemek için kullanılır.
    """
    if not app_dir:
        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            app_dir = os.path.dirname(os.path.abspath(sys.executable))
        else:
            app_dir = get_app_base_dir()

    cleaned_files = []
    if not os.path.exists(app_dir):
        return cleaned_files

    try:
        for entry in os.listdir(app_dir):
            if entry.lower().endswith(".old") or entry.lower().endswith(".old.exe"):
                file_path = os.path.join(app_dir, entry)
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        cleaned_files.append(file_path)
                        logger.info(f"Eski sürüm dosyası temizlendi: {file_path}")
                    except Exception as e:
                        logger.warning(f"Eski dosya temizlenemedi ({file_path}): {e}")
    except Exception as e:
        logger.error(f"Eski dosyalar taranırken hata: {e}")

    return cleaned_files


def generate_update_bat_script(target_exe_name: str, temp_exe_name: str) -> str:
    """Windows icin guvenli dosya degisimi ve yeniden baslatma .bat betigi olusturur."""
    return f"""@echo off
chcp 65001 > nul

:: 1. Eski uygulamanin sonlanmasi icin bekle
timeout /t 1 /nobreak > nul 2>&1 || ping 127.0.0.1 -n 2 > nul

:: 2. Calisma dizinine gec
cd /d "%~dp0"

:: 3. Eger Python seviyesinde dosya degisimi henuz yapilmamissa guvence olarak yap
if exist "{temp_exe_name}" (
    if exist "{target_exe_name}" (
        if exist "{target_exe_name}.old" del /f /q "{target_exe_name}.old" > nul 2>&1
        ren "{target_exe_name}" "{target_exe_name}.old" > nul 2>&1
    )
    ren "{temp_exe_name}" "{target_exe_name}" > nul 2>&1
)

:: 4. Yeni surumu baslat
start "" "{target_exe_name}"

:: 5. updater.bat betigini temizle
del "%~f0" > nul 2>&1
"""


class UpdateCheckingDialog(QDialog):
    """Güncelleme kontrolü sırasında kullanıcıya sürecin başladığını gösteren diyalog penceresi."""

    def __init__(self, parent_widget: Optional[QWidget] = None):
        actual_parent = parent_widget if isinstance(parent_widget, QWidget) else None
        super().__init__(actual_parent)
        self.setWindowTitle("Güncelleme Kontrolü")
        self.setFixedSize(380, 130)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QLabel {
                color: #F8FAFC;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            QProgressBar {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                height: 10px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #0284C7;
                border-radius: 5px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.lbl_title = QLabel("Güncellemeler kontrol ediliyor, lütfen bekleyin...")
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.lbl_sub = QLabel("GitHub sunucusuna bağlanılıyor...")
        self.lbl_sub.setStyleSheet("font-size: 11px; color: #94A3B8;")
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_sub)


class UpdateProgressBarDialog(QDialog):
    """İndirme sürecini görselleştiren Progress Bar penceresi."""

    def __init__(self, parent_widget: Optional[QWidget] = None):
        actual_parent = parent_widget if isinstance(parent_widget, QWidget) else None
        super().__init__(actual_parent)
        self.setWindowTitle("Güncelleme İndiriliyor")
        self.setFixedSize(400, 150)
        self.setModal(True)

        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            QLabel {
                color: #F8FAFC;
            }
            QProgressBar {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 8px;
                text-align: center;
                color: #FFFFFF;
                font-weight: bold;
                height: 24px;
            }
            QProgressBar::chunk {
                background-color: #0284C7;
                border-radius: 7px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self.lbl = QLabel("Yeni sürüm indiriliyor, lütfen bekleyin...")
        self.lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_lbl)

    def set_progress(self, pct: float, downloaded_bytes: int = 0, total_bytes: int = 0):
        val = int(pct * 100)
        self.progress_bar.setValue(val)
        if total_bytes > 0:
            dl_mb = downloaded_bytes / (1024 * 1024)
            tot_mb = total_bytes / (1024 * 1024)
            self.status_lbl.setText(f"{dl_mb:.2f} MB / {tot_mb:.2f} MB (%{val})")
        else:
            dl_mb = downloaded_bytes / (1024 * 1024)
            self.status_lbl.setText(f"{dl_mb:.2f} MB indirildi")


class AutoUpdater:
    """
    GitHub Releases tabanlı otomatik güncelleme sınıfı.
    PyInstaller --onefile yapısına uygun kendini güncelleme, .old yeniden adlandırma
    ve açılışta eski dosyaları temizleme desteğine sahiptir.
    """

    def __init__(self, parent_window):
        self.parent = parent_window
        self.github_url = "https://api.github.com/repos/ErkayAktas/FaturaTakip/releases/latest"
        token = get_github_token()
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.progress_win = None
        self.checking_dialog = None
        self.is_update_available = False
        self.latest_release_data = None
        self._is_checking = False

    @property
    def parent_widget(self) -> Optional[QWidget]:
        return self.parent if isinstance(self.parent, QWidget) else None

    @classmethod
    def cleanup_old_files(cls, app_dir: Optional[str] = None) -> List[str]:
        """Uygulama açılışında dizinde kalan eski .old uzantılı dosyaları bulup temizler."""
        return cleanup_old_files(app_dir)

    def is_newer_version(self, current: str, latest: str) -> bool:
        """Sürüm karşılaştırma fonksiyonu."""
        return is_newer_version(current, latest)

    def check_for_updates(self, silent_if_latest: bool = True):
        """
        GitHub üzerinden güncellemeleri denetler.
        silent_if_latest=True ise açılışta sessiz kontrol yapar, güncelleme yoksa uyarmaz.
        silent_if_latest=False ise kullanıcı butona tıklamıştır; "Güncellemeler kontrol ediliyor, lütfen bekleyin..."
        penceresi gösterilir ve sonuç her durumda (güncel, yeni sürüm, hata) kullanıcıya bildirilir.
        """
        if self._is_checking:
            return
        self._is_checking = True

        if not silent_if_latest:
            self.checking_dialog = UpdateCheckingDialog(self.parent_widget)
            self.checking_dialog.show()
            QApplication.processEvents()

        def _close_checking_dialog():
            self._is_checking = False
            if hasattr(self, "checking_dialog") and self.checking_dialog:
                try:
                    self.checking_dialog.close()
                    self.checking_dialog.deleteLater()
                except Exception:
                    pass
                self.checking_dialog = None

        def run_check():
            try:
                headers = self.headers.copy()
                try:
                    res = requests.get(self.github_url, headers=headers, timeout=10)
                    if res.status_code == 401 and "Authorization" in headers:
                        headers.pop("Authorization", None)
                        res = requests.get(self.github_url, headers=headers, timeout=10)
                except Exception as req_err:
                    raise req_err

                if res.status_code == 404:
                    logger.warning("No release found or repository is inaccessible.")
                    if not silent_if_latest:
                        QTimer.singleShot(
                            0,
                            lambda: (
                                _close_checking_dialog(),
                                QMessageBox.critical(
                                    self.parent_widget,
                                    "Hata",
                                    "Güncelleme sunucusunda yayın (Release) bulunamadı.\n(GitHub 404 Not Found)",
                                ),
                            ),
                        )
                    else:
                        _close_checking_dialog()
                    return

                res.raise_for_status()
                data = res.json()

                latest_version = data.get("tag_name", CURRENT_VERSION).strip()
                logger.info(f"Current version: {CURRENT_VERSION}, Latest release: {latest_version}")

                if self.is_newer_version(CURRENT_VERSION, latest_version):
                    self.is_update_available = True
                    self.latest_release_data = data
                    if hasattr(self.parent, "on_new_update_detected"):
                        QTimer.singleShot(0, lambda: self.parent.on_new_update_detected(data))
                    QTimer.singleShot(0, lambda: (_close_checking_dialog(), self.prompt_update(data)))
                else:
                    self.is_update_available = False
                    self.latest_release_data = None
                    if hasattr(self.parent, "on_app_up_to_date"):
                        QTimer.singleShot(0, self.parent.on_app_up_to_date)
                    if not silent_if_latest:
                        QTimer.singleShot(
                            0,
                            lambda: (
                                _close_checking_dialog(),
                                QMessageBox.information(
                                    self.parent_widget,
                                    "Güncelleme",
                                    f"Uygulamanız güncel.\nMevcut Sürüm: {CURRENT_VERSION}",
                                ),
                            ),
                        )
                    else:
                        _close_checking_dialog()
            except Exception as e:
                logger.error(f"Error checking for updates: {e}")
                if not silent_if_latest:
                    QTimer.singleShot(
                        0,
                        lambda err=str(e): (
                            _close_checking_dialog(),
                            QMessageBox.critical(
                                self.parent_widget,
                                "Güncelleme Hatası",
                                f"Güncelleme kontrolü sırasında hata oluştu:\n{err}",
                            ),
                        ),
                    )
                else:
                    _close_checking_dialog()

        threading.Thread(target=run_check, daemon=True).start()

    def prompt_update(self, release_data: dict):
        """Kullanıcıya yeni sürüm çıktığını soran onay penceresi (MessageBox)."""
        latest_version = release_data.get("tag_name", "v1.0.0")
        body = release_data.get("body", "").strip()

        question_text = "Yeni bir sürüm bulundu, şimdi güncellensin mi?"
        details = []
        if latest_version:
            details.append(f"Yeni Sürüm: {latest_version} (Mevcut: v{APP_VERSION})")
        if body:
            details.append(f"Yenilikler:\n{body}")

        msg = question_text
        if details:
            msg += "\n\n" + "\n\n".join(details)

        reply = QMessageBox.question(
            self.parent_widget,
            "Güncelleme",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.start_download(release_data)

    def start_download(self, release_data: dict):
        """Yeni sürüm .exe dosyasını arka planda indirir ve ilerleme çubuğunu günceller."""
        assets = release_data.get("assets", [])
        exe_asset = None
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith(".exe"):
                exe_asset = asset
                break

        if not exe_asset:
            for asset in assets:
                name = asset.get("name", "").lower()
                if "faturatakip" in name or "siparistakip" in name or "setup" in name:
                    exe_asset = asset
                    break

        if not exe_asset and assets:
            exe_asset = assets[0]

        if not exe_asset:
            QMessageBox.critical(
                self.parent_widget,
                "Güncelleme Hatası",
                "Güncelleme sırasında hata oluştu:\nSürümde indirilebilir uygulama dosyası (.exe) bulunamadı.",
            )
            return

        # GitHub token ile indirme yapabilmek için varsa asset API url'si
        download_url = exe_asset.get("url") or exe_asset.get("browser_download_url")
        asset_headers = self.headers.copy()
        if "/assets/" in str(download_url):
            asset_headers["Accept"] = "application/octet-stream"

        # Hedef dizini ve orijinal .exe adını belirle (PyInstaller --onefile uyumlu)
        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            current_exe_path = os.path.abspath(sys.executable)
            current_dir = os.path.dirname(current_exe_path)
            target_exe_name = os.path.basename(current_exe_path)
        else:
            current_dir = get_app_base_dir()
            target_exe_name = "FaturaTakip.exe"
            current_exe_path = os.path.join(current_dir, target_exe_name)

        if not target_exe_name.lower().endswith(".exe"):
            target_exe_name = f"{target_exe_name}.exe"

        # İndirme için geçici dosya yolu
        temp_exe_name = "yeni_surum_temp.exe"
        temp_exe_path = os.path.join(current_dir, temp_exe_name)

        # Progress Bar Penceresi
        self.progress_win = UpdateProgressBarDialog(self.parent_widget)
        self.progress_win.show()

        def do_download():
            try:
                res = requests.get(download_url, headers=asset_headers, stream=True, timeout=60)
                if res.status_code == 401 and "Authorization" in asset_headers:
                    asset_headers.pop("Authorization", None)
                    res = requests.get(download_url, headers=asset_headers, stream=True, timeout=60)
                res.raise_for_status()

                total_size = int(res.headers.get("content-length", 0))

                # Varsa eski yarım kalmış geçici dosyayı temizle
                if os.path.exists(temp_exe_path):
                    try:
                        os.remove(temp_exe_path)
                    except Exception as e:
                        logger.warning(f"Eski geçici dosya temizlenemedi: {e}")

                bytes_downloaded = 0
                chunk_size = 1024 * 64

                with open(temp_exe_path, "wb") as f:
                    for chunk in res.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            bytes_downloaded += len(chunk)
                            if total_size > 0:
                                pct = bytes_downloaded / total_size
                                QTimer.singleShot(
                                    0,
                                    lambda p=pct, d=bytes_downloaded, t=total_size: (
                                        self.progress_win.set_progress(p, d, t) if self.progress_win else None
                                    ),
                                )

                # İndirilen dosya doğrulaması
                if not os.path.exists(temp_exe_path) or os.path.getsize(temp_exe_path) == 0:
                    raise RuntimeError("İndirilen güncelleme dosyası doğrulanamadı veya boş.")

                if self.progress_win:
                    QTimer.singleShot(0, self.progress_win.close)

                # İndirme bittiğinde güvenli dosya değişimi ve yeniden başlatma
                QTimer.singleShot(
                    100, lambda: self.apply_update_and_restart(current_dir, target_exe_name, temp_exe_name)
                )

            except Exception as e:
                logger.error(f"Download failed: {e}")
                # İndirmeyi iptal et ve geçici dosyayı sil
                if os.path.exists(temp_exe_path):
                    try:
                        os.remove(temp_exe_path)
                    except Exception:
                        pass
                if self.progress_win:
                    QTimer.singleShot(0, self.progress_win.close)
                QTimer.singleShot(
                    0,
                    lambda err=str(e): QMessageBox.critical(
                        self.parent_widget,
                        "Güncelleme Hatası",
                        f"Güncelleme sırasında hata oluştu:\n{err}",
                    ),
                )

        threading.Thread(target=do_download, daemon=True).start()

    def apply_update_and_restart(self, current_dir: str, target_exe_name: str, temp_exe_name: str):
        """
        PyInstaller --onefile yapısına uygun olarak güvenli dosya değişimi ve yeniden başlatma:
        1. Çalışan mevcut .exe dosyasının adını değiştir (.old ekle).
        2. İndirilen yeni .exe dosyasını orijinal isimle kaydet.
        3. Dosya değişiminin başarılı olup olmadığını doğrula (Validation).
        4. Başarılıysa kullanıcıya bilgi verip yeniden başlat; hata varsa rollback yapıp pop-up göster.
        """
        current_exe_path = os.path.join(current_dir, target_exe_name) if not os.path.isabs(target_exe_name) else target_exe_name
        target_name_only = os.path.basename(current_exe_path)
        temp_exe_path = os.path.join(current_dir, temp_exe_name) if not os.path.isabs(temp_exe_name) else temp_exe_name
        old_exe_path = os.path.join(current_dir, f"{target_name_only}.old")

        rename_old_done = False
        try:
            # 1. İndirilen dosya doğrulaması
            if not os.path.exists(temp_exe_path) or os.path.getsize(temp_exe_path) == 0:
                raise RuntimeError("İndirilen yeni sürüm dosyası bulunamadı veya boş (0 bayt).")

            # 2. Varsa eski .old dosyasını temizle
            if os.path.exists(old_exe_path):
                try:
                    os.remove(old_exe_path)
                except Exception as e:
                    logger.warning(f"Eski .old dosyası silinemedi: {e}")
                    old_exe_path = os.path.join(current_dir, f"{target_name_only}.{int(time.time())}.old")
                    if os.path.exists(old_exe_path):
                        os.remove(old_exe_path)

            # 3. Çalışan mevcut .exe dosyasının adını değiştir (.old ekle)
            if os.path.exists(current_exe_path):
                os.rename(current_exe_path, old_exe_path)
                rename_old_done = True
                logger.info(f"Mevcut .exe başarıyla .old yapıldı: {old_exe_path}")

            # 4. İndirilen yeni dosyayı orijinal isimle kaydet
            os.rename(temp_exe_path, current_exe_path)
            logger.info(f"Yeni sürüm orijinal isimle kaydedildi: {current_exe_path}")

            # 5. DOĞRULAMA (VALIDATION):
            if not os.path.exists(current_exe_path) or os.path.getsize(current_exe_path) == 0:
                raise RuntimeError("Dosya değişimi doğrulanamadı: Yeni sürüm dosyası oluşturulamadı.")

            # Başarılı doğrulama!
            logger.info("Güncelleme doğrulandı ve başarıyla tamamlandı.")
            QMessageBox.information(
                self.parent_widget,
                "Güncelleme",
                "Güncelleme başarıyla tamamlandı, uygulama yeniden başlatılıyor.",
            )

            # 6. Uygulamayı yeniden başlat
            bat_content = generate_update_bat_script(target_name_only, os.path.basename(temp_exe_path))
            updater_bat_path = os.path.join(current_dir, "updater.bat")

            with open(updater_bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)

            if sys.platform.startswith("win"):
                subprocess.Popen(
                    ["cmd.exe", "/c", "updater.bat"],
                    cwd=current_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0,
                )
                if self.parent:
                    try:
                        self.parent.close()
                    except Exception:
                        pass
                os._exit(0)
            else:
                logger.info(f"macOS/Linux: Güncelleme tamamlandı. Yeni sürüm: {current_exe_path}")

        except Exception as e:
            logger.error(f"Dosya değişimi sırasında hata: {e}", exc_info=True)
            # Rollback: Eski dosya .old yapıldıysa ve hedef dosya yoksa eski dosyayı geri getir
            if rename_old_done and os.path.exists(old_exe_path) and not os.path.exists(current_exe_path):
                try:
                    os.rename(old_exe_path, current_exe_path)
                    logger.info("Geri alma (Rollback) başarılı: Eski .exe restore edildi.")
                except Exception as rb_err:
                    logger.error(f"Rollback hatası: {rb_err}")

            # İndirilen geçici dosyayı temizle (indirmeyi iptal et)
            if os.path.exists(temp_exe_path):
                try:
                    os.remove(temp_exe_path)
                except Exception:
                    pass

            # Hata durumunda kullanıcıya pop-up sağla
            QMessageBox.critical(
                self.parent_widget,
                "Güncelleme Hatası",
                f"Güncelleme sırasında hata oluştu:\n{str(e)}",
            )
