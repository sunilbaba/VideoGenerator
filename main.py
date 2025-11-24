import random
import os
import sys
import requests
from datetime import datetime
from gtts import gTTS
from moviepy.editor import *

# --- CONFIGURATION ---
OUTPUT_FOLDER = "generated_videos"
RESOLUTION = (1080, 1920) # 9:16 Vertical
DURATION = 15 # Seconds

# Ensure output directory exists
if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

# --- DATA ---
NICHES = [
    {
        "name": "Pool Rooms",
        "prompt": "liminal space indoor pool complex, white tiles, crystal clear water, no windows, endless corridors, 90s CGI aesthetic, dreamcore, 8k",
        "script": "You have been swimming here for days. The water never gets cold. But you haven't seen the exit in a long time."
    },
    {
        "name": "Empty Mall",
        "prompt": "abandoned shopping mall at night, neon lights flickering, marble floor, vaporwave, liminal space, lonely, highly detailed",
        "script": "The music is still playing. It's a song you heard in your childhood. Why is the mall still open?"
    }
]

def get_ai_image(prompt, filename):
    print(f"[*] Generating Visuals...")
    seed = random.randint(1, 99999)
    url = f"https://image.pollinations.ai/prompt/{prompt}?width={RESOLUTION[0]}&height={RESOLUTION[1]}&seed={seed}&model=flux&nologo=true"
    response = requests.get(url, timeout=120) # Increased timeout
    if response.status_code == 200:
        with open(filename, 'wb') as f:
            f.write(response.content)
        return True
    return False

def create_video():
    # 1. Setup File Names
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    concept = random.choice(NICHES)
    
    # Use absolute paths to avoid confusion
    base_dir = os.getcwd()
    img_path = os.path.join(base_dir, "temp_image.jpg")
    audio_path = os.path.join(base_dir, "temp_audio.mp3")
    final_filename = f"Anomaly_{timestamp}.mp4"
    output_path = os.path.join(base_dir, OUTPUT_FOLDER, final_filename)

    print(f"--- STARTING: {concept['name']} ---")

    # 2. Fetch Assets
    if not get_ai_image(concept["prompt"], img_path):
        print("Error: Could not fetch image from API")
        sys.exit(1) # Force crash

    # 3. Generate Audio
    print("[*] Generating Audio...")
    tts = gTTS(text=concept["script"], lang='en', slow=False)
    tts.save(audio_path)

    # 4. Render Video
    print("[*] Rendering with MoviePy...")
    
    # NO TRY/EXCEPT BLOCK HERE - Let it crash if it fails!
    audio_clip = AudioFileClip(audio_path)
    clip = ImageClip(img_path).set_duration(DURATION)
    clip = clip.resize(height=RESOLUTION[1] + 100) 
    clip = clip.set_position(lambda t: ('center', -50 + t * 2))
    
    final = CompositeVideoClip([clip], size=RESOLUTION)
    final = final.set_audio(audio_clip)

    final.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac')
    
    # 5. Verify File Created
    if os.path.exists(output_path):
        print(f"[SUCCESS] Saved to {output_path}")
        print(f"File size: {os.path.getsize(output_path)} bytes")
    else:
        print("[ERROR] Render finished but file not found!")
        sys.exit(1)

    # Cleanup
    if os.path.exists(img_path): os.remove(img_path)
    if os.path.exists(audio_path): os.remove(audio_path)

if __name__ == "__main__":
    create_video()
