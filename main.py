#!/usr/bin/env python3
"""
Slides video generator (per-slide TTS) with:
 - Smooth transitions (A): 0.8s fade-in/out, gentle slide-up
 - Per-slide TTS (edge-tts) in Telugu
 - Skip/merge very short slides
 - Dark gradient overlay for readability
 - Company logo watermark (configurable path & opacity)
 - Outputs to generated_videos/
"""

import os
import sys
import random
import requests
import asyncio
import time
import urllib.parse
import traceback
from datetime import datetime
from io import BytesIO

# third-party libraries
import yfinance as yf
import edge_tts
from moviepy.editor import *
from moviepy.video.fx.all import resize
from PIL import Image, ImageDraw
from deep_translator import GoogleTranslator
from bs4 import BeautifulSoup

# ---------------- CONFIG ----------------
OUTPUT_FOLDER = "generated_videos"
VIDEO_MODE = "PORTRAIT"   # PORTRAIT or LANDSCAPE

if VIDEO_MODE == "PORTRAIT":
    RESOLUTION = (1080, 1920)
else:
    RESOLUTION = (1920, 1080)

VOICE = "te-IN-ShrutiNeural"

# slide text sizing / thresholds
MIN_SLIDE_CHARS = 40
MAX_SLIDE_CHARS = 1200

# Transition style A (Very smooth)
FADE_DURATION = 0.8      # seconds (fade-in and fade-out)
SLIDE_UP_PIXELS = 60     # total upward motion across slide duration (gentle)
PADDING_PER_SLIDE = 0.35 # extra seconds padding per slide

# Ken Burns (subtle zoom)
ZOOM_FACTOR = 0.04       # 4% zoom over slide duration

# logo watermark settings
LOGO_PATH_ENV = os.environ.get("LOGO_PATH", "")  # optional override via env
DEFAULT_LOGO_PATH = "assets/logo.png"            # default location in repo
LOGO_OPACITY = 0.65      # 0..1
LOGO_SCALE = 0.18        # fraction of width for logo (approx)

# dark gradient overlay (top->transparent->bottom) parameters
GRADIENT_TOP_ALPHA = 0.55   # opacity at top (0..1)
GRADIENT_BOTTOM_ALPHA = 0.35

FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1535320903710-d9cf63d4040c?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1642543492481-44e81e3914a7?q=80&w=1080&h=1920&fit=crop"
]

WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LICI.NS", "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS"
]

# ---------------- util ----------------
def _retry_request(func, retries=3, backoff=1.5):
    last_exc = None
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            last_exc = e
            sleep_t = backoff * (2 ** i)
            print(f"[RETRY] attempt {i+1}/{retries} failed: {e} — sleeping {sleep_t:.1f}s", flush=True)
            time.sleep(sleep_t)
    raise last_exc

# ---------------- pick topic ----------------
def get_trending_stock():
    random.shuffle(WATCHLIST)
    for ticker in WATCHLIST[:15]:
        try:
            stock = yf.Ticker(ticker)
            news = getattr(stock, "news", None) or []
            if news and len(news) > 0:
                latest = news[0]
                title = latest.get('title', 'Market Update')
                publisher = latest.get('publisher', 'News Source')
                link = latest.get('link') or latest.get('url')
                info = getattr(stock, "info", {}) or {}
                name = info.get('shortName', ticker)
                price = info.get('currentPrice', 0)
                mcap = int(info.get('marketCap', 0) / 10000000) if info.get('marketCap') else 0
                script = f"Breaking update on {name}. Price: {price} rupees. {title}. Market cap approx {mcap} crore."
                return {"type":"news","title":f"News_{ticker}","name":name,"script":script,"article_link":link}
        except Exception as e:
            print(f"[WARN] get_trending_stock error for {ticker}: {e}", flush=True)
            continue
    return None

def get_market_analysis_data():
    indices = [{"ticker":"^NSEI","name":"Nifty 50"},{"ticker":"^NSEBANK","name":"Bank Nifty"}]
    target = random.choice(indices)
    try:
        stock = yf.Ticker(target['ticker'])
        hist = stock.history(period="1mo")
        if hist.shape[0] < 2:
            raise ValueError("Not enough history")
        curr = hist['Close'].iloc[-1]
        prev = hist['Close'].iloc[-2]
        change = curr - prev
        pct = (change / prev) * 100
        trend = "bullish" if change > 0 else "bearish"
        script = f"{target['name']} shows a {trend} move of {abs(round(pct,2))}% today at {int(curr)} points."
        return {"type":"technical","title":f"Technical_{target['name']}","name":target['name'],"script":script,"article_link":None}
    except Exception as e:
        print(f"[ERROR] market analysis failed: {e}", flush=True)
        return None

# ---------------- scrape ----------------
def fetch_article_text(url):
    if not url:
        return None
    try:
        headers = {"User-Agent":"Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        paras = []
        article = soup.find("article")
        if article:
            for p in article.find_all("p"):
                t = p.get_text(strip=True)
                if t:
                    paras.append(t)
        if not paras:
            # pick largest div/section with many <p>
            candidates = soup.find_all(["div","section"])
            best = None
            best_count = 0
            for c in candidates:
                ps = c.find_all("p")
                if len(ps) > best_count:
                    best_count = len(ps)
                    best = c
            if best and best_count > 0:
                for p in best.find_all("p"):
                    t = p.get_text(strip=True)
                    if t:
                        paras.append(t)
        if not paras:
            meta = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name":"description"})
            if meta and meta.get("content"):
                paras = [meta.get("content").strip()]
        if not paras:
            ps = soup.find_all("p")
            for p in ps[:10]:
                t = p.get_text(strip=True)
                if t:
                    paras.append(t)
        if not paras:
            return None
        full = "\n\n".join(paras)
        # limit to avoid huge videos
        maxlen = MAX_SLIDE_CHARS * 10
        if len(full) > maxlen:
            full = full[:maxlen].rsplit(" ",1)[0] + "..."
        return full
    except Exception as e:
        print(f"[ERROR] fetch_article_text failed: {e}", flush=True)
        return None

# ---------------- split + merge ----------------
def split_text_into_slides(text, title=None, approx_chars=700):
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    slides = []
    if title:
        slides.append({"title": title, "body": ""})
    cur = []
    cur_len = 0
    for p in paras:
        p_len = len(p)
        if cur_len + p_len + 2 <= approx_chars:
            cur.append(p); cur_len += p_len + 2
        else:
            slides.append({"title": None, "body": "\n\n".join(cur)})
            cur = [p]; cur_len = p_len + 2
    if cur:
        slides.append({"title": None, "body": "\n\n".join(cur)})
    # merge extremely short slides into previous
    cleaned = []
    for s in slides:
        body = (s.get("body") or "").strip()
        if len(body) < MIN_SLIDE_CHARS:
            if cleaned:
                prev = cleaned[-1]
                prev_body = prev.get("body","")
                prev["body"] = (prev_body + "\n\n" + body).strip()
            else:
                # if first slide short, keep (title slide typically) or skip
                cleaned.append(s)
        else:
            cleaned.append(s)
    if len(cleaned) > 14:
        return split_text_into_slides(text, title=title, approx_chars=1200)
    return cleaned

# ---------------- per-slide TTS ----------------
async def synthesize_slide_tts(text, out_path):
    try:
        telugu = GoogleTranslator(source='auto', target='te').translate(text)
        comm = edge_tts.Communicate(telugu, VOICE)
        await comm.save(out_path)
        return True
    except Exception as e:
        print(f"[ERROR] synthesize_slide_tts failed: {e}", flush=True)
        traceback.print_exc()
        return False

# ---------------- background + gradient + logo ----------------
def download_background(path):
    for url in FALLBACK_IMAGES:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200 and r.headers.get("Content-Type","").startswith("image/"):
                with open(path, "wb") as f:
                    f.write(r.content)
                return True
        except Exception:
            continue
    # create plain dark
    img = Image.new("RGB", RESOLUTION, (12, 12, 12))
    img.save(path, quality=90)
    return True

def create_dark_gradient_overlay(path):
    """Create a PNG gradient (same size as RESOLUTION) with alpha channel to overlay on top."""
    w, h = RESOLUTION
    base = Image.new("RGBA", (w, h), (0,0,0,0))
    draw = ImageDraw.Draw(base)
    # vertical gradient: top alpha -> middle transparent -> bottom alpha (subtle)
    for y in range(h):
        # compute alpha: stronger near top and bottom, lower at center
        # normalized position 0..1
        pos = y / (h-1)
        # alpha curve: blend top and bottom influences
        top_influence = max(0.0, 1.0 - (pos * 2.0))   # decreases from top
        bottom_influence = max(0.0, 1.0 - ((1.0 - pos) * 2.0)) # increases toward bottom
        # combine and scale using configured alphas
        alpha = int(255 * (top_influence * GRADIENT_TOP_ALPHA + bottom_influence * GRADIENT_BOTTOM_ALPHA) / 2.0)
        draw.line([(0,y),(w,y)], fill=(0,0,0,alpha))
    base.save(path, format="PNG")
    return True

def load_logo_clip(logo_path):
    try:
        if not os.path.exists(logo_path):
            return None
        logo = Image.open(logo_path).convert("RGBA")
        # determine target width
        w, h = RESOLUTION
        max_logo_w = int(w * LOGO_SCALE)
        # scale preserving aspect ratio
        aspect = logo.width / logo.height
        new_w = max_logo_w
        new_h = int(new_w / aspect)
        logo = logo.resize((new_w, new_h), Image.LANCZOS)
        # save a temporary file (logo_temp.png)
        tmp = "logo_temp.png"
        logo.save(tmp, format="PNG")
        clip = ImageClip(tmp).set_duration(0.1)  # will be used as image clip; duration will be extended later per slide
        clip = clip.set_opacity(LOGO_OPACITY)
        return clip
    except Exception as e:
        print(f"[WARN] load_logo_clip failed: {e}", flush=True)
        return None

# ---------------- create slide clip ----------------
def create_slide_clip(bg_path, gradient_path, logo_clip, slide, audio_path, idx, total):
    # audio info -> duration
    audio_clip = AudioFileClip(audio_path)
    base_dur = audio_clip.duration
    duration = max(2.5, base_dur + PADDING_PER_SLIDE)

    # background base clip
    bg = ImageClip(bg_path).set_duration(duration)

    # Ken Burns zoom (subtle)
    try:
        zoom_clip = bg.resize(lambda t: 1.0 + ZOOM_FACTOR * (t / duration)).set_duration(duration)
    except Exception:
        zoom_clip = bg.set_duration(duration)

    clips = [zoom_clip]

    # overlay gradient PNG as ImageClip with same duration
    grad_clip = ImageClip(gradient_path).set_duration(duration)
    clips.append(grad_clip)

    # text rendering (title card or body)
    if slide.get("title"):
        text = slide["title"]
        fontsize = 78 if VIDEO_MODE=="PORTRAIT" else 60
        txt = TextClip(text, fontsize=fontsize, font="DejaVu-Sans", color="white", method="label")
        txt = txt.set_duration(duration)
        # gentle slide-up: start slightly lower, end higher
        y_start = int(RESOLUTION[1]*0.62)
        y_end = int(RESOLUTION[1]*0.34)
        def pos_title(t):
            prog = min(1.0, t / duration)
            y = int(y_start + (y_end - y_start) * prog)
            x = (RESOLUTION[0] - txt.w) / 2
            return (int(x), int(y))
        txt = txt.set_position(pos_title)
        clips.append(txt)
    else:
        body = slide.get("body","")
        fontsize = 44 if VIDEO_MODE=="PORTRAIT" else 36
        caption_w = RESOLUTION[0] - 120
        body_clip = TextClip(body, fontsize=fontsize, font="DejaVu-Sans", method="caption", size=(caption_w, None), align="West", color="white")
        body_clip = body_clip.set_duration(duration)
        x = int((RESOLUTION[0] - caption_w) / 2)
        y_start = int(RESOLUTION[1] * 0.62)
        y_end = int(RESOLUTION[1] * 0.18)
        def pos_body(t):
            prog = min(1.0, t / duration)
            y = int(y_start + (y_end - y_start) * prog)
            return (x, y)
        body_clip = body_clip.set_position(pos_body)
        clips.append(body_clip)

    # logo watermark: clone with same duration and position (bottom-left)
    if logo_clip:
        logo_dur = duration
        # clone the logo clip and set duration & position bottom-left with margin
        logo_c = logo_clip.set_duration(duration)
        margin = 28
        logo_c = logo_c.set_position((margin, RESOLUTION[1] - logo_c.h - margin))
        clips.append(logo_c)

    # footer slide counter small
    footer_txt = f"{idx+1}/{total}"
    footer_clip = TextClip(footer_txt, fontsize=26, font="DejaVu-Sans", color="white", method="label")
    footer_clip = footer_clip.set_duration(duration).set_position(("right", RESOLUTION[1]-60))
    clips.append(footer_clip)

    comp = CompositeVideoClip(clips, size=RESOLUTION).set_duration(duration)

    # apply fade-in/out (style A durations)
    comp = comp.fx(vfx.fadein, FADE_DURATION).fx(vfx.fadeout, FADE_DURATION)

    # set audio: pad silence if needed to match duration
    if audio_clip.duration < duration:
        silence = AudioClip(lambda t: 0*t, duration=(duration - audio_clip.duration)).set_fps(44100)
        audio_final = concatenate_audioclips([audio_clip, silence])
    else:
        audio_final = audio_clip.subclip(0, duration)

    comp = comp.set_audio(audio_final)
    return comp

# ---------------- main ----------------
async def main():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    base = os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bg_path = os.path.join(base, "temp_bg.jpg")
    grad_path = os.path.join(base, "temp_grad.png")

    try:
        # pick topic
        data = get_trending_stock()
        if not data:
            data = get_market_analysis_data()
        if not data:
            print("[CRITICAL] No data available", flush=True); sys.exit(1)

        title = data.get("name") or data.get("title")
        final_filename = f"{data.get('title')}_{timestamp}.mp4"
        out_path = os.path.join(base, OUTPUT_FOLDER, final_filename)
        link = data.get("article_link")

        # fetch article or fallback to script
        article_text = None
        if link and link.startswith("http"):
            article_text = fetch_article_text(link)
        if not article_text:
            article_text = data.get("script") or f"{title} - Market update."

        # split into slides, merge short
        slides = split_text_into_slides(article_text, title=title, approx_chars=700)
        if not slides:
            slides = [{"title": title, "body": data.get("script","")}]

        print(f"[INFO] Created {len(slides)} slides", flush=True)

        # prepare background+gradient
        download_background(bg_path)
        create_dark_gradient_overlay(grad_path)

        # load logo clip (if available)
        logo_path = LOGO_PATH_ENV if LOGO_PATH_ENV else DEFAULT_LOGO_PATH
        logo_clip = load_logo_clip(logo_path) if os.path.exists(logo_path) else None
        if logo_clip:
            print(f"[INFO] Logo watermark loaded from {logo_path}", flush=True)
        else:
            print("[INFO] No logo found; continuing without watermark", flush=True)

        # per-slide TTS generation
        temp_audio_paths = []
        for idx, slide in enumerate(slides):
            if slide.get("title"):
                text_to_read = slide["title"]
            else:
                text_to_read = slide.get("body","")
            if not text_to_read or len(text_to_read.strip()) == 0:
                temp_audio_paths.append(None); continue
            if len(text_to_read) > MAX_SLIDE_CHARS:
                text_to_read = text_to_read[:MAX_SLIDE_CHARS].rsplit(" ",1)[0] + "..."
            audio_file = os.path.join(base, f"slide_audio_{idx}.mp3")
            ok = await synthesize_slide_tts(text_to_read, audio_file)
            if not ok:
                # fallback: short silent audio
                silent = AudioClip(lambda t: 0*t, duration=3.0).set_fps(44100)
                silent.write_audiofile(audio_file, fps=44100, codec="mp3", verbose=False, logger=None)
            temp_audio_paths.append(audio_file)

        # filter/merge extremely short slides (again) using audio durations
        filtered_slides = []
        filtered_audio = []
        for s, ap in zip(slides, temp_audio_paths):
            body = (s.get("body") or "").strip()
            title_flag = bool(s.get("title"))
            audio_len = 0
            if ap and os.path.exists(ap):
                try:
                    audio_len = AudioFileClip(ap).duration
                except Exception:
                    audio_len = 0
            # decide keep/merge/skip
            if title_flag or len(body) >= MIN_SLIDE_CHARS or audio_len > 0.5:
                filtered_slides.append(s); filtered_audio.append(ap)
            else:
                # merge with previous if possible
                if filtered_slides and not filtered_slides[-1].get("title"):
                    prev = filtered_slides[-1]
                    prev["body"] = (prev.get("body","") + "\n\n" + body).strip()
                    # do NOT regenerate previous audio here (tradeoff for speed)
                else:
                    # skip silently
                    print(f"[SKIP] dropping very short slide: '{body[:40]}'", flush=True)

        slides = filtered_slides
        temp_audio_paths = filtered_audio

        if not slides:
            print("[CRITICAL] No slides after filtering. Aborting.", flush=True); sys.exit(1)

        # build clips per slide
        slide_clips = []
        total = len(slides)
        for idx, (s, a) in enumerate(zip(slides, temp_audio_paths)):
            if not a or not os.path.exists(a):
                # make short silent file
                fallback_a = os.path.join(base, f"slide_audio_fallback_{idx}.mp3")
                silent = AudioClip(lambda t: 0*t, duration=3.0).set_fps(44100)
                silent.write_audiofile(fallback_a, fps=44100, codec="mp3", verbose=False, logger=None)
                a = fallback_a
            clip = create_slide_clip(bg_path, grad_path, logo_clip, s, a, idx, total)
            slide_clips.append(clip)

        # concatenate
        final = concatenate_videoclips(slide_clips, method="compose")

        # write output
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        print(f"[INFO] Writing final video to {out_path} ...", flush=True)
        final.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", preset="medium", threads=4, ffmpeg_params=["-movflags","+faststart"])
        print(f"[SUCCESS] Video saved: {out_path}", flush=True)

    except Exception as e:
        print(f"[FATAL] {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
    finally:
        # cleanup temp files
        try:
            for f in os.listdir(base):
                if f.startswith("slide_audio_") and f.endswith(".mp3"):
                    try: os.remove(os.path.join(base,f))
                    except: pass
                if f.startswith("slide_audio_fallback_") and f.endswith(".mp3"):
                    try: os.remove(os.path.join(base,f))
                    except: pass
            if os.path.exists(bg_path): os.remove(bg_path)
            if os.path.exists(grad_path): os.remove(grad_path)
            if os.path.exists("logo_temp.png"): os.remove("logo_temp.png")
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
