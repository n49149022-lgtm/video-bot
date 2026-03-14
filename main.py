import os
import requests
import re
import time
import torch
import subprocess
import tempfile
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ================= НАСТРОЙКИ =================
# Токен берется из переменных окружения Bothost (автоматически)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Ключи API
GIGA_AUTH = os.getenv("GIGA_AUTH", "MDE5Y2VjM2YtMmNjOS03MzA4LWFiMjMtMjllMWU4NGU2MGU0Ojc5YWUzZTlmLTQ2MjMtNGRjYi1iMThkLWNhNWI4YThjY2FjMw==")
PEXELS_KEY = os.getenv("PEXELS_KEY", "L3Reu5JdqAheWW3iPF7n1rxyMjl9NHD9mumI0DP4VNR4V10778ZWzEuL")
PIXABAY_KEY = os.getenv("PIXABAY_KEY", "54311008-07504ce70c6812bf263f5a22d")

# Папка для временных файлов
WORK_DIR = "temp_videos"
os.makedirs(WORK_DIR, exist_ok=True)

# Флаг занятости
IS_BUSY = False

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= ФУНКЦИИ ГЕНЕРАЦИИ (ТЕ ЖЕ САМЫЕ) =================

def get_script(topic):
    logger.info(f"🧠 Генерация сценария: {topic}")
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GIGA_AUTH}"}
    prompt = f"""
    Topic: {topic}. Create a 30s Shorts script in Russian.
    Format strictly:
    ---SCRIPT_START---
    SCENE 1:
    [TEXT]: (Russian text for voiceover)
    [VISUAL]: (english query for stock video)
    ... (3-4 scenes)
    ---SCRIPT_END---
    """
    try:
        r = requests.post(url, headers=headers, json={"model": "GigaChat", "messages": [{"role": "user", "content": prompt}]}, verify=False, timeout=60)
        content = r.json()['choices'][0]['message']['content']
        match = re.search(r'---SCRIPT_START---(.*?)---SCRIPT_END---', content, re.DOTALL)
        return match.group(1) if match else None
    except Exception as e:
        logger.error(f"❌ Ошибка GigaChat: {e}")
        return None

def parse_scenes(text):
    scenes = []
    blocks = re.split(r'SCENE \d+:', text)
    for block in blocks:
        if not block.strip(): continue
        t = re.search(r'\[TEXT\]:\s*(.*?)(?=\[VISUAL\]|$)', block, re.DOTALL)
        v = re.search(r'\[VISUAL\]:\s*(.*?)$', block, re.DOTALL)
        if t and v:
            scenes.append({"text": t.group(1).strip(), "query": re.sub(r'[^\w\s]', '', v.group(1)).strip()})
    return scenes

def download_video(query, scene_folder):
    path = os.path.join(scene_folder, "v.mp4")
    # Pexels
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": PEXELS_KEY}, params={"query": query, "per_page": 1, "orientation": "portrait"}, timeout=10)
        if r.status_code == 200 and r.json().get('videos'):
            link = r.json()['videos'][0]['video_files'][0]['link']
            with open(path, 'wb') as f: f.write(requests.get(link, timeout=10).content)
            return path
    except: pass
    # Pixabay
    try:
        r = requests.get("https://pixabay.com/api/videos/", params={"key": PIXABAY_KEY, "q": query, "per_page": 1}, timeout=10)
        if r.status_code == 200 and r.json().get('hits'):
            link = r.json()['hits'][0]['videos'].get('small', {}).get('url')
            if link:
                with open(path, 'wb') as f: f.write(requests.get(link, timeout=10).content)
                return path
    except: pass
    return None

def generate_audio(scenes, scene_folder):
    logger.info("   🗣 Озвучка (Silero)...")
    try:
        model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models', model='silero_tts', language='ru', speaker='xenia', force_reload=False)
    except:
        model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models', model='silero_tts', language='ru', speaker='xenia')
    
    paths = []
    for i, s in enumerate(scenes):
        p = os.path.join(scene_folder, f"a{i}.wav")
        model.save_wav(text=s['text'], speaker='xenia', sample_rate=48000, audio_path=p)
        paths.append(p)
    return paths

def assemble_video(scenes, audio_paths, scene_folder, output_filename):
    v_list = os.path.join(scene_folder, "v_list.txt")
    a_list = os.path.join(scene_folder, "a_list.txt")
    
    # Если видео не найдено, создаем заглушку
    v_path = os.path.join(scene_folder, "v.mp4")
    if not os.path.exists(v_path):
        stub = os.path.join(scene_folder, "stub.mp4")
        subprocess.run(f"ffmpeg -y -f lavfi -i color=c=black:s=1080x1920:d=5 -c:v libx264 -t 5 {stub}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        v_path = stub

    with open(v_list, "w") as f:
        # Для простоты берем одно видео на весь ролик (или можно зациклить)
        f.write(f"file '{v_path}'\n") 
    
    with open(a_list, "w") as f:
        for ap in audio_paths: f.write(f"file '{ap}'\n")

    temp_v = os.path.join(scene_folder, "temp_v.mp4")
    temp_a = os.path.join(scene_folder, "temp_a.wav")
    
    subprocess.run(f"ffmpeg -y -f concat -safe 0 -i {v_list} -c copy {temp_v}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(f"ffmpeg -y -f concat -safe 0 -i {a_list} -c pcm_s16le {temp_a}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Музыка
    mus_url = "https://cdn.pixabay.com/download/audio/2022/03/10/audio_c8c8a73467.mp3?filename=lofi-study-112191.mp3"
    mus_path = os.path.join(scene_folder, "bg.mp3")
    if not os.path.exists(mus_path):
        with open(mus_path, 'wb') as f: f.write(requests.get(mus_url).content)

    final_path = os.path.join(scene_folder, output_filename)
    cmd = f'ffmpeg -y -i {temp_v} -i {temp_a} -i {mus_path} -filter_complex "[1:a]volume=1[v];[2:a]volume=0.1[m];[v][m]amix=inputs=2[a]" -map 0:v -map "[a]" -c:v copy -c:a aac -shortest "{final_path}"'
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    return final_path

# ================= ОБРАБОТЧИКИ КОМАНД TELEGRAM =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Прометей Видео-Фабрика** запущена!\n\n"
        "🎬 **Команды:**\n"
        "/make <тема> — Создать видео (например: /make Нейросети)\n"
        "/status — Проверить занятость бота\n\n"
        "⏳ Генерация занимает 2-4 минуты. Я пришлю готовый файл сюда."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BUSY
    if IS_BUSY:
        await update.message.reply_text("🔄 Бот сейчас занят генерацией другого видео. Подождите немного.")
    else:
        await update.message.reply_text("✅ Бот свободен и готов к работе!")

async def make_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_BUSY
    
    if IS_BUSY:
        await update.message.reply_text("🔄 Я сейчас занят! Подождите, пока закончу предыдущее видео.")
        return

    if not context.args:
        await update.message.reply_text("❌ Укажите тему! Пример: /make Искусственный интеллект")
        return

    topic = " ".join(context.args)
    IS_BUSY = True
    
    msg = await update.message.reply_text(f"🚀 **Запуск фабрики для темы:** {topic}\n\n⏳ Это займет пару минут...")
    
    try:
        # 1. Сценарий
        script = get_script(topic)
        if not script:
            await msg.edit_text("❌ Ошибка: Не удалось получить сценарий от GigaChat.")
            IS_BUSY = False
            return

        scenes = parse_scenes(script)
        if not scenes:
            await msg.edit_text("❌ Ошибка: Не удалось разобрать сценарий.")
            IS_BUSY = False
            return

        await msg.edit_text(f"📝 Сценарий готов ({len(scenes)} сцен). Скачиваю видео и озвучиваю...")

        # 2. Подготовка папки
        scene_folder = os.path.join(WORK_DIR, f"task_{update.message.message_id}")
        os.makedirs(scene_folder, exist_ok=True)

        # 3. Видео (берем первое ключевое слово для фона всего ролика для скорости)
        first_query = scenes[0]['query']
        v_path = download_video(first_query, scene_folder)
        if not v_path:
            logger.warning("Видео не найдено, будет черный фон.")

        # 4. Аудио
        audio_paths = generate_audio(scenes, scene_folder)

        # 5. Сборка
        await msg.edit_text("🎬 Монтирую финальное видео...")
        out_file = "result.mp4"
        final_path = assemble_video(scenes, audio_paths, scene_folder, out_file)

        # 6. Отправка файла
        await msg.edit_text("✅ Готово! Отправляю файл...")
        
        with open(final_path, 'rb') as video:
            await update.message.reply_video(video, caption=f"🎬 **Готово!**\nТема: {topic}\n\n🔥 Создано Прометеем.", quote=True)
        
        await msg.delete() # Удаляем служебное сообщение

    except Exception as e:
        logger.error(f"Ошибка генерации: {e}")
        await msg.edit_text(f"❌ Произошла ошибка: {str(e)}")
    
    finally:
        IS_BUSY = False
        # Очистка папки (опционально, чтобы не забивать диск)
        # import shutil
        # shutil.rmtree(scene_folder, ignore_errors=True)

# ================= ЗАПУСК БОТА =================

def main():
    if not TOKEN:
        logger.error("❌ TOKEN не найден! Проверьте переменные окружения.")
        return

    logger.info("🤖 Запуск бота...")
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("make", make_video))
    
    logger.info("✅ Бот запущен и ожидает команды...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
