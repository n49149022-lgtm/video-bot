import os
import requests
import re
import time
import torch
import subprocess

# ================= КОНФИГУРАЦИЯ (ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ) =================
# Ключи берем из переменных окружения Bothost (безопасно!)
GIGA_AUTH = os.getenv("GIGA_AUTH", "MDE5Y2VjM2YtMmNjOS03MzA4LWFiMjMtMjllMWU4NGU2MGU0Ojc5YWUzZTlmLTQ2MjMtNGRjYi1iMThkLWNhNWI4YThjY2FjMw==")
PEXELS_KEY = os.getenv("PEXELS_KEY", "L3Reu5JdqAheWW3iPF7n1rxyMjl9NHD9mumI0DP4VNR4V10778ZWzEuL")
PIXABAY_KEY = os.getenv("PIXABAY_KEY", "54311008-07504ce70c6812bf263f5a22d")

# Папки
WORK_DIR = "output"
VIDEO_DIR = os.path.join(WORK_DIR, "clips")
AUDIO_DIR = os.path.join(WORK_DIR, "audio")
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

print("🚀 Video Bot Started...")

# ================= 1. GIGACHAT =================
def get_script(topic):
    print(f"🧠 Generating script for: {topic}")
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GIGA_AUTH}"}
    
    prompt = f"""
    Topic: {topic}. Create a 30s Shorts script.
    Format strictly:
    ---SCRIPT_START---
    SCENE 1:
    [TEXT]: ...
    [VISUAL]: (english query for stock video)
    ...
    ---SCRIPT_END---
    ---POST_START---
    Title: ...
    Tags: ...
    ---POST_END---
    """
    
    try:
        r = requests.post(url, headers=headers, json={"model": "GigaChat", "messages": [{"role": "user", "content": prompt}]}, verify=False)
        content = r.json()['choices'][0]['message']['content']
        
        # Save Post Info
        post_match = re.search(r'---POST_START---(.*?)---SCRIPT_END---|---POST_START---(.*?)$', content, re.DOTALL)
        if post_match:
            with open(os.path.join(WORK_DIR, "post.txt"), "w", encoding="utf-8") as f:
                f.write(post_match.group(1) or post_match.group(2))
        
        return re.search(r'---SCRIPT_START---(.*?)---SCRIPT_END---', content, re.DOTALL).group(1)
    except Exception as e:
        print(f"❌ GigaChat Error: {e}")
        return None

# ================= 2. PARSER =================
def parse_scenes(text):
    scenes = []
    for block in re.split(r'SCENE \d+:', text):
        t = re.search(r'\[TEXT\]:\s*(.*?)(?=\[VISUAL\]|$)', block, re.DOTALL)
        v = re.search(r'\[VISUAL\]:\s*(.*?)$', block, re.DOTALL)
        if t and v:
            scenes.append({"text": t.group(1).strip(), "query": re.sub(r'[^\w\s]', '', v.group(1)).strip()})
    return scenes

# ================= 3. VIDEO DOWNLOADER =================
def download_video(query, idx):
    # Pexels
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": PEXELS_KEY}, params={"query": query, "per_page": 1, "orientation": "portrait"}, timeout=10)
        if r.status_code == 200 and r.json().get('videos'):
            link = r.json()['videos'][0]['video_files'][0]['link']
            path = os.path.join(VIDEO_DIR, f"c{idx}.mp4")
            with open(path, 'wb') as f: f.write(requests.get(link, timeout=10).content)
            return path
    except: pass
    
    # Pixabay Fallback
    try:
        r = requests.get("https://pixabay.com/api/videos/", params={"key": PIXABAY_KEY, "q": query, "per_page": 1}, timeout=10)
        if r.status_code == 200 and r.json().get('hits'):
            link = r.json()['hits'][0]['videos'].get('small', {}).get('url')
            if link:
                path = os.path.join(VIDEO_DIR, f"c{idx}.mp4")
                with open(path, 'wb') as f: f.write(requests.get(link, timeout=10).content)
                return path
    except: pass
    return None

# ================= 4. TTS (SILERO) =================
def generate_audio(scenes):
    print("🗣 Loading Silero TTS...")
    model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models', model='silero_tts', language='ru', speaker='xenia')
    
    paths = []
    for i, s in enumerate(scenes):
        p = os.path.join(AUDIO_DIR, f"a{i}.wav")
        print(f"   Synthesizing scene {i+1}...")
        model.save_wav(text=s['text'], speaker='xenia', sample_rate=48000, audio_path=p)
        paths.append(p)
    return paths

# ================= 5. ASSEMBLE (FFMPEG) =================
def assemble(scenes, audio_paths):
    print("🎬 Assembling video...")
    
    # 1. Concat Video List
    with open("v_list.txt", "w") as f:
        for i in range(len(scenes)):
            fp = os.path.join(VIDEO_DIR, f"c{i}.mp4")
            if os.path.exists(fp): f.write(f"file '{fp}'\n")
            else: # Create black stub if missing
                stub = os.path.join(VIDEO_DIR, f"c{i}.mp4")
                subprocess.run(f"ffmpeg -y -f lavfi -i color=c=black:s=1080x1920:d=5 -c:v libx264 -t 5 {stub}", shell=True)
                f.write(f"file '{stub}'\n")

    # 2. Concat Audio List
    with open("a_list.txt", "w") as f:
        for ap in audio_paths: f.write(f"file '{ap}'\n")

    # 3. Merge
    subprocess.run("ffmpeg -y -f concat -safe 0 -i v_list.txt -c copy temp_v.mp4", shell=True)
    subprocess.run("ffmpeg -y -f concat -safe 0 -i a_list.txt -c pcm_s16le temp_a.wav", shell=True)
    
    # Download Music
    mus_url = "https://cdn.pixabay.com/download/audio/2022/03/10/audio_c8c8a73467.mp3?filename=lofi-study-112191.mp3"
    mus_path = "bg.mp3"
    with open(mus_path, 'wb') as f: f.write(requests.get(mus_url).content)

    # Final Mix
    cmd = 'ffmpeg -y -i temp_v.mp4 -i temp_a.wav -i bg.mp3 -filter_complex "[1:a]volume=1[v];[2:a]volume=0.1[m];[v][m]amix=inputs=2[a]" -map 0:v -map "[a]" -c:v copy -c:a aac -shortest final_video.mp4'
    subprocess.run(cmd, shell=True)
    
    # Cleanup
    for f in ["v_list.txt", "a_list.txt", "temp_v.mp4", "temp_a.wav", "bg.mp3"]: 
        if os.path.exists(f): os.remove(f)
        
    print("✅ DONE! File: final_video.mp4")

# ================= MAIN =================
if __name__ == "__main__":
    topic = input("Enter video topic: ") or "AI news"
    script = get_script(topic)
    if script:
        scenes = parse_scenes(script)
        for i, s in enumerate(scenes):
            if not download_video(s['query'], i): print(f"⚠️ No video for {s['query']}")
        
        audio = generate_audio(scenes)
        assemble(scenes, audio)
