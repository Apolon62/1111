FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxkbcommon0 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Копирование и установка Python зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Установка Playwright
RUN playwright install chromium
RUN playwright install-deps

# Копирование всего проекта
COPY . .

# Создание необходимых директорий
RUN mkdir -p logs sessions

# Запуск бота
CMD ["python", "-m", "bot.main"]
