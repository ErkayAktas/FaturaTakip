@echo off
chcp 65001 > nul
echo ==================================================
echo    📦 Fatura Takip - Windows EXE Derleme Aracı
echo ==================================================

echo Gerekli paketler kontrol ediliyor...
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo.
echo PyInstaller ile tek dosya .exe derleniyor (icon.ico entegre ediliyor)...
pyinstaller --noconfirm --onefile --windowed --name="FaturaTakip" --icon=icon.ico --add-data="icon.ico;." --collect-all pymupdf main.py

echo.
if exist "dist\FaturaTakip.exe" (
    echo [BASARILI] FaturaTakip.exe basariyla dist klasorunde olusturuldu!
) else (
    echo [HATA] Derleme sirasinda bir sorun olustu.
)
pause

