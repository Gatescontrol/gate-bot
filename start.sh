#!/bin/bash
echo "🚀 Запуск бота моніторингу воріт..."
echo "📦 Встановлення залежностей..."
pip install -r requirements.txt
echo "✅ Залежності встановлено!"
echo "🤖 Запуск бота..."
python app.py
