import random
import os
import sys
import requests
from datetime import datetime

# --- FIX FOR PILLOW 10 ERROR (MUST BE AT THE TOP) ---
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
# ----------------------------------------------------

from gtts import gTTS
from moviepy.editor import *

# --- CONFIGURATION ---
OUTPUT_FOLDER = "generated_videos"
RESOLUTION = (1080, 1920) # 9:16 Vertical HD
DURATION = 15 # Seconds

# Ensure output directory exists
if not os.path.exists(OUTPUT_FOLDER):
    os.makedirs(OUTPUT_FOLDER)

# --- DATA: The Content Database ---
NICHES = [
    {
        "name": "Pool Rooms",
        "prompt": "liminal space indoor pool complex, white tiles, crystal clear water, no windows, endless corridors, 90s CGI aesthetic, dreamcore, 8k, photorealistic",
        "script": "You have been swimming here for days. The water never gets cold. But you haven't seen the exit in a long time."
    },
    {
        "name": "Empty Mall",
        "prompt": "abandoned shopping mall at night, neon lights flickering, marble floor, plants, vaporwave, liminal space, lonely, highly detailed",
        "script": "The music is still playing on the speakers. It's a song you heard in your childhood. Why is the mall still open?"
    },
    {
        "name": "Foggy Playground",
        "prompt": "playground in thick fog at night, street lamp, metal slide, nostalgic, unsettling, silent hill aesthetic, grainy",
        "script": "Do not climb the slide. It goes down much further than it should."
    },
    {
        "name": "Glitch Field",
        "prompt": "grassy field with a floating black cube, television static texture, glitch art, surreal, weirdcore, windows xp wallpaper style",
        "script": "The sky is buffering. Please wait while reality loads."
    }
]

def get_ai_image(prompt, filename):
    print(f"[*] Generating Visuals...")
    # Using Pollinations.ai (Free API)
    seed = random.randint(1, 99999)
    url = f"https://image.pollinations.ai/prompt/{prompt}?width={RESOLUTION[0]}&height={RESOLUTION[1]}&seed={seed}&model=flux&nologo=true"
    
    try:
        response = requests.get(url, timeout=120)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            return True
        else:
            print(f"API Error: Status {response.status_code}")
            return False
    except Exception as e:
        print(f"Connection Error: {e}")
        return False

def create_video():
    # 1. Setup File Names with Date
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    concept = random.choice(NICHES)
    
    # Use absolute paths to avoid GitHub Actions path confusion
    base_dir = os.getcwd()
    img_path = os.path.join(base_dir, "temp_image.jpg")
    audio_path = os.path.join(base_dir, "temp_audio.mp3")
    
    final_filename = f"Anomaly_{timestamp}.mp4"
    # Ensure the output path is inside the folder
    output_path = os.path.join(base_dir, OUTPUT_FOLDER, final_filename)

    print(f"--- STARTING JOB: {concept['name']} ---")

    # 2. Fetch Assets
    if not get_ai_image(concept["prompt"], img_path):
        print("[CRITICAL] Failed to fetch image. Exiting.")
        sys.exit(1) # Fail the workflow so you know it broke

    # 3. Generate Audio
    print(f"[*] Synthesizing Audio: '{concept['script']}'...")
    try:
        tts = gTTS(text=concept["script"], lang='en', slow=False)
        tts.save(audio_path)
    except Exception as e:
        print(f"[CRITICAL] TTS failed: {e}")
        sys.exit(1)

    # 4. Render Video with MoviePy
    print("[*] Rendering Video (This may take 30-60 seconds)...")
    
    try:
        # Load Audio
        audio_clip = AudioFileClip(audio_path)
        
        # Create Image Clip
        clip = ImageClip(img_path).set_duration(DURATION)
        
        # Apply Vertical Pan (Ken Burns Effect)
        # We resize height to be larger than screen (1920 + 200px) so we can scroll it
        clip = clip.resize(height=RESOLUTION[1] + 200)
        
        # Scroll from top (-50) to bottom (-150) slowly
        clip = clip.set_position(lambda t: ('center', -50 - (t * 5)))
        
        # Combine
        final = CompositeVideoClip([clip], size=RESOLUTION)
        final = final.set_audio(audio_clip)

        # Write File
        final.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac', preset='medium')
        
        # 5. Final Verification
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"\n[SUCCESS] Video saved to: {output_path}")
            print(f"File Size: {os.path.getsize(output_path) / 1024 / 1024:.2f} MB")
        else:
            print("[ERROR] File was not saved correctly.")
            sys.exit(1)

    except Exception as e:
        print(f"[CRITICAL] Rendering failed: {e}")
        # Print full traceback for debugging
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Cleanup temp files
    if os.path.exists(img_path): os.remove(img_path)
    if os.path.exists(audio_path): os.remove(audio_path)

if __name__ == "__main__":
    create_video()
