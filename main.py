import os
import sys
import random
import requests
import asyncio
import time
import urllib.parse
import traceback
from datetime import datetime

# --- LIBRARIES ---
import yfinance as yf
import edge_tts
from moviepy.editor import *
import PIL.Image
from deep_translator import GoogleTranslator

# --- CONFIGURATION ---
OUTPUT_FOLDER = "generated_videos"
VIDEO_MODE = "PORTRAIT" 

if VIDEO_MODE == "PORTRAIT":
    RESOLUTION = (1080, 1920)
    RESIZE_DIM = (1920, 3415)
else:
    RESOLUTION = (1920, 1080)
    RESIZE_DIM = (3415, 1920)

VOICE = "te-IN-ShrutiNeural"

# --- RELIABLE FALLBACK IMAGES (Wikimedia Commons) ---
# Used if ALL AI generation fails, ensuring the video still renders.
FALLBACK_IMAGES = [
    "https://upload.wikimedia.org/wikipedia/commons/e/e1/Stock_Market_prices.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b3/Stock_market_wall_street.jpg/1280px-Stock_market_wall_street.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/00/New_York_Stock_Exchange_-_panoramio_%283%29.jpg/1280px-New_York_Stock_Exchange_-_panoramio_%283%29.jpg"
]

# --- STOCK LIST ---
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LICI.NS", "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS",
    "TITAN.NS", "BAJFINANCE.NS", "SUNPHARMA.NS", "ADANIENT.NS", "TATAMOTORS.NS"
]

def get_trending_stock():
    print("[*] Scanning Market for Fresh News...", flush=True)
    random.shuffle(WATCHLIST)
    selected_data = None
    
    for ticker in WATCHLIST[:15]:
        try:
            stock = yf.Ticker(ticker)
            news = stock.news
            if news and len(news) > 0:
                print(f" [!] Found News for {ticker}", flush=True)
                latest_news = news[0]
                info = stock.info
                
                selected_data = {
                    "ticker": ticker,
                    "name": info.get('shortName', ticker),
                    "price": info.get('currentPrice', 0),
                    "mcap": int(info.get('marketCap', 0) / 10000000),
                    "headline": latest_news['title'],
                    "publisher": latest_news.get('publisher', 'News')
                }
                break 
        except Exception:
            continue
            
    if not selected_data:
        print(" [!] No fresh news found. Picking random fallback.", flush=True)
        fallback = random.choice(["RELIANCE.NS", "TCS.NS"])
        stock = yf.Ticker(fallback)
        info = stock.info
        selected_data = {
            "ticker": fallback,
            "name": info.get('shortName', fallback),
            "price": info.get('currentPrice', 0),
            "mcap": int(info.get('marketCap', 0) / 10000000),
            "headline": "Market is trading with mixed signals today.",
            "publisher": "Market Update"
        }
    return selected_data

def prepare_script_and_visuals(data):
    english_script = (
        f"Breaking Stock Market Update! Let's talk about {data['name']}. "
        f"The stock is currently trading at {data['price']} rupees. "
        f"According to {data['publisher']}, reports say: {data['headline']}. "
        f"With a market valuation of {data['mcap']} crore rupees, this is a key level to watch. "
        "Stay subscribed for more Indian market updates."
    )
    print(f"[*] English Draft: {english_script}", flush=True)

    print("[*] Translating to Telugu...", flush=True)
    try:
        telugu_script = GoogleTranslator(source='auto', target='te').translate(english_script)
    except Exception as e:
        print(f" [!] Translation Failed: {e}", flush=True)
        telugu_script = english_script 

    image_prompt = (
        f"stock market concept art for {data['name']}, financial graph rising, "
        "digital currency background, cinematic lighting, 8k, photorealistic"
    )
    
    return {
        "title": f"News_{data['ticker']}",
        "script": telugu_script,
        "prompt": image_prompt
    }

# --- GENERATION ENGINE ---
def generate_image_huggingface(prompt, filename):
    """
    Uses Hugging Face Inference API. Requires HF_TOKEN in secrets.
    """
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("   [WARN] No HF_TOKEN found. Skipping Hugging Face.", flush=True)
        return False

    print("   [Attempt] Trying Hugging Face (Stable Diffusion XL)...", flush=True)
    API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.post(API_URL, headers=headers, json={"inputs": prompt}, timeout=60)
        if response.status_code == 200:
            with open(filename, "wb") as f:
                f.write(response.content)
            print("   [SUCCESS] Image generated via Hugging Face.", flush=True)
            return True
        else:
            print(f"   [FAIL] HF Status: {response.status_code} {response.text}", flush=True)
            return False
    except Exception as e:
        print(f"   [FAIL] HF Error: {e}", flush=True)
        return False

def generate_image_pollinations(prompt, filename):
    """
    Free API, often blocked by GitHub IPs.
    """
    print("   [Attempt] Trying Pollinations (Flux)...", flush=True)
    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={RESOLUTION[0]}&height={RESOLUTION[1]}&model=flux&nologo=true"
    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            print("   [SUCCESS] Image generated via Pollinations.", flush=True)
            return True
    except:
        pass
    return False

def download_fallback_image(filename):
    """
    Downloads a real stock market image from Wikimedia if AI fails.
    """
    print("   [FALLBACK] AI failed. Downloading generic stock image...", flush=True)
    url = random.choice(FALLBACK_IMAGES)
    try:
        # Fake user agent to avoid Wikipedia blocking
        headers = {'User-Agent': 'Mozilla/5.0'} 
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            print("   [SUCCESS] Fallback image saved.", flush=True)
            return True
    except Exception as e:
        print(f"   [CRITICAL] Fallback failed: {e}", flush=True)
    return False

def get_visuals_robust(prompt, filename):
    print(f"[*] Starting Visual Generation Pipeline...", flush=True)
    
    # 1. Try Hugging Face (Best Quality)
    if generate_image_huggingface(prompt, filename): return True
    
    # 2. Try Pollinations (Backup)
    if generate_image_pollinations(prompt, filename): return True
    
    # 3. Last Resort (Wikimedia)
    if download_fallback_image(filename): return True
    
    return False

# --- AUDIO ---
async def generate_audio(text, filename):
    print(f"[*] Generating Audio...", flush=True)
    try:
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(filename)
        return True
    except Exception as e:
        print(f"[ERROR] Audio failed: {e}", flush=True)
        return False

# --- RENDER ---
def render_video(image_path, audio_path, output_path):
    print("[*] Rendering Video...", flush=True)
    try:
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration + 1.0
        
        img_clip = ImageClip(image_path).set_duration(duration)
        img_clip = img_clip.resize(RESIZE_DIM)
        
        if VIDEO_MODE == "PORTRAIT":
            img_clip = img_clip.set_position(lambda t: ('center', -50 - (t * 20)))
        else:
            img_clip = img_clip.set_position(lambda t: (-50 - (t * 20), 'center'))
            
        final = CompositeVideoClip([img_clip], size=RESOLUTION)
        final = final.set_audio(audio_clip)
        
        final.write_videofile(
            output_path, fps=24, codec='libx264', audio_codec='aac', preset='medium', threads=4
        )
        return True
    except Exception as e:
        print(f"[ERROR] Render failed: {e}", flush=True)
        traceback.print_exc()
        return False

# --- MAIN ---
async def main():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        
    base_dir = os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_path = os.path.join(base_dir, "temp_bg.jpg")
    audio_path = os.path.join(base_dir, "temp_voice.mp3")
    
    try:
        stock_data = get_trending_stock()
        video_content = prepare_script_and_visuals(stock_data)
        
        final_filename = f"{video_content['title']}_{timestamp}.mp4"
        output_path = os.path.join(base_dir, OUTPUT_FOLDER, final_filename)
        
        # 1. Generate Visuals (With 3-Layer Fallback)
        if not get_visuals_robust(video_content['prompt'], img_path):
            print("[CRITICAL] All visual generation methods failed.", flush=True)
            sys.exit(1)
            
        # 2. Audio
        if not await generate_audio(video_content['script'], audio_path):
            print("[CRITICAL] Audio generation failed.", flush=True)
            sys.exit(1)
        
        # 3. Render
        if render_video(img_path, audio_path, output_path):
            print(f"\n[SUCCESS] Video Saved: {output_path}", flush=True)
        else:
            print("[CRITICAL] Video rendering failed.", flush=True)
            sys.exit(1)

    except Exception as e:
        print(f"\n[FATAL ERROR] {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
        
    finally:
        if os.path.exists(img_path): os.remove(img_path)
        if os.path.exists(audio_path): os.remove(audio_path)

if __name__ == "__main__":
    asyncio.run(main())
