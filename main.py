#!/usr/bin/env python3
"""
Video generator script WITHOUT Pollinations (removed).
Pipeline:
 - Try multiple Hugging Face inference models (if HF_TOKEN set)
 - Try Unsplash search (if UNSPLASH_ACCESS_KEY set)
 - Fall back to guaranteed FALLBACK_IMAGES

Make sure to set optional env secrets:
 - HF_TOKEN (Hugging Face token) -- optional but recommended
 - UNSPLASH_ACCESS_KEY -- optional but recommended for reliable images
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
from datetime import datetime

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

        df['SMA_50'] = df['Close'].rolling(window=50).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df_plot = df.tail(120)

        mc = mpf.make_marketcolors(up='#00ff00', down='#ff0000', inherit=True)
        s = mpf.make_mpf_style(base_mpf_style='nightclouds', marketcolors=mc)
        add_plots = [
            mpf.make_addplot(df_plot['SMA_50'], color='cyan', width=2, panel=0),
            mpf.make_addplot(df_plot['SMA_200'], color='orange', width=2, panel=0)
        ]

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
# 3. ROBUST VISUAL GENERATION PIPELINE (NO POLLINATIONS)
# ==========================================
HF_MODEL_CANDIDATES = [
    "stabilityai/stable-diffusion-xl-base-1.0",
    "stabilityai/stable-diffusion-xl-refiner-1.0",
    "stabilityai/stable-diffusion-3-medium",
    "runwayml/stable-diffusion-v1-5"
]

def _try_hf_models(prompt, filename):
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("   [INFO] HF_TOKEN not set; skipping Hugging Face attempts.", flush=True)
        return False

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/octet-stream"}
    payload = {"inputs": prompt, "options": {"wait_for_model": True}}

    for model in HF_MODEL_CANDIDATES:
        model_url = f"https://api-inference.huggingface.co/models/{model}"
        print(f"   [HF] Trying model: {model}", flush=True)
        try:
            def call_model():
                resp = requests.post(model_url, headers=headers, json=payload, timeout=50)
                # For server errors allow retries by raising
                if resp.status_code >= 500:
                    resp.raise_for_status()
                return resp
            resp = _retry_request(call_model, retries=2, backoff=2)
        except Exception as e:
            print(f"     [HF] network/server error for {model}: {e}", flush=True)
            continue

        status = getattr(resp, "status_code", None)
        try:
            text_snippet = resp.text[:400]
        except Exception:
            text_snippet = "<no-text>"

        if status == 200:
            ctype = resp.headers.get("Content-Type", "")
            if ctype and ctype.startswith("image/"):
                with open(filename, "wb") as f:
                    f.write(resp.content)
                print(f"   [SUCCESS] Hugging Face image from {model}", flush=True)
                return True
            else:
                print(f"   [HF] Unexpected Content-Type {ctype} from {model}; response body: {text_snippet}", flush=True)
                continue

        if status in (410, 403, 404):
            print(f"   [HF] Model {model} returned {status}. Likely gated/removed or token lacks access. Response: {text_snippet}", flush=True)
            continue

        print(f"   [HF] Model {model} returned status {status}. Response: {text_snippet}", flush=True)
    return False

def _try_unsplash(prompt, filename):
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not unsplash_key:
        print("   [INFO] UNSPLASH_ACCESS_KEY not set; skipping Unsplash attempts.", flush=True)
        return False

    print("   [Unsplash] Searching Unsplash...", flush=True)
    try:
        q = urllib.parse.quote_plus(prompt or "stock market")
        search_url = f"https://api.unsplash.com/search/photos?query={q}&orientation=portrait&per_page=10"
        headers = {"Authorization": f"Client-ID {unsplash_key}", "Accept-Version": "v1"}
        def call_search():
            r = requests.get(search_url, headers=headers, timeout=20)
            r.raise_for_status()
            return r.json()
        j = _retry_request(call_search, retries=2, backoff=1.5)
        results = j.get("results", []) if isinstance(j, dict) else []
        if not results:
            print("   [Unsplash] No results returned.", flush=True)
            return False
        photo = random.choice(results)
        img_url = photo.get("urls", {}).get("regular") or photo.get("urls", {}).get("full")
        if not img_url:
            print("   [Unsplash] Result missing urls.", flush=True)
            return False
        def call_img():
            r2 = requests.get(img_url, timeout=30)
            r2.raise_for_status()
            return r2
        r2 = _retry_request(call_img, retries=2, backoff=1)
        ctype = r2.headers.get("Content-Type", "")
        if not ctype or not ctype.startswith("image/"):
            print(f"   [Unsplash] Image request returned non-image Content-Type: {ctype}", flush=True)
            return False
        with open(filename, "wb") as f:
            f.write(r2.content)
        print("   [SUCCESS] Image downloaded from Unsplash.", flush=True)
        return True
    except Exception as e:
        print(f"   [WARN] Unsplash search failed: {e}", flush=True)
        return False

def get_visuals_robust(data, filename):
    # 1) If technical: try to generate a real chart first
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

    # 2) Try HF models (if HF_TOKEN)
    if _try_hf_models(data.get('prompt', ''), filename):
        return True

    # 3) Try Unsplash (search)
    if _try_unsplash(data.get('name') or data.get('prompt', ''), filename):
        return True

    # 4) Final fallback images
    print("   [Fallback] Trying guaranteed FALLBACK_IMAGES ...", flush=True)
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

        if img_w > img_h:
            img_clip = img_clip.resize(width=1080)
            img_clip = img_clip.set_position("center")
        else:
            img_clip = img_clip.resize(height=RESIZE_DIM[1])
            if VIDEO_MODE == "PORTRAIT":
                img_clip = img_clip.set_position(lambda t: ('center', -50 - (t * 20)))
            else:
                img_clip = img_clip.set_position(lambda t: (-50 - (t * 20), 'center'))

        final = CompositeVideoClip([img_clip], size=RESOLUTION)
        final = final.set_audio(audio_clip)

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
        data = get_trending_stock()
        if not data:
            data = get_market_analysis_data()
        if not data:
            print("[CRITICAL] Could not fetch ANY data. Exiting.", flush=True)
            sys.exit(1)

        print(f"[*] Mode: {data['type'].upper()} | Topic: {data['name']}", flush=True)
        final_filename = f"{data['title']}_{timestamp}.mp4"
        output_path = os.path.join(base_dir, OUTPUT_FOLDER, final_filename)

        if not get_visuals_robust(data, img_path):
            print("[CRITICAL] All visual generation methods failed.", flush=True)
            sys.exit(1)

        if not await generate_audio_telugu(data['script'], audio_path):
            print("[CRITICAL] Audio generation failed.", flush=True)
            sys.exit(1)

        if render_video(img_path, audio_path, output_path):
            print(f"\n[SUCCESS] Video Saved: {output_path}", flush=True)
        else:
            sys.exit(1)

    except Exception as e:
        print(f"\n[FATAL ERROR] {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)

    finally:
        try:
            if os.path.exists(img_path):
                os.remove(img_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
