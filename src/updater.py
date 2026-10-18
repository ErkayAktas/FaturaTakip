import logging
import os
import subprocess
import sys
import threading
from typing import Any, Dict, Optional

import requests
from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
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

APP_VERSION = "1.0.0"
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


class UpdateProgressBarDialog(QDialog):
    """İndirme sürecini görselleştiren Progress Bar penceresi."""

    def __init__(self, parent_widget: Optional[QWidget] = None):
        super().__init__(parent_widget)
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
    Sipariş Takip (APK-STU) projesindeki güncelleme altyapısını referans alan,
    GitHub Releases tabanlı otomatik güncelleme sınıfı.
    """

    def __init__(self, parent_window):
        self.parent = parent_window
        self.github_url = "https://api.github.com/repos/ErkayAktas/FaturaTakip/releases/latest"
        token = get_github_token()
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        self.progress_win = None
        self.is_update_available = False
        self.latest_release_data = None

    def check_for_updates(self, silent_if_latest: bool = True):
        """
        GitHub üzerinden güncellemeleri denetler.
        silent_if_latest=True ise açılışta sessiz kontrol yapar, güncelleme yoksa uyarmaz.
        """
        def run_check():
            try:
                res = requests.get(self.github_url, headers=self.headers, timeout=10)
                if res.status_code == 404:
                    logger.warning("No release found or repository is inaccessible.")
                    if not silent_if_latest:
                        QTimer.singleShot(
                            0,
                            lambda: QMessageBox.critical(
                                self.parent,
                                "Hata",
                                "Güncelleme sunucusunda yayın (Release) bulunamadı.\n(GitHub 404 Not Found)",
                            ),
                        )
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
                    QTimer.singleShot(0, lambda: self.prompt_update(data))
                else:
                    self.is_update_available = False
                    self.latest_release_data = None
                    if hasattr(self.parent, "on_app_up_to_date"):
                        QTimer.singleShot(0, self.parent.on_app_up_to_date)
                    if not silent_if_latest:
                        QTimer.singleShot(
                            0,
                            lambda: QMessageBox.information(
                                self.parent,
                                "Güncelleme",
                                f"Uygulamanız güncel.\nMevcut Sürüm: {CURRENT_VERSION}",
                            ),
                        )
            except Exception as e:
                logger.error(f"Error checking for updates: {e}")
                if not silent_if_latest:
                    QTimer.singleShot(
                        0,
                        lambda: QMessageBox.critical(
                            self.parent,
                            "Hata",
                            f"Güncelleme kontrolü sırasında hata oluştu:\n{str(e)}",
                        ),
                    )

        threading.Thread(target=run_check, daemon=True).start()

    def is_newer_version(self, current: str, latest: str) -> bool:
        """Sipariş Takip (APK-STU) projesindeki sürüm karşılaştırma fonksiyonu."""
        c_str = current.lower().lstrip("v")
        l_str = latest.lower().lstrip("v")
        try:
            c_parts = [int(x) for x in c_str.split(".")]
            l_parts = [int(x) for x in l_str.split(".")]
            max_len = max(len(c_parts), len(l_parts))
            c_parts += [0] * (max_len - len(c_parts))
            l_parts += [0] * (max_len - len(l_parts))
            return l_parts > c_parts
        except Exception:
            return l_str > c_str

    def prompt_update(self, release_data: dict):
        """Kullanıcıya yeni sürüm çıktığını soran diyalog penceresi."""
        latest_version = release_data.get("tag_name", "v1.0.0")
        body = release_data.get("body", "Detay belirtilmemiş.")

        msg = f"Yeni bir güncelleme bulundu: {latest_version}\n\nYenilikler:\n{body}\n\nŞimdi indirmek istiyor musunuz?"
        reply = QMessageBox.question(
            self.parent,
            "Güncelleme Mevcut",
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
            if name.endswith(".exe") or "faturatakip" in name or "siparistakip" in name:
                exe_asset = asset
                break

        if not exe_asset and assets:
            exe_asset = assets[0]

        if not exe_asset:
            QMessageBox.critical(self.parent, "Hata", "Sürümde indirilebilir uygulama dosyası (.exe asset) bulunamadı.")
            return

        # GitHub token ile indirme yapabilmek için varsa asset API url'si
        download_url = exe_asset.get("url") or exe_asset.get("browser_download_url")
        asset_headers = self.headers.copy()
        if "/assets/" in str(download_url):
            asset_headers["Accept"] = "application/octet-stream"

        # Hedef dizini ve orijinal .exe adını belirle
        is_frozen = getattr(sys, "frozen", False)
        if is_frozen:
            current_exe_path = os.path.abspath(sys.executable)
            current_dir = os.path.dirname(current_exe_path)
            target_exe_name = os.path.basename(current_exe_path)
        else:
            current_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
            target_exe_name = "FaturaTakip.exe"
            current_exe_path = os.path.join(current_dir, target_exe_name)

        if not target_exe_name.lower().endswith(".exe"):
            target_exe_name = "FaturaTakip.exe"

        # Güvenli Değiştirme Mantığı - Geçici dosya adı "yeni_surum_temp.exe"
        temp_exe_name = "yeni_surum_temp.exe"
        temp_exe_path = os.path.join(current_dir, temp_exe_name)

        # Progress Bar Penceresi
        self.progress_win = UpdateProgressBarDialog(self.parent)
        self.progress_win.show()

        def do_download():
            try:
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

                if self.progress_win:
                    QTimer.singleShot(0, self.progress_win.close)
                QTimer.singleShot(
                    100, lambda: self.apply_update_and_restart(current_dir, target_exe_name, temp_exe_name)
                )

            except Exception as e:
                logger.error(f"Download failed: {e}")
                if self.progress_win:
                    QTimer.singleShot(0, self.progress_win.close)
                QTimer.singleShot(
                    0,
                    lambda: QMessageBox.critical(
                        self.parent,
                        "İndirme Hatası",
                        f"Güncelleme dosyası indirilemedi:\n{str(e)}",
                    ),
                )

        threading.Thread(target=do_download, daemon=True).start()

    def apply_update_and_restart(self, current_dir: str, target_exe_name: str, temp_exe_name: str):
        """
        Sipariş Takip (APK-STU) projesindeki updater.bat oluşturma ve
        Hot-Swap çalıştırma mantığını birebir uygular.
        """
        current_pid = os.getpid()

        # APK-STU projesindeki birebir .bat betiği
        bat_content = f"""@echo off
chcp 65001 > nul

:: 1. Gorev Sonlandirma (Taskkill): Ana uygulamanin islemini zorla kapat
taskkill /F /IM "{target_exe_name}" /T > nul 2>&1
set PID={current_pid}
if defined PID taskkill /F /PID %PID% /T > nul 2>&1

:: 2. Dizin Temizligi (Cleanup): %TEMP% dizinindeki eski _MEI* klasorlerini temizle
for /d %%x in ("%TEMP%\\_MEI*") do rd /s /q "%%x" > nul 2>&1

:: 3. Bekleme Suresi (Timeout): Dosya sisteminin serbest kalmasi icin 5 saniye bekle
timeout /t 5 /nobreak > nul 2>&1 || ping 127.0.0.1 -n 6 > nul

:: Eski orijinal .exe dosyasini sil (kilit kalkana kadar tekrar dene)
cd /d "%~dp0"
set DEL_COUNT=0
:delete_old
if exist "{target_exe_name}" (
    del /f /q "{target_exe_name}" > nul 2>&1
    if exist "{target_exe_name}" (
        timeout /t 1 /nobreak > nul 2>&1 || ping 127.0.0.1 -n 2 > nul
        set /a DEL_COUNT+=1
        if %DEL_COUNT% leq 5 goto delete_old
    )
)

:: "{temp_exe_name}" dosyasini, silinen orijinal dosyanin tam adiyla yeniden adlandir
set REN_COUNT=0
:rename_new
if exist "{temp_exe_name}" (
    ren "{temp_exe_name}" "{target_exe_name}" > nul 2>&1
    if exist "{temp_exe_name}" (
        timeout /t 1 /nobreak > nul 2>&1 || ping 127.0.0.1 -n 2 > nul
        set /a REN_COUNT+=1
        if %REN_COUNT% leq 5 goto rename_new
    )
)

:: 4. Sabit Calisma Dizini (Absolute Path): Betigin bulundugu konuma gec ve yeni .exe dosyasini baslat
cd /d "%~dp0"
start "" "{target_exe_name}"

:: updater.bat betigini temizle
del "%~f0" > nul 2>&1
"""

        try:
            updater_bat_path = os.path.join(current_dir, "updater.bat")
            with open(updater_bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)

            if sys.platform.startswith("win"):
                subprocess.Popen(
                    ["cmd.exe", "/c", "updater.bat"],
                    cwd=current_dir,
                    creationflags=subprocess.CREATE_NEW_CONSOLE if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0,
                )
                try:
                    self.parent.close()
                except Exception:
                    pass
                os._exit(0)
            else:
                temp_exe_full_path = os.path.join(current_dir, temp_exe_name)
                QMessageBox.information(
                    self.parent,
                    "İşlem Tamamlandı",
                    f"Windows dışı işletim sisteminde çalışıyorsunuz.\nGüncelleme dosyası indirildi:\n{temp_exe_full_path}\nOrijinal dosya adı: {target_exe_name}",
                )
        except Exception as e:
            logger.error(f"Failed to apply update script: {e}")
            QMessageBox.critical(
                self.parent,
                "Güncelleme Hatası",
                f"Güncelleme uygulanırken hata oluştu:\n{str(e)}",
            )
