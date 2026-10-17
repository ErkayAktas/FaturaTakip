#!/usr/bin/env bash
# Fatura Takip Uygulamasını Başlatma Betiği
cd "$(dirname "$0")"

echo "=================================================="
echo "    📄 Fatura Takip Sistemi Başlatılıyor...       "
echo "=================================================="

# Python bağımlılıklarını kontrol et veya çalıştır
python3 main.py
