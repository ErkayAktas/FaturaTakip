import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import requests
from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
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
from src.version import APP_VERSION

logger = logging.getLogger(__name__)

CURRENT_VERSION = APP_VERSION if str(APP_VERSION).startswith("v") else f"v{APP_VERSION}"


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


def parse_version_tuple(v_str: str) -> tuple:
    """
    Sürüm metnini tam sayı tuple'ına çevirir.
    Örnek:
      "v1.0.9" -> (1, 0, 9)
      "v1.0.10" -> (1, 0, 10)
      "1.0.9" -> (1, 0, 5)
      "v1.0.0-build.12" -> (1, 0, 0, 12)
    """
    if not v_str:
        return (0, 0, 0)
    cleaned = str(v_str).strip().lstrip("vV").strip()
    for delim in ["-", "_", "+", "build", "b"]:
        cleaned = cleaned.replace(delim, ".")
    parts = []
    for item in cleaned.split("."):
        digits = "".join([c for c in item if c.isdigit()])
        if digits:
            parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer_version(current: str, latest: str) -> bool:
    """
    Doğru sürüm karşılaştırması (Tam sayı tuple ile):
    Örn: (1, 0, 10) > (1, 0, 9) -> True
    """
    c_tuple = parse_version_tuple(current)
    l_tuple = parse_version_tuple(latest)
    return l_tuple > c_tuple


def cleanup_old_files(app_dir: Optional[str] = None) -> List[str]:
    """
    Uygulama ilk açılışında dizinde kalan eski .old uzantılı dosyaları bulup temizler.
    PyInstaller --onefile yapısında önceki güncellemeden kalan .old dosyalarını temizler.
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


def generate_update_bat_script(target_exe_name: str, new_exe_name: str = "guncel_fatura.exe") -> str:
    """Windows için harici dosya değişimi ve otomatik yeniden başlatma .bat betiği oluşturur."""
    return f"""@echo off
chcp 65001 > nul
cd /d "%~dp0"

:: 1. Calisan uygulamanin sonlanmasi ve dosya kilidinin kalkmasi icin 2 saniye bekle
ping 127.0.0.1 -n 3 > nul

:: 2. Calisan orijinal uygulamanin .exe dosyasini sil / .old yap
if exist "{target_exe_name}.old" del /f /q "{target_exe_name}.old" > nul 2>&1
if exist "{target_exe_name}" (
    ren "{target_exe_name}" "{target_exe_name}.old" > nul 2>&1
    if exist "{target_exe_name}" del /f /q "{target_exe_name}" > nul 2>&1
)

:: 3. {new_exe_name} dosyasinin adini orijinal uygulama adi yap
if exist "{new_exe_name}" (
    ren "{new_exe_name}" "{target_exe_name}" > nul 2>&1
)

:: 4. Yeni guncel uygulamayi baslat
start "" "{target_exe_name}"

:: 5. update.bat kendini temizlesin
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
        self.setFixedSize(420, 150)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self.setStyleSheet("""
            QDialog {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QLabel {
                color: #F8FAFC;
            }
            QProgressBar {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                height: 14px;
                text-align: center;
                color: #FFFFFF;
                font-size: 11px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                border-radius: 5px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        self.lbl_title = QLabel("Yeni sürüm indiriliyor, lütfen bekleyin...")
        self.lbl_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        layout.addWidget(self.lbl_title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("0.00 MB / 0.00 MB (%0)")
        self.status_lbl.setStyleSheet("font-size: 11px; color: #94A3B8;")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_lbl)

    def set_progress(self, pct: float, downloaded_bytes: int = 0, total_bytes: int = 0):
        val = int(pct * 100)
        self.progress_bar.setValue(min(100, max(0, val)))
        dl_mb = downloaded_bytes / (1024 * 1024)
        if total_bytes > 0:
            tot_mb = total_bytes / (1024 * 1024)
            self.status_lbl.setText(f"{dl_mb:.2f} MB / {tot_mb:.2f} MB (%{val})")
        else:
            self.status_lbl.setText(f"{dl_mb:.2f} MB indirildi...")


class UpdateCheckWorker(QThread):
    """
    Arka planda GitHub API üzerinden güncelleme kontrolü yapan QThread iş parçacığı.
    Arayüzün kilitlenmesini kesin olarak engeller.
    """
    update_available = pyqtSignal(dict)
    up_to_date = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    check_finished = pyqtSignal()

    def __init__(self, github_url: str, current_version: str):
        super().__init__()
        self.github_url = github_url
        self.current_version = current_version

    def run(self):
        try:
            self.status_changed.emit("GitHub sunucusuna bağlanılıyor...")
            headers = {
                "User-Agent": "FaturaTakip-Updater",
                "Accept": "application/vnd.github.v3+json",
            }
            token = get_github_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"

            try:
                # 5 saniye bağlantı, 8 saniye okuma zaman aşımı
                res = requests.get(self.github_url, headers=headers, timeout=(5, 8))
            except requests.exceptions.Timeout:
                self.error_occurred.emit("GitHub sunucusuna bağlanırken zaman aşımı oluştu (5 sn bağlantı / 8 sn okuma).")
                return
            except requests.exceptions.ConnectionError as ce:
                self.error_occurred.emit(f"İnternet veya GitHub sunucu bağlantısı kurulamadı:\n{ce}")
                return

            if res.status_code == 404:
                self.error_occurred.emit("GitHub deposunda henüz yayınlanmış bir Release sürümü bulunamadı (HTTP 404).")
                return
            elif res.status_code == 403:
                msg = "GitHub API istek limiti aşıldı (HTTP 403)."
                rate_reset = res.headers.get("X-RateLimit-Reset", "")
                if rate_reset:
                    try:
                        reset_time = time.strftime('%H:%M:%S', time.localtime(int(rate_reset)))
                        msg += f" Limit sıfırlanma saati: {reset_time}"
                    except Exception:
                        pass
                self.error_occurred.emit(msg)
                return
            elif res.status_code != 200:
                self.error_occurred.emit(f"GitHub API beklenmeyen bir yanıt döndürdü (HTTP {res.status_code}):\n{res.text[:200]}")
                return

            try:
                data = res.json()
            except Exception as json_err:
                self.error_occurred.emit(f"GitHub API yanıtı JSON formatında ayrıştırılamadı:\n{json_err}")
                return

            if not isinstance(data, dict):
                self.error_occurred.emit("GitHub API beklenen nesne formatında veri döndürmedi.")
                return

            latest_version = data.get("tag_name", "").strip()
            if not latest_version:
                self.error_occurred.emit("GitHub Release verisinde 'tag_name' alanı bulunamadı.")
                return

            logger.info(f"Mevcut sürüm: {self.current_version}, GitHub'daki en son sürüm: {latest_version}")

            if is_newer_version(self.current_version, latest_version):
                self.update_available.emit(data)
            else:
                self.up_to_date.emit(self.current_version, latest_version)

        except Exception as e:
            logger.error(f"Beklenmeyen güncelleme kontrolü hatası: {e}")
            self.error_occurred.emit(str(e))
        finally:
            self.check_finished.emit()


class AutoUpdater:
    """
    GitHub Releases tabanlı otomatik güncelleme sınıfı.
    - QThread ile arayüzü dondurmayan API sorgusu (timeout=(5, 8))
    - Doğru sürüm karşılaştırması (Tam sayı tuple ile)
    - Asset (.exe) tespiti ve arka plan indirmesi
    - Gerçek zamanlı QProgressBar
    - Hot-swap (.bat) ile uygulama değişimi ve yeniden başlatma
    """

    def __init__(self, parent_window=None):
        self.parent = parent_window
        self.github_url = "https://api.github.com/repos/ErkayAktas/FaturaTakip/releases/latest"
        self.progress_win = None
        self.checking_dialog = None
        self.is_update_available = False
        self.latest_release_data = None
        self._is_checking = False
        self._worker: Optional[UpdateCheckWorker] = None
        self._active_trigger_button: Optional[QPushButton] = None
        self._original_button_text: str = ""

    @property
    def parent_widget(self) -> Optional[QWidget]:
        return self.parent if isinstance(self.parent, QWidget) else None

    @classmethod
    def cleanup_old_files(cls, app_dir: Optional[str] = None) -> List[str]:
        return cleanup_old_files(app_dir)

    def is_newer_version(self, current: str, latest: str) -> bool:
        return is_newer_version(current, latest)

    def check_for_updates(self, silent_if_latest: bool = False, trigger_button: Optional[QPushButton] = None):
        """GitHub API üzerinden en son yayınlanan Release sürümünü QThread ile kontrol eder."""
        if self._is_checking:
            logger.info("Güncelleme kontrolü zaten arka planda devam ediyor.")
            return

        self._is_checking = True
        self._active_trigger_button = trigger_button

        if self._active_trigger_button:
            try:
                self._original_button_text = self._active_trigger_button.text()
                self._active_trigger_button.setEnabled(False)
                self._active_trigger_button.setText("⏳ Kontrol Ediliyor...")
            except Exception:
                pass

        if not silent_if_latest:
            self.checking_dialog = UpdateCheckingDialog(self.parent_widget)
            self.checking_dialog.show()

        self._worker = UpdateCheckWorker(self.github_url, CURRENT_VERSION)

        def on_status_changed(msg: str):
            if self.checking_dialog and hasattr(self.checking_dialog, "lbl_sub"):
                try:
                    self.checking_dialog.lbl_sub.setText(msg)
                except Exception:
                    pass

        def on_update_available(data: dict):
            self.is_update_available = True
            self.latest_release_data = data
            self._close_checking_dialog()
            self.prompt_update(data)

        def on_up_to_date(current_ver: str, latest_ver: str):
            self.is_update_available = False
            self.latest_release_data = None
            self._close_checking_dialog()
            if not silent_if_latest:
                self._show_info(
                    "Güncelleme",
                    f"✓ Uygulamanız güncel ({current_ver}).\nEn son yayınlanan sürümdesiniz.",
                )

        def on_error(err_msg: str):
            self._close_checking_dialog()
            if not silent_if_latest:
                self._show_error(
                    "Güncelleme Hatası",
                    f"Güncelleme kontrolü yapılamadı:\n\n{err_msg}",
                )

        def on_finished():
            self._is_checking = False
            if self._active_trigger_button:
                try:
                    self._active_trigger_button.setEnabled(True)
                    if self._original_button_text:
                        self._active_trigger_button.setText(self._original_button_text)
                except Exception:
                    pass
                self._active_trigger_button = None
            self._close_checking_dialog()

        self._worker.status_changed.connect(on_status_changed)
        self._worker.update_available.connect(on_update_available)
        self._worker.up_to_date.connect(on_up_to_date)
        self._worker.error_occurred.connect(on_error)
        self._worker.check_finished.connect(on_finished)

        self._worker.start()

    def _close_checking_dialog(self):
        if self.checking_dialog:
            try:
                self.checking_dialog.close()
            except Exception:
                pass
            self.checking_dialog = None

    def _show_info(self, title: str, text: str):
        self._close_checking_dialog()
        QMessageBox.information(self.parent_widget, title, text)

    def _show_error(self, title: str, text: str):
        self._close_checking_dialog()
        QMessageBox.warning(self.parent_widget, title, text)

    def prompt_update(self, release_data: dict):
        """Yeni sürüm bulunduğunda kullanıcıya onay soran mesaj kutusu."""
        latest_version = release_data.get("tag_name", "v1.0.0")
        body = release_data.get("body", "").strip()

        question_text = "Yeni bir sürüm bulundu, şimdi güncellensin mi?"
        details = [f"Yeni Sürüm: {latest_version} (Mevcut: {CURRENT_VERSION})"]
        if body:
            details.append(f"Yenilikler:\n{body}")

        msg = question_text + "\n\n" + "\n\n".join(details)
        reply = QMessageBox.question(
            self.parent_widget,
            "Yeni Güncelleme Mevcut",
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
            name = str(asset.get("name", "")).lower()
            if name.endswith(".exe"):
                exe_asset = asset
                break

        if not exe_asset:
            QMessageBox.critical(
                self.parent_widget,
                "Güncelleme Hatası",
                f"Sürümde indirilebilir uygulama dosyası (.exe) bulunamadı.\nRelease içindeki asset sayısı: {len(assets)}",
            )
            return

        download_url = exe_asset.get("browser_download_url")
        if not download_url:
            QMessageBox.critical(
                self.parent_widget,
                "Güncelleme Hatası",
                "Asset için geçerli bir 'browser_download_url' bağlantısı bulunamadı.",
            )
            return

        # Çalışma dizinini ve hedef .exe adını sys.executable ile belirle
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

        new_exe_name = "guncel_fatura.exe"
        new_exe_path = os.path.join(current_dir, new_exe_name)

        # Progress bar diyalogu
        self.progress_win = UpdateProgressBarDialog(self.parent_widget)
        self.progress_win.show()

        def do_download():
            try:
                # S3 yönlendirmesi için Bearer eklenmeden standart User-Agent kullanılır
                download_headers = {
                    "User-Agent": "FaturaTakip-Updater",
                    "Accept": "*/*",
                }
                try:
                    res = requests.get(
                        download_url,
                        headers=download_headers,
                        stream=True,
                        allow_redirects=True,
                        timeout=60,
                    )
                except requests.exceptions.Timeout:
                    raise RuntimeError("Dosya indirme zaman aşımına uğradı (60 saniye).")
                except requests.exceptions.ConnectionError as ce:
                    raise RuntimeError(f"Dosya indirme sunucusuna bağlanılamadı:\n{ce}")

                if res.status_code != 200:
                    raise RuntimeError(
                        f"Dosya indirme başarısız oldu (HTTP {res.status_code}).\n"
                        f"İndirme Adresi: {download_url[:120]}"
                    )

                total_size = int(res.headers.get("content-length", 0))

                # Varsa önceki yarım kalmış geçici dosyayı temizle
                if os.path.exists(new_exe_path):
                    try:
                        os.remove(new_exe_path)
                    except Exception:
                        pass

                bytes_downloaded = 0
                chunk_size = 1024 * 64

                with open(new_exe_path, "wb") as f:
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

                # Dosya bütünlük doğrulaması
                if not os.path.exists(new_exe_path) or os.path.getsize(new_exe_path) == 0:
                    raise RuntimeError("İndirilen güncelleme dosyası boş veya doğrulanamadı (0 bayt).")

                logger.info(f"İndirme başarıyla tamamlandı: {bytes_downloaded} bayt -> {new_exe_path}")

                if self.progress_win:
                    QTimer.singleShot(0, self.progress_win.close)

                # Hot-swap ile güncellemeyi uygula ve yeniden başlat
                QTimer.singleShot(
                    200,
                    lambda: self.apply_update_and_restart(current_dir, target_exe_name, new_exe_name),
                )

            except Exception as e:
                err_msg = str(e)
                logger.error(f"İndirme hatası: {err_msg}")
                if os.path.exists(new_exe_path):
                    try:
                        os.remove(new_exe_path)
                    except Exception:
                        pass
                if self.progress_win:
                    QTimer.singleShot(0, self.progress_win.close)
                QTimer.singleShot(
                    0,
                    lambda err=err_msg: QMessageBox.critical(
                        self.parent_widget,
                        "Güncelleme Hatası",
                        f"Güncelleme dosyası indirilirken hata oluştu:\n{err}",
                    ),
                )

        threading.Thread(target=do_download, daemon=True).start()

    def apply_update_and_restart(self, current_dir: str, target_exe_name: str, new_exe_name: str = "guncel_fatura.exe"):
        """
        update.bat dosyası ile hot-swap güncelleme uygular, uygulamayı yeniden başlatır ve mevcut süreci kapatır.
        """
        try:
            new_exe_path = os.path.join(current_dir, new_exe_name)
            if not os.path.exists(new_exe_path) or os.path.getsize(new_exe_path) == 0:
                raise RuntimeError("Yeni sürüm dosyası (guncel_fatura.exe) bulunamadı.")

            bat_script = generate_update_bat_script(target_exe_name, new_exe_name)
            bat_path = os.path.join(current_dir, "update.bat")

            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_script)

            logger.info(f"update.bat başarıyla oluşturuldu: {bat_path}")

            if sys.platform.startswith("win"):
                subprocess.Popen(["cmd.exe", "/c", "update.bat"], cwd=current_dir, shell=True)
            else:
                logger.info("macOS/Linux ortamında update.bat simüle edildi.")

            QMessageBox.information(
                self.parent_widget,
                "Güncelleme Hazır",
                "Güncelleme başarıyla indirildi. Uygulama güncellenip yeniden başlatılacak.",
            )

            QApplication.quit()
            sys.exit(0)

        except Exception as e:
            logger.error(f"Güncelleme uygulama hatası: {e}")
            QMessageBox.critical(
                self.parent_widget,
                "Güncelleme Hatası",
                f"Güncelleme uygulanırken hata oluştu:\n{e}",
            )
