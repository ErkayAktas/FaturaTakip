import atexit
import json
import logging
import os
import shutil
import socket
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

import dropbox
from dropbox.exceptions import ApiError, AuthError
from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

DROPBOX_APP_KEY = "5ymg7fu8z3zha1n"
DROPBOX_APP_SECRET = "lly1tk6ue4238cc"
DROPBOX_REFRESH_TOKEN = "0tfxdj_QbjQAAAAAAAAAAesK-vT29IUt25alSxa5SYqNb7t2GXnMARJdeIfdaQhi"
DEFAULT_DROPBOX_KEY = DROPBOX_APP_KEY

REMOTE_INFOS_PATH = "/FaturaTakip/infos.json"
REMOTE_SESSIONS_PATH = "/FaturaTakip/sessions.json"
AUTO_SYNC_INTERVAL_SECONDS = 30
SESSION_TIMEOUT_SECONDS = 90  # 90 saniyeden uzun süre heartbeat vermeyen kapanmış/çökmüş oturumlar elenir


class DropboxSyncManager(QObject):
    """
    Dropbox Yedekleme, Çift Yönlü Senkronizasyon ve Aktif Oturum Yöneticisi:
    - Dropbox app_key, app_secret ve oauth2_refresh_token ile kalıcı ve otomatik yenilenen entegrasyon sağlar.
    - Başlangıç Mantığı: Dropbox'ta infos.json varsa bilgisayara indirir, yoksa bilgisayardakini Dropbox'a yükler.
    - Anlık Yükleme: Veritabanında bir değişiklik yapıldığında (save_all) anında Dropbox'a yükler.
    - Auto-Sync & Canlı Sayaç: 30 saniyede bir geriye doğru sayar (sync_countdown_tick sinyali) ve buluttan çeker.
    - Aktif Oturum Takibi: Dropbox üzerindeki sessions.json ile aynı anda açık olan cihaz/pencere sayısını canlı izler.
    """

    # Sinyaller: (status_text, color_code)
    sync_status_updated = pyqtSignal(str, str)
    # Buluttan yeni veri çekildiğinde arayüzü yenileme sinyali
    data_reloaded_from_cloud = pyqtSignal()
    # Canlı Geriye Sayım Sayacı: (kalan_saniye)
    sync_countdown_tick = pyqtSignal(int)
    # Aktif Oturum Sayısı Sinyali: (oturum_sayisi)
    active_sessions_updated = pyqtSignal(int)

    def __init__(
        self,
        local_json_path: str,
        app_key: str = DROPBOX_APP_KEY,
        app_secret: str = DROPBOX_APP_SECRET,
        refresh_token: str = DROPBOX_REFRESH_TOKEN,
        parent=None,
        api_key: Optional[str] = None
    ):
        super().__init__(parent)
        self.local_json_path = os.path.abspath(local_json_path)
        self.storage_dir = os.path.dirname(self.local_json_path)
        self.app_key = app_key
        self.app_secret = app_secret
        self.refresh_token = refresh_token
        self.api_key = api_key or app_key
        self.remote_path = REMOTE_INFOS_PATH
        self.remote_sessions_path = REMOTE_SESSIONS_PATH

        # Benzersiz Oturum Tanımlayıcısı
        self.session_id = f"{socket.gethostname()}_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        self.active_session_count = 1

        self.last_known_rev: Optional[str] = None
        self._lock = threading.Lock()
        self._is_running = False
        self._auto_sync_thread: Optional[threading.Thread] = None
        self._upload_in_progress = False
        self._countdown = AUTO_SYNC_INTERVAL_SECONDS

        # Uygulama sonlandığında oturumun otomatik silinmesi için atexit kaydı
        atexit.register(self._on_process_exit)

    def get_client(self) -> dropbox.Dropbox:
        """Dropbox istemcisi oluşturur (oauth2_refresh_token ile süresi bitmeyen bağlantı)."""
        return dropbox.Dropbox(
            app_key=self.app_key,
            app_secret=self.app_secret,
            oauth2_refresh_token=self.refresh_token
        )

    def start(self):
        """Senkronizasyon servisini ve canlı oturum takip döngüsünü başlatır."""
        if self._is_running:
            return
        self._is_running = True

        # 1. Başlangıç senkronizasyonunu ve oturum kaydını arka planda başlat
        threading.Thread(target=self._startup_sync_worker, daemon=True).start()

        # 2. 30 saniyelik geriye sayımlı Auto-Sync döngü thread'ini başlat
        self._auto_sync_thread = threading.Thread(target=self._auto_sync_loop, daemon=True)
        self._auto_sync_thread.start()

    def stop(self):
        """Senkronizasyon servisini güvenli durdurur ve oturumu Dropbox'tan düşürür."""
        if not self._is_running:
            return
        self._is_running = False
        self._unregister_session_sync()

    def _on_process_exit(self):
        if self._is_running:
            self._is_running = False
            self._unregister_session_sync()

    # --- 1. BAŞLANGIÇ SENKRONİZASYONU ---
    def _startup_sync_worker(self):
        """
        Başlangıç Mantığı:
        Uygulama ilk açıldığında Dropbox'ı kontrol eder.
        Eğer Dropbox'ta infos.json varsa bilgisayara indirip üzerine yazar.
        Yoksa, bilgisayardaki mevcut dosyayı Dropbox'a yükler.
        Ayrıca açılışta aktif oturum kaydı oluşturur.
        """
        self.sync_status_updated.emit("🔄 Dropbox: Başlangıç kontrolü...", "#F59E0B")
        try:
            dbx = self.get_client()

            # Dropbox'ta infos.json var mı kontrol et
            file_exists_on_cloud = False
            remote_metadata = None
            try:
                remote_metadata = dbx.files_get_metadata(self.remote_path)
                file_exists_on_cloud = True
            except ApiError as e:
                if e.error.is_path() and e.error.get_path().is_not_found():
                    file_exists_on_cloud = False
                else:
                    logger.warning(f"Dropbox metadata kontrol hatası: {e}")
            except AuthError as ae:
                logger.warning(f"Dropbox Yetkilendirme Uyarısı (Token): {ae}")
                self.sync_status_updated.emit("● Dropbox: Yetki Bekleniyor", "#F97316")
                self.active_sessions_updated.emit(1)
                return

            if file_exists_on_cloud and remote_metadata:
                # Dropbox'ta dosya var -> İndir ve yerel dosyanın üzerine yaz
                logger.info(f"[Dropbox] Buluttaki dosya bulundu (rev: {remote_metadata.rev}). İndiriliyor...")
                self.sync_status_updated.emit("🔄 Dropbox: Buluttan İndiriliyor...", "#38BDF8")

                temp_download = os.path.join(self.storage_dir, f"temp_dbx_{int(time.time())}.json")
                dbx.files_download_to_file(temp_download, self.remote_path)

                with self._lock:
                    shutil.move(temp_download, self.local_json_path)
                    self.last_known_rev = remote_metadata.rev

                self.sync_status_updated.emit("✓ Dropbox: Senkronize", "#10B981")
                self.data_reloaded_from_cloud.emit()
            else:
                # Dropbox'ta dosya yok -> Bilgisayardaki mevcut dosyayı Dropbox'a yükle
                logger.info("[Dropbox] Bulutta dosya bulunamadı. Yerel infos.json Dropbox'a yükleniyor...")
                self._upload_local_file_internal(dbx)

            # Oturum kaydı aç (Aktif Oturum Takibi)
            self._register_session(dbx)

        except AuthError as ae:
            logger.warning(f"Dropbox AuthError: {ae}")
            self.sync_status_updated.emit("● Dropbox: Yetki Bekleniyor", "#F97316")
            self.active_sessions_updated.emit(1)
        except Exception as e:
            logger.error(f"[Dropbox Başlangıç Hatası] {e}")
            self.sync_status_updated.emit("● Dropbox: Çevrimdışı", "#94A3B8")
            self.active_sessions_updated.emit(1)

    # --- 2. ANLIK YÜKLEME (INSTANT UPLOAD) ---
    def trigger_instant_upload(self):
        """Veritabanında bir değişiklik yapıldığında (save_all) anında Dropbox'a yükler ve sayacı sıfırlar."""
        if not self._is_running:
            return

        def do_upload():
            if self._upload_in_progress:
                return
            self._upload_in_progress = True
            try:
                dbx = self.get_client()
                self._upload_local_file_internal(dbx)
                # Her yüklemede canlı sayaç sıfırlanıp 30'a döner
                self._countdown = AUTO_SYNC_INTERVAL_SECONDS
                self.sync_countdown_tick.emit(self._countdown)
            except Exception as e:
                logger.warning(f"[Dropbox Anlık Yükleme Hatası] {e}")
            finally:
                self._upload_in_progress = False

        threading.Thread(target=do_upload, daemon=True).start()

    def _upload_local_file_internal(self, dbx: dropbox.Dropbox):
        """Yerel dosyayı Dropbox'a güvenle yükler ve rev kodunu günceller."""
        if not os.path.exists(self.local_json_path):
            return

        self.sync_status_updated.emit("🔄 Dropbox: Yükleniyor...", "#38BDF8")
        try:
            with open(self.local_json_path, "rb") as f:
                data_bytes = f.read()

            mode = dropbox.files.WriteMode.overwrite
            res = dbx.files_upload(data_bytes, self.remote_path, mode=mode)
            with self._lock:
                self.last_known_rev = res.rev

            logger.info(f"[Dropbox] Yerel dosya yüklendi (Yeni rev: {res.rev}).")
            self.sync_status_updated.emit("✓ Dropbox: Senkronize Edildi", "#10B981")
        except AuthError:
            self.sync_status_updated.emit("● Dropbox: Yetki Bekleniyor", "#F97316")
        except Exception as e:
            logger.warning(f"[Dropbox Yükleme Başarısız] {e}")
            self.sync_status_updated.emit("⚠️ Dropbox: Yükleme Hatası", "#EF4444")

    # --- 3. AUTO-SYNC & CANLI GERİYE SAYIM DÖNGÜSÜ ---
    def _auto_sync_loop(self):
        """
        30 saniyeden geriye sayarak (sync_countdown_tick) arayüzde canlı sayaç oluşturur.
        Sayaç 0 olduğunda Dropbox'tan güncel dosyayı çeker ve oturum heartbeat'ini günceller.
        """
        while self._is_running:
            self._countdown = AUTO_SYNC_INTERVAL_SECONDS

            while self._countdown > 0 and self._is_running:
                self.sync_countdown_tick.emit(self._countdown)
                time.sleep(1)
                self._countdown -= 1

            if not self._is_running:
                break

            self.sync_countdown_tick.emit(0)

            # 30 saniye doldu: Buluttan dosya kontrolü yap
            try:
                self._check_and_pull_from_cloud()
            except Exception as e:
                logger.warning(f"[Dropbox Auto-Sync Hatası] {e}")

            # Oturum heartbeat ve temizlik yap
            try:
                dbx = self.get_client()
                self._heartbeat_and_prune_sessions(dbx)
            except Exception as e:
                logger.warning(f"[Dropbox Session Heartbeat Hatası] {e}")

    def _check_and_pull_from_cloud(self):
        """Buluttaki rev kontrolünü yapar. Dosya güncellenmişse indirir ve arayüzü tetikler."""
        try:
            dbx = self.get_client()
            remote_metadata = dbx.files_get_metadata(self.remote_path)

            if self.last_known_rev is None or remote_metadata.rev != self.last_known_rev:
                logger.info(f"[Dropbox Auto-Sync] Bulutta güncel dosya tespit edildi. İndiriliyor...")
                self.sync_status_updated.emit("🔄 Dropbox: Güncelleme Çekiliyor...", "#38BDF8")

                temp_download = os.path.join(self.storage_dir, f"temp_dbx_autosync_{int(time.time())}.json")
                dbx.files_download_to_file(temp_download, self.remote_path)

                with self._lock:
                    shutil.move(temp_download, self.local_json_path)
                    self.last_known_rev = remote_metadata.rev

                self.sync_status_updated.emit("✓ Dropbox: Senkronize Edildi", "#10B981")
                self.data_reloaded_from_cloud.emit()
            else:
                self.sync_status_updated.emit("✓ Dropbox: Senkronize", "#10B981")

        except ApiError as ae:
            if ae.error.is_path() and ae.error.get_path().is_not_found():
                pass
        except AuthError:
            self.sync_status_updated.emit("● Dropbox: Yetki Bekleniyor", "#F97316")
        except Exception as e:
            logger.warning(f"[Dropbox Auto-Sync Check] {e}")

    # --- 4. AKTİF OTURUM TAKİBİ (SESSIONS.JSON) ---

    def _read_remote_sessions(self, dbx: dropbox.Dropbox) -> Dict[str, Any]:
        """Dropbox üzerindeki sessions.json dosyasını okur."""
        try:
            _, response = dbx.files_download(self.remote_sessions_path)
            content = response.content.decode("utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            return {}
        except ApiError as ae:
            if ae.error.is_path() and ae.error.get_path().is_not_found():
                return {}
            logger.warning(f"Dropbox sessions.json okuma uyarısı: {ae}")
            return {}
        except Exception as e:
            logger.warning(f"Dropbox sessions.json ayrıştırma hatası: {e}")
            return {}

    def _write_remote_sessions(self, dbx: dropbox.Dropbox, sessions: Dict[str, Any]) -> bool:
        """Dropbox üzerindeki sessions.json dosyasını günceller."""
        try:
            raw_bytes = json.dumps(sessions, ensure_ascii=False, indent=2).encode("utf-8")
            dbx.files_upload(raw_bytes, self.remote_sessions_path, mode=dropbox.files.WriteMode.overwrite)
            return True
        except Exception as e:
            logger.warning(f"Dropbox sessions.json yazma hatası: {e}")
            return False

    def _prune_stale_sessions(self, sessions: Dict[str, Any]) -> Dict[str, Any]:
        """90 saniyeden uzun süredir heartbeat vermeyen eski oturumları temizler."""
        now = time.time()
        active = {}
        for s_id, s_data in sessions.items():
            if not isinstance(s_data, dict):
                continue
            last_hb = float(s_data.get("last_heartbeat") or s_data.get("started_at") or 0.0)
            if (now - last_hb) < SESSION_TIMEOUT_SECONDS:
                active[s_id] = s_data
        return active

    def _register_session(self, dbx: dropbox.Dropbox):
        """Uygulama açılışında oturumu ekler ve aktif oturum sayısını artırır."""
        try:
            with self._lock:
                sessions = self._read_remote_sessions(dbx)
                sessions = self._prune_stale_sessions(sessions)
                now = time.time()
                sessions[self.session_id] = {
                    "hostname": socket.gethostname(),
                    "pid": os.getpid(),
                    "started_at": now,
                    "last_heartbeat": now,
                }
                self._write_remote_sessions(dbx, sessions)
                self.active_session_count = max(1, len(sessions))
                self.active_sessions_updated.emit(self.active_session_count)
        except Exception as e:
            logger.warning(f"Oturum kaydı başarısız: {e}")
            self.active_sessions_updated.emit(1)

    def _heartbeat_and_prune_sessions(self, dbx: dropbox.Dropbox):
        """Periyodik döngüde mevcut oturumun zaman damgasını yeniler ve güncel sayıyı bildirir."""
        try:
            with self._lock:
                sessions = self._read_remote_sessions(dbx)
                sessions = self._prune_stale_sessions(sessions)
                now = time.time()
                sessions[self.session_id] = {
                    "hostname": socket.gethostname(),
                    "pid": os.getpid(),
                    "started_at": sessions.get(self.session_id, {}).get("started_at", now),
                    "last_heartbeat": now,
                }
                self._write_remote_sessions(dbx, sessions)
                self.active_session_count = max(1, len(sessions))
                self.active_sessions_updated.emit(self.active_session_count)
        except Exception as e:
            logger.warning(f"Oturum heartbeat başarısız: {e}")

    def _unregister_session_sync(self):
        """Uygulama kapanışında oturumu siler ve aktif oturum sayısını düşürür."""
        try:
            dbx = self.get_client()
            with self._lock:
                sessions = self._read_remote_sessions(dbx)
                sessions.pop(self.session_id, None)
                sessions = self._prune_stale_sessions(sessions)
                self._write_remote_sessions(dbx, sessions)
                count = max(0, len(sessions))
                self.active_sessions_updated.emit(count)
        except Exception as e:
            logger.warning(f"Oturum silme hatası: {e}")
