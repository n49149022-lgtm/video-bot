import os
import requests
import re
import time
import torch
import subprocess
import zipfile

# ================= КОНФИГУРАЦИЯ =================
# Ключи (берутся из переменных окружения Bothost, но тут запасные)
GIGA_AUTH = os.getenv("GIGA_AUTH", "MDE5Y2VjM2YtMmNjOS03MzA4LWFiMjMtMjllMWU4NGU2MGU0Ojc5YWUzZTlmLTQ2MjMtNGRjYi1iMThkLWNhNWI4YThjY2FjMw==")
PEXELS_KEY = os.getenv("PEXELS_KEY", "L3Reu5JdqAheWW3iPF7n1rxyMjl9NHD9mumI0DP4VNR4V10778ZWzEuL")
PIXABAY_KEY = os.getenv("PIXABAY_KEY", "54311008-07504ce70c6812bf263f5a22d")

# Папки
WORK_DIR = "output_batch"
VIDEO_DIR = os.path.join(WORK_DIR, "clips")
AUDIO_DIR = os.path.join(WORK_DIR, "audio")
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

# ================= СПИСОК ТЕМ (РЕДАКТИРУЙ ТУТ!) =================
TOPICS = [
    "Как нейросети меняют мир за 5 лет",
    "Топ 3 ошибки новичков в программировании",
    "Почему базы данных важнее кода",
    "Будущее искусственного интеллекта в России",
    "Секреты оптимизации SQL запросов"
]
# ================================================================

print(f"🚀 ЗАПУСК ФАБРИКИ ВИДЕО. Всего планов: {len(TOPICS)}")

# --- ФУНКЦИИ (те же самые, что и раньше) ---

def get_script(topic):
    print(f"🧠 Генерация сценария: {topic}...")
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
        print(f"❌ Ошибка GigaChat: {e}")
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

def download_video(query, idx, scene_folder):
    path = os.path.join(scene_folder, f"v.mp4")
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
    print("   🗣 Озвучка (Silero)...")
    try:
        model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models', model='silero_tts', language='ru', speaker='xenia', force_reload=True)
    except:
        model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models', model='silero_tts', language='ru', speaker='xenia')
    
    paths = []
    for i, s in enumerate(scenes):
        p = os.path.join(scene_folder, f"a{i}.wav")
        model.save_wav(text=s['text'], speaker='xenia', sample_rate=48000, audio_path=p)
        paths.append(p)
    return paths

def assemble_video(scenes, audio_paths, scene_folder, output_filename):
    # Создаем списки для ffmpeg
    v_list = os.path.join(scene_folder, "v_list.txt")
    a_list = os.path.join(scene_folder, "a_list.txt")
    
    with open(v_list, "w") as f:
        for i in range(len(scenes)):
            fp = os.path.join(scene_folder, "v.mp4") # Упрощаем: одно видео на сцену не всегда найдется, берем одно общее или заглушку
            # Для простоты массового генератора: если видео нет - черный экран
            if os.path.exists(fp): f.write(f"file '{fp}'\n")
            else:
                stub = os.path.join(scene_folder, "stub.mp4")
                subprocess.run(f"ffmpeg -y -f lavfi -i color=c=black:s=1080x1920:d=5 -c:v libx264 -t 5 {stub}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                f.write(f"file '{stub}'\n")
    
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

    final_path = os.path.join(WORK_DIR, output_filename)
    cmd = f'ffmpeg -y -i {temp_v} -i {temp_a} -i {mus_path} -filter_complex "[1:a]volume=1[v];[2:a]volume=0.1[m];[v][m]amix=inputs=2[a]" -map 0:v -map "[a]" -c:v copy -c:a aac -shortest "{final_path}"'
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Чистка временных файлов сцены
    for f in os.listdir(scene_folder):
        if f not in ["clips", "audio"]: # Не удаляем папки, только файлы внутри если надо, но тут мы удалим всю папку сцены потом
            pass 
    # Для экономии места можно удалить временные файлы сцены, но оставим для отладки пока
    
    print(f"   ✅ Сохранено: {output_filename}")

# ================= ГЛАВНЫЙ ЦИКЛ =================
def main():
    for i, topic in enumerate(TOPICS):
        print(f"\n>>> ВИДЕО {i+1}/{len(TOPICS)}: {topic}")
        
        # 1. Сценарий
        script = get_script(topic)
        if not script:
            print("   ❌ Не удалось получить сценарий, пропускаем.")
            continue
        
        scenes = parse_scenes(script)
        if not scenes:
            print("   ❌ Нет сцен, пропускаем.")
            continue
            
        # 2. Папка для текущей сцены
        scene_folder = os.path.join(WORK_DIR, f"scene_{i+1}")
        os.makedirs(scene_folder, exist_ok=True)
        
        # 3. Видео (пытаемся найти хоть что-то, иначе будет черное)
        # Для упрощения берем первый запрос и ищем видео, или можно искать для каждого кадра (долго)
        # Сделаем компромисс: ищем видео по первому ключевому слову для всего ролика
        first_query = scenes[0]['query']
        v_path = download_video(first_query, 0, scene_folder)
        if not v_path:
            print("   ⚠️ Видео не найдено, будет черный фон.")
        
        # 4. Аудио
        try:
            audio_paths = generate_audio(scenes, scene_folder)
        except Exception as e:
            print(f"   ❌ Ошибка озвучки: {e}")
            continue
            
        # 5. Сборка
        safe_name = "".join(c for c in topic if c.isalnum() or c in (' ', '_')).rstrip()[:30]
        out_file = f"video_{i+1}_{safe_name}.mp4"
        assemble_video(scenes, audio_paths, scene_folder, out_file)
        
        # Очистка папки сцены для экономии места (опционально)
        # import shutil
        # shutil.rmtree(scene_folder) 
        
        time.sleep(2) # Пауза между видео

    print("\n🎉 ВСЁ ГОТОВО! Проверь папку output_batch")
    
    # Архивация
    print("📦 Создаю ZIP архив...")
    zip_name = "all_videos.zip"
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(WORK_DIR):
            for file in files:
                if file.endswith(".mp4"):
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(full_path, WORK_DIR)
                    zipf.write(full_path, arcname)
    print(f"✅ Архив готов: {zip_name} (можно скачать)")

if __name__ == "__main__":
    main()
