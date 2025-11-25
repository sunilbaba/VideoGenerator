
import os
import sys
import random
import requests
import asyncio
import time
from datetime import datetime, timedelta

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

# --- VIDEO SETTINGS ---
if VIDEO_MODE == "PORTRAIT":
    RESOLUTION = (1080, 1920)
    RESIZE_DIM = (1920, 3415)
else:
    RESOLUTION = (1920, 1080)
    RESIZE_DIM = (3415, 1920)

# Telugu Voice: Female (Shruti) or Male (Mohan)
VOICE = "te-IN-ShrutiNeural"

# --- THE STOCK UNIVERSE (NIFTY 50 + MAJOR PLAYERS) ---
# We scan these to find which one has news TODAY.
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LICI.NS", "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS",
    "TITAN.NS", "BAJFINANCE.NS", "SUNPHARMA.NS", "ADANIENT.NS", "TATAMOTORS.NS",
    "NTPC.NS", "ULTRACEMCO.NS", "TATASTEEL.NS", "POWERGRID.NS", "M&M.NS",
    "HCLTECH.NS", "JSWSTEEL.NS", "ADANIPORTS.NS", "COALINDIA.NS", "WIPRO.NS",
    "ONGC.NS", "BAJAJFINSV.NS", "DLF.NS", "VBL.NS", "ZOMATO.NS", 
    "HAL.NS", "TRENT.NS", "SIEMENS.NS", "DMART.NS", "JIOFIN.NS"
]

# --- 1. SMART NEWS HUNTER ---
def get_trending_stock():
    print("[*] Scanning Market for Fresh News...")
    
    # Shuffle to ensure we don't always pick the same "top" stock
    random.shuffle(WATCHLIST)
    
    selected_data = None
    
    # We check up to 10 stocks to find one with news
    # If we check too many, the script takes too long.
    for ticker in WATCHLIST[:15]:
        try:
            stock = yf.Ticker(ticker)
            news = stock.news
            
            # Check if there is ANY news
            if news and len(news) > 0:
                latest_news = news[0]
                # timestamp = latest_news.get('providerPublishTime', 0)
                # news_date = datetime.fromtimestamp(timestamp)
                
                # If we found news, we grab this stock!
                print(f" [!] Found News for {ticker}: {latest_news['title'][:30]}...")
                
                info = stock.info
                name = info.get('shortName', ticker.replace('.NS', ''))
                price = info.get('currentPrice', 0)
                mcap_crores = info.get('marketCap', 0) / 10000000 
                
                selected_data = {
                    "ticker": ticker,
                    "name": name,
                    "price": price,
                    "mcap": int(mcap_crores),
                    "headline": latest_news['title'],
                    "publisher": latest_news.get('publisher', 'News')
                }
                break # Stop searching, we found our candidate
            
        except Exception:
            continue
            
    # FALLBACK: If NO stock has news (rare), pick a random big one
    if not selected_data:
        print(" [!] No fresh news found. Picking random fallback.")
        fallback = random.choice(["RELIANCE.NS", "TCS.NS", "INFY.NS"])
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
    # 1. Draft Script (English)
    # We make it sound like a "Breaking News" flash
    english_script = (
        f"Breaking Stock Market Update! "
        f"Let's talk about {data['name']}. "
        f"The stock is currently trading at {data['price']} rupees. "
        f"According to {data['publisher']}, reports say: {data['headline']}. "
        f"With a market valuation of {data['mcap']} crore rupees, this is a key level to watch. "
        "Stay subscribed for more Indian market updates."
    )
    
    print(f"[*] English Draft: {english_script}")

    # 2. Translate to Telugu
    print("[*] Translating to Telugu...")
    try:
        telugu_script = GoogleTranslator(source='auto', target='te').translate(english_script)
    except:
        telugu_script = english_script # Fallback if translator fails

    # 3. Create Visual Prompt (English)
    image_prompt = (
        f"cinematic shot of {data['name']} office building in india, "
        f"stock market overlay, financial graph with rupees {data['price']}, "
        "news anchor studio background, 8k, photorealistic, dramatic lighting"
    )
    
    return {
        "title": f"News_{data['ticker']}",
        "script": telugu_script,
        "prompt": image_prompt
    }

# --- 2. AI VISUALS ---
def get_ai_image(prompt, filename):
    print(f"[*] Generating Image...")
    seed = random.randint(1, 99999)
    url = f"https://image.pollinations.ai/prompt/{prompt}?width={RESOLUTION[0]}&height={RESOLUTION[1]}&seed={seed}&model=flux&nologo=true"
    
    try:
        response = requests.get(url, timeout=120)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            return True
        return False
    except Exception as e:
        print(f"Connection Error: {e}")
        return False

# --- 3. NEURAL AUDIO ---
async def generate_audio(text, filename):
    print(f"[*] Generating Audio...")
    try:
        communicate = edge_tts.Communicate(text, VOICE)
        await communicate.save(filename)
        return True
    except Exception as e:
        print(f"[ERROR] Audio failed: {e}")
        return False

# --- 4. RENDER ---
def render_video(image_path, audio_path, output_path):
    print("[*] Rendering Video...")
    try:
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration + 1.0
        
        img_clip = ImageClip(image_path).set_duration(duration)
        img_clip = img_clip.resize(RESIZE_DIM)
        
        # Pan Effect
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
        print(f"[ERROR] Render failed: {e}")
        return False

# --- MAIN ---
async def main():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        
    base_dir = os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_path = os.path.join(base_dir, "temp_bg.jpg")
    audio_path = os.path.join(base_dir, "temp_voice.mp3")
    
    # 1. Find a Stock with News
    stock_data = get_trending_stock()
    
    # 2. Prepare Script
    video_content = prepare_script_and_visuals(stock_data)
    
    final_filename = f"{video_content['title']}_{timestamp}.mp4"
    output_path = os.path.join(base_dir, OUTPUT_FOLDER, final_filename)
    
    # 3. Generate Assets
    if not get_ai_image(video_content['prompt'], img_path): sys.exit(1)
    if not await generate_audio(video_content['script'], audio_path): sys.exit(1)
    
    # 4. Render
    if render_video(img_path, audio_path, output_path):
        print(f"\n[SUCCESS] Video Saved: {output_path}")
    else:
        sys.exit(1)

    # Cleanup
    if os.path.exists(img_path): os.remove(img_path)
    if os.path.exists(audio_path): os.remove(audio_path)

if __name__ == "__main__":
    asyncio.run(main())
