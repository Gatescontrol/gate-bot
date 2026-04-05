# 🚪 Gate Monitor Bot

Telegram бот для моніторингу 50 воріт з аварійним сповіщенням.

## 🎯 Функціонал
- Моніторинг 50 воріт
- Сповіщення через 60 секунд відкриття
- Інтерактивні кнопки керування
- Статус всіх воріт

## 🚀 Деплой на Render.com
1. Завантажте файли на GitHub
2. Створіть Web Service на Render
3. Встановіть webhook:
   ```bash
   curl -F "url=https://YOUR-URL.onrender.com/webhook" https://api.telegram.org/botYOUR_TOKEN/setWebhook
