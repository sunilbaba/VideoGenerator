import os
import sys
import random
import requests
import asyncio
import time
import urllib.parse  # <--- NEW: For safe URL encoding
import traceback     # <--- NEW: For printing full error logs
from datetime import datetime

# --- LIBRARIES ---
import yfinance as yf
import edge_tts
from moviepy.editor import *
import PIL.Image
from deep_translator import GoogleTranslator

# --- FIX FOR PILLOW ERROR ---
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

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
        f"According to {data['publisher']}, reports say: {data['headline']}.. "
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

    # SIMPLIFIED PROMPT (Better for API success)
    image_prompt = (
        f"cinematic shot of {data['name']} office building, "
        f"stock market graph overlay, financial news studio, "
        "8k, photorealistic"
    )
    
    return {
        "title": f"News_{data['ticker']}",
        "script": telugu_script,
        "prompt": image_prompt
    }

# --- IMPROVED IMAGE GENERATOR WITH LOGGING ---
def get_ai_image(prompt, filename):
    print(f"[*] Generating Image...", flush=True)
    
    # 1. URL ENCODE THE PROMPT (Fixes broken URLs)
    encoded_prompt = urllib.parse.quote(prompt)
    seed = random.randint(1, 99999)
    
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={RESOLUTION[0]}&height={RESOLUTION[1]}&seed={seed}&model=flux&nologo=true"
    
    # 2. RETRY MECHANISM (Tries 3 times before failing)
    for attempt in range(1, 4):
        try:
            print(f"   [Attempt {attempt}] Requesting Image...", flush=True)
            response = requests.get(url, timeout=60)
            
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    f.write(response.content)
                print("   [SUCCESS] Image saved.", flush=True)
                return True
            else:
                # LOG THE SPECIFIC ERROR CODE
                print(f"   [ERROR] Status Code: {response.status_code}", flush=True)
                print(f"   [ERROR] Message: {response.text}", flush=True)
        
        except Exception as e:
            print(f"   [EXCEPTION] {e}", flush=True)
        
        time.sleep(2) # Wait 2 seconds before retry
        
    return False

async def generate_audio(text, filename):
    print(f"[*] Generating Audio...", flush=True)
    try:
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(filename)
        return True
    except Exception as e:
        print(f"[ERROR] Audio failed: {e}", flush=True)
        return False

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
        traceback.print_exc() # Print full crash report
        return False

async def main():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        
    base_dir = os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_path = os.path.join(base_dir, "temp_bg.jpg")
    audio_path = os.path.join(base_dir, "temp_voice.mp3")
    
    try:
        # 1. Get Data
        stock_data = get_trending_stock()
        video_content = prepare_script_and_visuals(stock_data)
        
        final_filename = f"{video_content['title']}_{timestamp}.mp4"
        output_path = os.path.join(base_dir, OUTPUT_FOLDER, final_filename)
        
        # 2. Generate Assets (With checks)
        if not get_ai_image(video_content['prompt'], img_path):
            print("[CRITICAL] Could not generate image after 3 attempts.", flush=True)
            sys.exit(1)
            
        if not await generate_audio(video_content['script'], audio_path):
            print("[CRITICAL] Could not generate audio.", flush=True)
            sys.exit(1)
        
        # 3. Render
        if render_video(img_path, audio_path, output_path):
            print(f"\n[SUCCESS] Video Saved: {output_path}", flush=True)
        else:
            print("[CRITICAL] Video rendering failed.", flush=True)
            sys.exit(1)

    except Exception as e:
        print(f"\n[FATAL SCRIPT ERROR] {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
        
    finally:
        # Cleanup
        if os.path.exists(img_path): os.remove(img_path)
        if os.path.exists(audio_path): os.remove(audio_path)

if __name__ == "__main__":
    asyncio.run(main())
