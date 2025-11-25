import os
import sys
import random
import requests
import asyncio
import time
import urllib.parse
import traceback
from datetime import datetime, timedelta

# --- LIBRARIES ---
import yfinance as yf
import edge_tts
from moviepy.editor import *
import PIL.Image
from deep_translator import GoogleTranslator

# --- CHARTING ---
import mplfinance as mpf
import pandas as pd
# Removed pandas_ta to fix installation errors

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

# --- RELIABLE FALLBACK IMAGES ---
FALLBACK_IMAGES = [
    "https://picsum.photos/1080/1920?grayscale&blur=2",
    "https://picsum.photos/1080/1920?blur=4"
]

# --- STOCK LIST ---
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LICI.NS", "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS"
]

# ==========================================
# 1. TECHNICAL ANALYSIS (Native Pandas)
# ==========================================

def generate_technical_chart(ticker, name, filename):
    print(f"[*] Generating Technical Chart for {name}...", flush=True)
    try:
        # Get last 1 year of data to ensure we have enough for 200 SMA
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        
        if df.empty: return False
        
        # --- FIX: Calculate Moving Averages using standard Pandas ---
        # This replaces 'pandas_ta' and avoids the installation error
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()

        # Slice data to show only the last 6 months (so the chart isn't squished)
        df_plot = df.tail(120) 

        # Create Custom Style
        mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)
        s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc)

        # Plot Settings (Cyan for 50 SMA, Orange for 200 SMA)
        add_plots = [
            mpf.make_addplot(df_plot['SMA_50'], color='cyan', width=2, panel=0),
            mpf.make_addplot(df_plot['SMA_200'], color='orange', width=2, panel=0)
        ]
        
        # Save Chart
        mpf.plot(
            df_plot, 
            type='candle', 
            style=s, 
            addplot=add_plots,
            title=f"\n{name} - Technical Analysis",
            ylabel='Price (INR)',
            volume=True,
            savefig=dict(fname=filename, dpi=150, bbox_inches='tight'),
            figratio=(9, 10),
            figscale=1.2
        )
        print("   [SUCCESS] Chart saved.", flush=True)
        return True
    except Exception as e:
        print(f"   [ERROR] Chart generation failed: {e}", flush=True)
        return False

def get_market_analysis_data():
    """
    Fallback function: Analyzes Nifty 50 or Bank Nifty.
    """
    print("[!] No stock news found. Switching to Market Technical Analysis...", flush=True)
    
    indices = [
        {"ticker": "^NSEI", "name": "Nifty 50"},
        {"ticker": "^NSEBANK", "name": "Bank Nifty"}
    ]
    target = random.choice(indices)
    
    try:
        stock = yf.Ticker(target['ticker'])
        hist = stock.history(period="1mo")
        current_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2]
        change = current_price - prev_close
        pct_change = (change / prev_close) * 100
        
        trend = "bullish" if current_price > prev_close else "bearish"
        
        script = (
            f"Market Analysis Report for {target['name']}. "
            f"The index is currently trading at {int(current_price)} points. "
            f"Today, we see a {trend} move of {abs(int(change))} points, which is {abs(round(pct_change, 2))} percent. "
            "Technically, the chart shows strong support at lower levels. "
            "Watch the 50-day moving average carefully for the next breakout. "
            "Stay tuned for more technical updates."
        )
        
        return {
            "type": "technical",
            "title": f"Technical_{target['name'].replace(' ', '_')}",
            "ticker": target['ticker'],
            "name": target['name'],
            "script": script,
            "prompt": f"stock market chart background, {target['name']}, financial lines, 8k"
        }
        
    except Exception as e:
        print(f"   [FAIL] Market Analysis failed: {e}", flush=True)
        return None

# ==========================================
# 2. STANDARD NEWS FINDER
# ==========================================

def get_trending_stock():
    print("[*] Scanning Market for Fresh News...", flush=True)
    random.shuffle(WATCHLIST)
    
    for ticker in WATCHLIST[:15]:
        try:
            stock = yf.Ticker(ticker)
            news = stock.news
            
            if news and len(news) > 0:
                print(f" [!] Checking News for {ticker}...", flush=True)
                latest_news = news[0]
                title = latest_news.get('title', 'Market Update')
                publisher = latest_news.get('publisher', 'News Source')
                
                # Filter out junk titles
                if len(title) < 5: continue

                info = stock.info
                name = info.get('shortName', ticker)
                price = info.get('currentPrice', 0)
                mcap = int(info.get('marketCap', 0) / 10000000)
                
                print(f" [SUCCESS] Locked in: {ticker}", flush=True)
                
                english_script = (
                    f"Breaking Stock Market Update! Let's talk about {name}. "
                    f"The stock is currently trading at {price} rupees. "
                    f"According to {publisher}, reports say: {title}. "
                    f"With a market valuation of {mcap} crore rupees, this is a key level to watch. "
                    "Stay subscribed for more Indian market updates."
                )

                return {
                    "type": "news",
                    "title": f"News_{ticker}",
                    "script": english_script,
                    "prompt": f"cinematic shot of {name} building, stock market graph, 8k",
                    "ticker": ticker,
                    "name": name
                }
        except:
            continue
            
    return None

# ==========================================
# 3. GENERATORS
# ==========================================

def get_visuals_robust(data, filename):
    # IF TECHNICAL MODE: Try to generate a Real Chart first
    if data['type'] == 'technical':
        chart_filename = filename.replace(".jpg", "_chart.jpg")
        if generate_technical_chart(data['ticker'], data['name'], chart_filename):
            if os.path.exists(filename): os.remove(filename)
            os.rename(chart_filename, filename)
            return True

    # FALLBACK: Use AI Image
    print("[*] Generating AI Background...", flush=True)
    token = os.environ.get("HF_TOKEN")
    
    if token:
        print("   [Attempt] Hugging Face...", flush=True)
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.post(
                "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
                headers=headers, json={"inputs": data['prompt']}, timeout=60
            )
            if resp.status_code == 200:
                with open(filename, "wb") as f: f.write(resp.content)
                return True
        except: pass

    # LAST RESORT: Pollinations
    print("   [Attempt] Pollinations...", flush=True)
    try:
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(data['prompt'])}?width={RESOLUTION[0]}&height={RESOLUTION[1]}&model=flux&nologo=true"
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            with open(filename, 'wb') as f: f.write(resp.content)
            return True
    except: pass
    
    # ULTIMATE FALLBACK
    print("   [FALLBACK] Downloading generic image...", flush=True)
    try:
        with open(filename, 'wb') as f:
            f.write(requests.get(random.choice(FALLBACK_IMAGES)).content)
        return True
    except: return False

async def generate_audio_telugu(text, filename):
    print("[*] Translating & Generating Audio...", flush=True)
    try:
        telugu_text = GoogleTranslator(source='auto', target='te').translate(text)
        communicate = edge_tts.Communicate(telugu_text, VOICE)
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
        img_w, img_h = img_clip.size
        
        if img_w > img_h: # It's a chart (Square/Landscape)
             img_clip = img_clip.resize(width=1080)
             img_clip = img_clip.set_position("center")
        else: # It's a vertical AI image
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

# ==========================================
# 4. MAIN FLOW
# ==========================================

async def main():
    if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)
    base_dir = os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_path = os.path.join(base_dir, "temp_bg.jpg")
    audio_path = os.path.join(base_dir, "temp_voice.mp3")
    
    try:
        data = get_trending_stock()
        
        if not data:
            data = get_market_analysis_data()
            
        if not data:
            print("[CRITICAL] Could not fetch ANY data (News or Technical).", flush=True)
            sys.exit(1)

        print(f"[*] Mode: {data['type'].upper()} | Topic: {data['name']}", flush=True)
        
        final_filename = f"{data['title']}_{timestamp}.mp4"
        output_path = os.path.join(base_dir, OUTPUT_FOLDER, final_filename)
        
        if not get_visuals_robust(data, img_path): sys.exit(1)
        if not await generate_audio_telugu(data['script'], audio_path): sys.exit(1)
        
        if render_video(img_path, audio_path, output_path):
            print(f"\n[SUCCESS] Video Saved: {output_path}", flush=True)
        else:
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
