#!/usr/bin/env python3
"""
Full generator script with robust image generation pipeline:
 - Hugging Face Inference API (if HF_TOKEN set)
 - Pollinations (free)
 - Unsplash API search (if UNSPLASH_ACCESS_KEY set)
 - Guaranteed FALLBACK_IMAGES (final fallback)

Requirements (example):
pip install yfinance edge-tts moviepy pillow deep-translator mplfinance pandas requests
"""

import os
import sys
import random
import requests
import asyncio
import time
import urllib.parse
import traceback
import base64
from datetime import datetime, timedelta

# --- LIBRARIES ---
import yfinance as yf
import edge_tts
from moviepy.editor import *
from PIL import Image
from deep_translator import GoogleTranslator

# --- CHARTING ---
import mplfinance as mpf
import pandas as pd

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

# --- GUARANTEED FALLBACK IMAGES (High-Quality Stock) ---
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1535320903710-d9cf63d4040c?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1642543492481-44e81e3914a7?q=80&w=1080&h=1920&fit=crop"
]

# --- STOCK LIST ---
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LICI.NS", "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS"
]

# -----------------------
# Helper: retry with backoff
# -----------------------
def _retry_request(func, retries=3, backoff=1.5):
    last_exc = None
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            last_exc = e
            sleep_t = backoff * (2 ** i)
            print(f"   [RETRY] attempt {i+1}/{retries} failed: {e} — sleeping {sleep_t:.1f}s", flush=True)
            time.sleep(sleep_t)
    raise last_exc

# ==========================================
# 1. TECHNICAL CHART GENERATOR
# ==========================================
def generate_technical_chart(ticker, name, filename):
    print(f"[*] Generating Technical Chart for {name}...", flush=True)
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty:
            print("   [WARN] Empty dataframe from yfinance.", flush=True)
            return False

        # Calculate Moving Averages
        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df_plot = df.tail(120)

        # Chart Style
        mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)
        s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc)
        add_plots = [
            mpf.make_addplot(df_plot['SMA_50'], color='cyan', width=2, panel=0),
            mpf.make_addplot(df_plot['SMA_200'], color='orange', width=2, panel=0)
        ]

        # Save Chart
        mpf.plot(
            df_plot, type='candle', style=s, addplot=add_plots,
            title=f"\n{name} - Technical Analysis", ylabel='Price (INR)', volume=True,
            savefig=dict(fname=filename, dpi=150, bbox_inches='tight'),
            figratio=(9, 10), figscale=1.2
        )
        print("   [SUCCESS] Chart saved.", flush=True)
        return True
    except Exception as e:
        print(f"   [ERROR] Chart generation failed: {e}", flush=True)
        traceback.print_exc()
        return False

# ==========================================
# 2. DATA SOURCE: NEWS & TECHNICALS
# ==========================================
def get_trending_stock():
    print("[*] Scanning Market for Fresh News...", flush=True)
    random.shuffle(WATCHLIST)
    for ticker in WATCHLIST[:15]:
        try:
            stock = yf.Ticker(ticker)
            news = getattr(stock, "news", None) or []
            if news and len(news) > 0:
                print(f" [!] Checking News for {ticker}...", flush=True)
                latest_news = news[0]
                title = latest_news.get('title', 'Market Update')
                publisher = latest_news.get('publisher', 'News Source')
                if len(title) < 5:
                    continue

                info = getattr(stock, "info", {}) or {}
                name = info.get('shortName', ticker)
                price = info.get('currentPrice', 0)
                mcap = int(info.get('marketCap', 0) / 10000000) if info.get('marketCap') else 0

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
        except Exception as e:
            print(f"   [WARN] news check failed for {ticker}: {e}", flush=True)
            continue
    return None

def get_market_analysis_data():
    print("[!] No stock news found. Switching to Market Technical Analysis...", flush=True)
    indices = [{"ticker": "^NSEI", "name": "Nifty 50"}, {"ticker": "^NSEBANK", "name": "Bank Nifty"}]
    target = random.choice(indices)
    try:
        stock = yf.Ticker(target['ticker'])
        hist = stock.history(period="1mo")
        if hist.shape[0] < 2:
            raise ValueError("Not enough history rows")
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
        traceback.print_exc()
        return None

# ==========================================
# 3. ROBUST VISUAL GENERATION PIPELINE
# ==========================================
def get_visuals_robust(data, filename):
    # 1. IF TECHNICAL MODE: Try to generate a Real Chart first
    if data.get('type') == 'technical':
        chart_filename = filename.replace(".jpg", "_chart.jpg")
        if generate_technical_chart(data['ticker'], data['name'], chart_filename):
            if os.path.exists(filename):
                os.remove(filename)
            os.rename(chart_filename, filename)
            return True

    def save_bytes_to_file(bytes_data, path):
        with open(path, "wb") as f:
            f.write(bytes_data)

    # 2. ATTEMPT: Hugging Face API (Needs HF_TOKEN)
    token = os.environ.get("HF_TOKEN")
    if token:
        print("   [Attempt 1] Hugging Face (Stable Diffusion XL)...", flush=True)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/octet-stream"}
        hf_url = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        payload = {"inputs": data.get('prompt', ''), "options": {"wait_for_model": True}}
        try:
            def call_hf():
                resp = requests.post(hf_url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                ctype = resp.headers.get("Content-Type", "")
                if ctype and ctype.startswith("image/"):
                    return resp.content
                # Sometimes HF returns JSON with base64-encoded image fields -> try to parse
                try:
                    j = resp.json()
                    # look for base64 fields (heuristic)
                    for k, v in j.items():
                        if isinstance(v, str) and len(v) > 100 and all(ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n" for ch in v[:10]):
                            try:
                                return base64.b64decode(v)
                            except Exception:
                                continue
                except Exception:
                    pass
                raise ValueError(f"Hugging Face returned non-image content-type: {ctype}")
            img_bytes = _retry_request(call_hf, retries=2, backoff=2)
            save_bytes_to_file(img_bytes, filename)
            print("   [SUCCESS] Image generated via Hugging Face.", flush=True)
            return True
        except Exception as e:
            print(f"   [WARN] Hugging Face Error: {e}", flush=True)

    # 3. ATTEMPT: Pollinations API (Backup AI)
    print("   [Attempt 2] Pollinations API (Flux)...", flush=True)
    try:
        poll_prompt = urllib.parse.quote(data.get('prompt', 'stock market'))
        poll_url = f"https://image.pollinations.ai/prompt/{poll_prompt}?width={RESOLUTION[0]}&height={RESOLUTION[1]}&model=flux&nologo=true"
        headers = {"Accept": "image/*,application/octet-stream"}
        def call_poll():
            resp = requests.get(poll_url, headers=headers, timeout=45)
            resp.raise_for_status()
            ctype = resp.headers.get("Content-Type", "")
            if not ctype or not ctype.startswith("image/"):
                raise ValueError(f"Pollinations returned Content-Type={ctype}")
            return resp.content
        img_bytes = _retry_request(call_poll, retries=3, backoff=1.5)
        save_bytes_to_file(img_bytes, filename)
        print("   [SUCCESS] Image generated via Pollinations.", flush=True)
        return True
    except Exception as e:
        print(f"   [WARN] Pollinations failed: {e}", flush=True)

    # 4. ATTEMPT: Unsplash API (Search & hotlink) - optional but more reliable than random external images
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if unsplash_key:
        print("   [Attempt 3] Unsplash search fallback...", flush=True)
        try:
            q = urllib.parse.quote_plus(data.get('name', data.get('prompt', 'stock market')))
            search_url = f"https://api.unsplash.com/search/photos?query={q}&orientation=portrait&per_page=10"
            headers = {"Authorization": f"Client-ID {unsplash_key}", "Accept-Version": "v1"}
            def call_unsplash():
                r = requests.get(search_url, headers=headers, timeout=20)
                r.raise_for_status()
                j = r.json()
                results = j.get("results", [])
                if not results:
                    raise ValueError("Unsplash returned no results")
                photo = random.choice(results)
                img_url = photo.get("urls", {}).get("regular") or photo.get("urls", {}).get("full")
                if not img_url:
                    raise ValueError("Unsplash result missing urls")
                r2 = requests.get(img_url, timeout=30)
                r2.raise_for_status()
                ctype = r2.headers.get("Content-Type", "")
                if not ctype or not ctype.startswith("image/"):
                    raise ValueError("Unsplash image request returned non-image")
                return r2.content
            img_bytes = _retry_request(call_unsplash, retries=2, backoff=1.5)
            save_bytes_to_file(img_bytes, filename)
            print("   [SUCCESS] Image downloaded from Unsplash.", flush=True)
            return True
        except Exception as e:
            print(f"   [WARN] Unsplash search failed: {e}", flush=True)
    else:
        print("   [INFO] UNSPLASH_ACCESS_KEY not set — skipping Unsplash search fallback.", flush=True)

    # 5. FINAL FALLBACK: GUARANTEED FALLBACK_IMAGES
    print("   [Attempt 4] Downloading Guaranteed Stock Image...", flush=True)
    for attempt in range(len(FALLBACK_IMAGES)):
        try:
            url = random.choice(FALLBACK_IMAGES)
            def call_fallback():
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                ctype = resp.headers.get("Content-Type", "")
                if not ctype or not ctype.startswith("image/"):
                    raise ValueError("Fallback URL not an image")
                return resp.content
            img_bytes = _retry_request(call_fallback, retries=2, backoff=1)
            save_bytes_to_file(img_bytes, filename)
            print("   [SUCCESS] Stock image downloaded.", flush=True)
            return True
        except Exception as e:
            print(f"   [WARN] Fallback image attempt failed: {e}", flush=True)
            continue

    print("   [CRITICAL] All visual generation methods failed.", flush=True)
    return False

# --- AUDIO & RENDER ---
async def generate_audio_telugu(text, filename):
    print("[*] Translating & Generating Audio...", flush=True)
    try:
        telugu_text = GoogleTranslator(source='auto', target='te').translate(text)
        communicate = edge_tts.Communicate(telugu_text, VOICE)
        await communicate.save(filename)
        return True
    except Exception as e:
        print(f"[ERROR] Audio failed: {e}", flush=True)
        traceback.print_exc()
        return False

def render_video(image_path, audio_path, output_path):
    print("[*] Rendering Video...", flush=True)
    try:
        audio_clip = AudioFileClip(audio_path)
        duration = audio_clip.duration + 1.0

        img_clip = ImageClip(image_path).set_duration(duration)
        img_w, img_h = img_clip.size

        # Logic to handle both square charts and portrait images
        if img_w > img_h:  # It's a chart
            img_clip = img_clip.resize(width=1080)
            img_clip = img_clip.set_position("center")
        else:  # It's a portrait image
            # robust resize while preserving aspect ratio; then center crop if needed
            img_clip = img_clip.resize(height=RESIZE_DIM[1])
            # position movement (subtle pan)
            if VIDEO_MODE == "PORTRAIT":
                img_clip = img_clip.set_position(lambda t: ('center', -50 - (t * 20)))
            else:
                img_clip = img_clip.set_position(lambda t: (-50 - (t * 20), 'center'))

        final = CompositeVideoClip([img_clip], size=RESOLUTION)
        final = final.set_audio(audio_clip)

        # ensure output folder exists
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

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
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    base_dir = os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    img_path = os.path.join(base_dir, "temp_bg.jpg")
    audio_path = os.path.join(base_dir, "temp_voice.mp3")

    try:
        # 1. Get Data (News or Technicals)
        data = get_trending_stock()
        if not data:
            data = get_market_analysis_data()
        if not data:
            print("[CRITICAL] Could not fetch ANY data. Exiting.", flush=True)
            sys.exit(1)

        print(f"[*] Mode: {data['type'].upper()} | Topic: {data['name']}", flush=True)
        final_filename = f"{data['title']}_{timestamp}.mp4"
        output_path = os.path.join(base_dir, OUTPUT_FOLDER, final_filename)

        # 2. Generate Visuals (With 4-Layer Fallback)
        if not get_visuals_robust(data, img_path):
            print("[CRITICAL] All visual generation methods failed.", flush=True)
            sys.exit(1)

        # 3. Generate Audio
        if not await generate_audio_telugu(data['script'], audio_path):
            print("[CRITICAL] Audio generation failed.", flush=True)
            sys.exit(1)

        # 4. Render Video
        if render_video(img_path, audio_path, output_path):
            print(f"\n[SUCCESS] Video Saved: {output_path}", flush=True)
        else:
            sys.exit(1)

    except Exception as e:
        print(f"\n[FATAL ERROR] {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    finally:
        # Cleanup temp files
        try:
            if os.path.exists(img_path):
                os.remove(img_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
