import os
import re
import subprocess
import sys
from typing import Any, Dict, Optional, Tuple

import requests
from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.database import get_app_base_dir

# Mevcut Uygulama Sürümü
APP_VERSION = "1.0.0"
GITHUB_REPO = "ErkayAktas/FaturaTakip"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def normalize_version(tag: str) -> str:
    """Sürüm etiketini temizler (Örn: 'v1.0.1' -> '1.0.1')."""
    return tag.strip().lstrip("v").lstrip("V").strip()


def parse_version_tuple(v_str: str) -> Tuple[int, ...]:
    """Sürüm dizgesini karşılaştırılabilir integer demetine dönüştürür."""
    clean = normalize_version(v_str)
    # Sadece rakam gruplarını al (1.0.1 -> (1, 0, 1))
    nums = re.findall(r"\d+", clean)
    if not nums:
        return (0,)
    return tuple(map(int, nums))


def is_newer_version(latest_tag: str, current_version: str = APP_VERSION) -> bool:
    """GitHub'daki son sürümün mevcut sürümden yüksek olup olmadığını belirler."""
    try:
        from packaging import version
        return version.parse(normalize_version(latest_tag)) > version.parse(normalize_version(current_version))
    except Exception:
        return parse_version_tuple(latest_tag) > parse_version_tuple(current_version)


class UpdateCheckWorker(QThread):
    """
    Arka planda GitHub API üzerinden en son sürümü kontrol eden iş parçacığı.
    """
    update_available = pyqtSignal(dict)  # Yeni sürüm bilgileri sözlüğü
    no_update = pyqtSignal(str)          # Mevcut en son sürüm etiketi
    check_failed = pyqtSignal(str)       # Hata mesajı

    def __init__(self, manual: bool = False, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.manual = manual

    def run(self):
        try:
            headers = {
                "User-Agent": f"FaturaTakip-App/{APP_VERSION}",
                "Accept": "application/vnd.github.v3+json",
            }
            resp = requests.get(GITHUB_API_URL, headers=headers, timeout=10)

            if resp.status_code == 404:
                self.check_failed.emit("GitHub üzerinde henüz yayınlanmış bir sürüm (Release) bulunamadı.")
                return

            if resp.status_code == 403:
                self.check_failed.emit("GitHub API istek limiti aşıldı. Lütfen daha sonra tekrar deneyiniz.")
                return

            if resp.status_code != 200:
                self.check_failed.emit(f"GitHub API yanıt hatası (Kod: {resp.status_code})")
                return

            data = resp.json()
            tag_name = data.get("tag_name", "")
            if not tag_name:
                self.check_failed.emit("GitHub sürüm etiketi (tag_name) okunamadı.")
                return

            if is_newer_version(tag_name, APP_VERSION):
                # .exe asset'ini tespit et
                assets = data.get("assets", [])
                exe_asset = None
                for asset in assets:
                    name = asset.get("name", "").lower()
                    if name.endswith(".exe"):
                        exe_asset = asset
                        break

                release_info = {
                    "tag_name": tag_name,
                    "release_name": data.get("name") or tag_name,
                    "body": data.get("body") or "Sürüm notu girilmemiş.",
                    "html_url": data.get("html_url", ""),
                    "published_at": data.get("published_at", ""),
                    "download_url": exe_asset.get("browser_download_url") if exe_asset else None,
                    "asset_name": exe_asset.get("name") if exe_asset else "FaturaTakip.exe",
                    "asset_size": exe_asset.get("size") if exe_asset else 0,
                }
                self.update_available.emit(release_info)
            else:
                self.no_update.emit(tag_name)

        except requests.exceptions.Timeout:
            self.check_failed.emit("GitHub sunucusuna bağlanırken zaman aşımı oluştu.")
        except requests.exceptions.ConnectionError:
            self.check_failed.emit("İnternet bağlantısı kurulamadı veya GitHub'a erişilemiyor.")
        except Exception as e:
            self.check_failed.emit(f"Güncelleme kontrolü sırasında beklenmeyen bir hata oluştu: {str(e)}")


class DownloadWorker(QThread):
    """
    Arka planda yeni sürüm .exe dosyasını indiren iş parçacığı.
    """
    progress = pyqtSignal(int, int)  # (İndirilen Bayt, Toplam Bayt)
    finished = pyqtSignal(str)       # İndirilen dosyanın tam dosya yolu
    failed = pyqtSignal(str)         # Hata mesajı

    def __init__(self, download_url: str, target_path: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.download_url = download_url
        self.target_path = target_path
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            headers = {"User-Agent": f"FaturaTakip-Updater/{APP_VERSION}"}
            with requests.get(self.download_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                total_length = r.headers.get("content-length")

                if total_length is None:
                    total_bytes = 0
                else:
                    total_bytes = int(total_length)

                downloaded_bytes = 0
                os.makedirs(os.path.dirname(os.path.abspath(self.target_path)), exist_ok=True)

                with open(self.target_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if self._is_cancelled:
                            f.close()
                            if os.path.exists(self.target_path):
                                os.remove(self.target_path)
                            self.failed.emit("İndirme kullanıcı tarafından iptal edildi.")
                            return

                        if chunk:
                            f.write(chunk)
                            downloaded_bytes += len(chunk)
                            self.progress.emit(downloaded_bytes, total_bytes)

            self.finished.emit(self.target_path)
        except Exception as e:
            if os.path.exists(self.target_path):
                try:
                    os.remove(self.target_path)
                except Exception:
                    pass
            self.failed.emit(f"İndirme sırasında hata oluştu: {str(e)}")


class UpdatePromptDialog(QDialog):
    """Kullanıcıya yeni sürüm çıktığını bildiren modern pop-up ekranı."""

    def __init__(self, release_info: dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.release_info = release_info
        self.setWindowTitle("🚀 Yeni Güncelleme Mevcut")
        self.resize(520, 380)
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
            QTextEdit {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
            }
            QPushButton#updateBtn {
                background-color: #10B981;
                color: #FFFFFF;
                font-weight: bold;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton#updateBtn:hover {
                background-color: #059669;
            }
            QPushButton#secondaryBtn {
                background-color: #334155;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 8px;
                padding: 10px 16px;
                font-size: 13px;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #475569;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)

        # Başlık ve Rozet
        header_layout = QHBoxLayout()
        icon_lbl = QLabel("🚀")
        icon_lbl.setStyleSheet("font-size: 32px;")
        header_layout.addWidget(icon_lbl)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(4)
        title_lbl = QLabel("Yeni Bir Sürüm Yayınlandı!")
        title_lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #FFFFFF;")

        tag_name = self.release_info.get("tag_name", "")
        version_lbl = QLabel(f"Mevcut Sürüm: <b>v{APP_VERSION}</b>  ➔  Yeni Sürüm: <span style='color: #10B981; font-weight: bold;'>{tag_name}</span>")
        version_lbl.setStyleSheet("font-size: 13px; color: #94A3B8;")

        title_vbox.addWidget(title_lbl)
        title_vbox.addWidget(version_lbl)
        header_layout.addLayout(title_vbox)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Sürüm Notları Başlığı
        notes_hdr = QLabel("📋 Sürüm Notları:")
        notes_hdr.setStyleSheet("font-weight: 700; color: #CBD5E1; font-size: 13px;")
        layout.addWidget(notes_hdr)

        # Sürüm Notları İçeriği
        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.notes_text.setPlainText(self.release_info.get("body", "Detay belirtilmemiş."))
        layout.addWidget(self.notes_text)

        # Soru Metni
        has_exe = bool(self.release_info.get("download_url"))
        if has_exe:
            prompt_lbl = QLabel("Yeni sürüm dosyasını şimdi indirip uygulamayı otomatik güncellemek istiyor musunuz?")
        else:
            prompt_lbl = QLabel("⚠️ Yeni sürüm bulundu ancak henüz doğrudan indirilebilir bir .exe dosyası eklenmemiş.")
            prompt_lbl.setStyleSheet("color: #F59E0B; font-weight: 600;")
        prompt_lbl.setWordWrap(True)
        prompt_lbl.setStyleSheet("font-size: 13px; color: #E2E8F0;")
        layout.addWidget(prompt_lbl)

        # Butonlar
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.btn_cancel = QPushButton("Daha Sonra")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_update = QPushButton("⚡ Şimdi Güncelle")
        self.btn_update.setObjectName("updateBtn")
        self.btn_update.setEnabled(has_exe)
        self.btn_update.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_update)
        layout.addLayout(btn_layout)


class DownloadProgressDialog(QDialog):
    """İndirme sürecini görselleştiren Progress Bar diyaloğu."""

    def __init__(self, download_url: str, target_path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.download_url = download_url
        self.target_path = target_path
        self.download_completed = False
        self.downloaded_file = ""

        self.setWindowTitle("Fatura Takip Güncelleniyor")
        self.resize(440, 200)
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
            QPushButton#secondaryBtn {
                background-color: #334155;
                color: #F8FAFC;
                border: 1px solid #475569;
                border-radius: 8px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #475569;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(16)

        self.title_lbl = QLabel("⬇️ Yeni Sürüm İndiriliyor...")
        self.title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #FFFFFF;")
        layout.addWidget(self.title_lbl)

        self.status_lbl = QLabel("Sunucuya bağlanılıyor...")
        self.status_lbl.setStyleSheet("font-size: 12px; color: #94A3B8;")
        layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_cancel = QPushButton("İptal Et")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        # Worker başlat
        self.worker = DownloadWorker(self.download_url, self.target_path, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, downloaded: int, total: int):
        if total > 0:
            pct = int((downloaded / total) * 100)
            self.progress_bar.setValue(pct)
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            self.status_lbl.setText(f"İndiriliyor: {dl_mb:.2f} MB / {tot_mb:.2f} MB (%{pct})")
        else:
            dl_mb = downloaded / (1024 * 1024)
            self.status_lbl.setText(f"İndiriliyor: {dl_mb:.2f} MB")

    def _on_finished(self, file_path: str):
        self.download_completed = True
        self.downloaded_file = file_path
        self.progress_bar.setValue(100)
        self.status_lbl.setText("✓ İndirme tamamlandı! Güncelleme uygulanıyor...")
        self.accept()

    def _on_failed(self, err_msg: str):
        self.status_lbl.setText(f"Hata: {err_msg}")
        QMessageBox.warning(self, "İndirme Hatası", f"Güncelleme indirilemedi:\n{err_msg}")
        self.reject()

    def _on_cancel(self):
        if self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(1500)
        self.reject()

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(1500)
        super().closeEvent(event)


def generate_update_bat_script(current_exe: str, new_exe: str) -> str:
    """
    Windows üzerinde çalışan .exe dosyasının üzerine yazılmasını ve uygulamanın
    yeniden başlatılmasını sağlayan 'update.bat' komut dosyasının içeriğini üretir.
    """
    # Windows ve POSIX yolları için güvenli dosya adı ayrıştırma
    exe_name = current_exe.replace("/", "\\").split("\\")[-1]
    
    script = f"""@echo off
chcp 65001 > nul
title Fatura Takip Otomatik Guncelleme
echo ======================================================
echo Fatura Takip guncelleniyor, lutfen bekleyin...
echo ======================================================

:: Uygulamanin tamamen kapanmasi icin bekle
timeout /t 2 /nobreak > nul

:: Calisan eski prosesi gerekiyorsa sonlandir
taskkill /f /im "{exe_name}" > nul 2>&1
timeout /t 1 /nobreak > nul

:wait_close
del /f /q "{current_exe}" > nul 2>&1
if exist "{current_exe}" (
    timeout /t 1 /nobreak > nul
    goto wait_close
)

:: Yeni indirilen exe'nin adini orijinaliyle degistir (ren hedefi sadece dosya adi olmalidir)
ren "{new_exe}" "{exe_name}"

:: Guncellenmis uygulamayi baslat
start "" "{current_exe}"

:: Gecici bat dosyasini sil
del "%~f0"
"""
    return script


def apply_update_and_restart(new_exe_path: str):
    """
    Çalışan EXE'nin Üzerine Yazma (Hot-Swap / Batch Script):
    - Yeni indirilen dosyayı kullanarak update.bat oluşturur.
    - subprocess.Popen ile betiği başlatır ve sys.exit() ile uygulamayı kapatır.
    """
    if getattr(sys, "frozen", False):
        current_exe = os.path.abspath(sys.executable)
    else:
        # Geliştirici modu (Python .py olarak çalıştığında)
        current_exe = os.path.abspath(sys.argv[0])
        # Güvenlik önlemi: python.exe'yi silmemek için uyar ve çık
        if not current_exe.lower().endswith(".exe"):
            print(f"[Updater] Geliştirici modundasınız. İndirilen dosya: {new_exe_path}")
            QMessageBox.information(
                None,
                "Geliştirici Modu",
                f"Yeni sürüm indirildi:\n{new_exe_path}\n\nUygulama Python betiği (.py) olarak çalıştığından .bat güncellemesi devre dışı bırakıldı. Derlenmiş .exe üzerinde bu işlem tam otomatik çalışacaktır.",
            )
            return

    exe_dir = os.path.dirname(current_exe)
    bat_path = os.path.join(exe_dir, "update.bat")

    bat_content = generate_update_bat_script(current_exe, new_exe_path)
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    print(f"[Updater] update.bat oluşturuldu: {bat_path}")

    # Windows üzerinde subprocess.Popen ile çalıştırıp uygulamayı kapat
    if sys.platform.startswith("win"):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            ["cmd.exe", "/c", bat_path],
            creationflags=creation_flags,
            close_fds=True,
            shell=False,
        )
    else:
        # macOS / Linux için shell script fallback
        subprocess.Popen(["sh", "-c", f"sleep 2; mv '{new_exe_path}' '{current_exe}'; '{current_exe}' &"], close_fds=True)

    # Uygulamayı hemen kapat
    sys.exit(0)
