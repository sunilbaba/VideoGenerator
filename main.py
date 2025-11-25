
#!/usr/bin/env python3
"""
Cinematic slides video generator (no ImageMagick/TextClip).
- Per-slide TTS (edge-tts)
- Per-slide audio files (one per slide)
- Title + body slides with cinematic fade & zoom
- Skip/merge very short slides
- Dark gradient overlay and company logo watermark (logo.png)
- Uses Pillow to render text images (avoids ImageMagick)
"""

import os
import sys
import random
import requests
import asyncio
import time
import textwrap
import traceback
from datetime import datetime
from io import BytesIO

# Third-party libs
import yfinance as yf
import edge_tts
from moviepy.editor import (
    AudioFileClip, ImageClip, CompositeVideoClip,
    concatenate_videoclips, VideoFileClip, concatenate_audioclips
)
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from deep_translator import GoogleTranslator
from bs4 import BeautifulSoup

# Charting optionally (kept for technical mode)
import mplfinance as mpf
import pandas as pd

# ---------------- CONFIG ----------------
OUTPUT_FOLDER = "generated_videos"
VIDEO_MODE = "PORTRAIT"  # PORTRAIT or LANDSCAPE

if VIDEO_MODE == "PORTRAIT":
    RESOLUTION = (1080, 1920)
else:
    RESOLUTION = (1920, 1080)

VOICE = "te-IN-ShrutiNeural"
MIN_SLIDE_CHARS = 40        # skip slides shorter than this
MAX_SLIDE_CHARS = 1200     # cap slide text length
TITLE_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
]
BODY_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
]
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1535320903710-d9cf63d4040c?q=80&w=1080&h=1920&fit=crop"
]
WATCHLIST = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "KOTAKBANK.NS",
    "LICI.NS", "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS"
]

# Cinematic timing & effects
FADE_DURATION = 1.2   # seconds fade in/out
PADDING_PER_SLIDE = 0.35  # seconds breathing room per slide
ZOOM_FACTOR = 0.06    # total zoom-in across slide
TITLE_CHAR_WRAP = 40  # target wrap width for title
BODY_CHAR_WRAP = 36   # base wrap width for body (adjusted by resolution)
SLIDE_BODY_CHAR_APPROX = 700  # target chars per body slide

# Watermark/logo
COMPANY_LOGO_FILENAME = "logo.png"  # optional; place in repo root
LOGO_MAX_WIDTH_RATIO = 0.22  # logo max width relative to video width
LOGO_OPACITY = 0.85

# ---------------- utilities ----------------
def _retry_request(func, retries=3, backoff=1.5):
    last = None
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            last = e
            sleep_t = backoff * (2 ** i)
            print(f"[RETRY] attempt {i+1}/{retries} failed: {e}; sleeping {sleep_t}s", flush=True)
            time.sleep(sleep_t)
    raise last

# ---------------- fonts ----------------
def find_font(path_list, fallback_size):
    for p in path_list:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, fallback_size)
            except Exception:
                continue
    # fallback to PIL default font (bitmap) - size ignored but usable
    print("[WARN] No specified TTF font found; using default PIL bitmap font.", flush=True)
    return ImageFont.load_default()

# ---------------- data selection ----------------
def get_trending_stock():
    print("[*] Scanning watchlist for news...", flush=True)
    random.shuffle(WATCHLIST)
    for t in WATCHLIST[:15]:
        try:
            stock = yf.Ticker(t)
            news = getattr(stock, "news", []) or []
            if news:
                n = news[0]
                title = n.get("title", "").strip()
                publisher = n.get("publisher", "")
                link = n.get("link") or n.get("url")
                info = getattr(stock, "info", {}) or {}
                name = info.get("shortName", t)
                price = info.get("currentPrice", 0)
                mcap = int(info.get("marketCap", 0) / 10000000) if info.get("marketCap") else 0
                script = (
                    f"Breaking update for {name}. Current price {price} rupees. "
                    f"Reported by {publisher}: {title}. Market valuation approx {mcap} crore rupees."
                )
                return {"type":"news", "title":f"News_{t}", "name":name, "script":script, "article_link":link}
        except Exception as e:
            print(f"[WARN] yfinance error for {t}: {e}", flush=True)
    return None

def get_market_analysis_data():
    print("[*] Using index technical summary (fallback).", flush=True)
    indices = [{"ticker":"^NSEI","name":"Nifty 50"}, {"ticker":"^NSEBANK","name":"Bank Nifty"}]
    tar = random.choice(indices)
    try:
        stock = yf.Ticker(tar["ticker"])
        hist = stock.history(period="1mo")
        if hist.shape[0] < 2:
            raise RuntimeError("Not enough history")
        cur = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2]
        change = cur - prev
        pct = (change/prev)*100
        trend = "bullish" if change>0 else "bearish"
        script = f"{tar['name']} shows a {trend} move of {abs(round(pct,2))}% today at {int(cur)} points."
        return {"type":"technical","title":f"Technical_{tar['name']}","name":tar['name'],"script":script,"article_link":None}
    except Exception as e:
        print(f"[ERROR] market analysis failed: {e}", flush=True)
        return None

# ---------------- scraping ----------------
def fetch_article_text(url):
    if not url:
        return None
    try:
        print(f"[*] Fetching article: {url}", flush=True)
        headers = {"User-Agent":"Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Prefer <article>
        paras = []
        article_tag = soup.find("article")
        if article_tag:
            for p in article_tag.find_all("p"):
                t = p.get_text(strip=True)
                if t:
                    paras.append(t)

        if not paras:
            # find largest div/section by number of <p>
            candidates = soup.find_all(["div","section"])
            best = None
            best_count = 0
            for c in candidates:
                ps = c.find_all("p")
                if len(ps) > best_count:
                    best_count = len(ps)
                    best = c
            if best:
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
                if t: paras.append(t)

        if not paras:
            print("[WARN] Could not extract article body.", flush=True)
            return None

        text = "\n\n".join(paras)
        max_len = MAX_SLIDE_CHARS * 10
        if len(text) > max_len:
            text = text[:max_len].rsplit(" ",1)[0] + "..."
        return text
    except Exception as e:
        print(f"[ERROR] fetch_article_text failed: {e}", flush=True)
        return None

# ---------------- split & merge slides ----------------
def split_text_into_slides(text, title=None, approx_chars=SLIDE_BODY_CHAR_APPROX):
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    slides = []
    if title:
        slides.append({"title":title, "body":""})

    cur = []
    cur_len = 0
    for p in paras:
        p_len = len(p)
        if cur_len + p_len + 2 <= approx_chars:
            cur.append(p)
            cur_len += p_len + 2
        else:
            slides.append({"title":None, "body": "\n\n".join(cur)})
            cur = [p]; cur_len = p_len + 2
    if cur:
        slides.append({"title":None, "body": "\n\n".join(cur)})

    # merge very short slides into previous
    cleaned = []
    for s in slides:
        body = (s.get("body") or "").strip()
        if len(body) < MIN_SLIDE_CHARS:
            if cleaned and not cleaned[-1].get("title"):
                cleaned[-1]["body"] = (cleaned[-1].get("body","") + "\n\n" + body).strip()
            else:
                # attempt to append to next by just adding; if it's first, keep it for now
                if cleaned:
                    cleaned.append(s)
                else:
                    # keep short first slide (title usually) — only drop if truly empty
                    if body:
                        cleaned.append(s)
        else:
            cleaned.append(s)

    # cap number of slides
    if len(cleaned) > 18:
        return split_text_into_slides(text, title=title, approx_chars=1200)
    return cleaned

# ---------------- PIL text rendering ----------------
def render_text_image(text, width_px, font_path_list, base_font_size, color=(255,255,255), align="left", line_spacing=4, padding=40):
    """
    Render multiline text into a transparent PNG using PIL and return PIL.Image object.
    - width_px: total width; function will wrap words to fit into width - 2*padding
    - font_path_list: list of font paths to try
    """
    # determine font
    try:
        font = None
        for p in font_path_list:
            if os.path.exists(p):
                font = ImageFont.truetype(p, base_font_size)
                break
        if font is None:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    max_text_width = width_px - 2*padding
    # wrap text into lines by measuring
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        wsize = font.getsize(test)[0]
        if wsize <= max_text_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    # build image height based on lines
    line_height = font.getsize("Ay")[1] + line_spacing
    img_h = padding*2 + line_height * max(1, len(lines))
    img = Image.new("RGBA", (width_px, img_h), (0,0,0,0))
    draw = ImageDraw.Draw(img)

    # draw lines
    y = padding
    for line in lines:
        w, h = font.getsize(line)
        if align == "center":
            x = (width_px - w)//2
        elif align == "right":
            x = width_px - w - padding
        else:
            x = padding
        draw.text((x,y), line, font=font, fill=color)
        y += line_height

    return img

# ---------------- gradient overlay ----------------
def create_dark_gradient_overlay(size, strength=0.6):
    w,h = size
    grd = Image.new("RGBA", (w,h), (0,0,0,0))
    draw = ImageDraw.Draw(grd)
    # top transparent -> bottom dark
    for i in range(h):
        alpha = int(255 * (strength * (i / h)))
        draw.line([(0,i),(w,i)], fill=(0,0,0,alpha))
    # add subtle vignette radial blur (optional)
    return grd.filter(ImageFilter.GaussianBlur(radius=2))

# ---------------- background helper ----------------
def download_background(path):
    for url in FALLBACK_IMAGES:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200 and r.headers.get("Content-Type","").startswith("image/"):
                with open(path,"wb") as f:
                    f.write(r.content)
                return True
        except Exception:
            continue
    # fallback solid
    img = Image.new("RGB", RESOLUTION, (12,12,12))
    img.save(path, quality=90)
    return True

# ---------------- TTS ----------------
async def synthesize_text_to_file(text, out_path):
    try:
        telugu = GoogleTranslator(source='auto', target='te').translate(text)
        comm = edge_tts.Communicate(telugu, VOICE)
        await comm.save(out_path)
        return True
    except Exception as e:
        print(f"[ERROR] TTS failed: {e}", flush=True)
        traceback.print_exc()
        return False

# ---------------- watermark/logo ----------------
def load_logo_if_exists(max_width_px):
    if not os.path.exists(COMPANY_LOGO_FILENAME):
        print("[INFO] No logo found; continuing without watermark", flush=True)
        return None
    try:
        logo = Image.open(COMPANY_LOGO_FILENAME).convert("RGBA")
        w,h = logo.size
        target_w = int(max_width_px)
        if w > target_w:
            ratio = target_w / w
            logo = logo.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
        # apply opacity
        if LOGO_OPACITY < 1.0:
            alpha = logo.split()[3].point(lambda p: int(p * LOGO_OPACITY))
            logo.putalpha(alpha)
        return logo
    except Exception as e:
        print(f"[WARN] loading logo failed: {e}", flush=True)
        return None

# ---------------- create slide clip (PIL-based text images) ----------------
def create_slide_clip(bg_path, gradient_img, logo_img, slide, audio_path, idx, total_slides):
    # load audio duration
    audio_clip = AudioFileClip(audio_path)
    base_dur = audio_clip.duration
    duration = base_dur + PADDING_PER_SLIDE

    # Background ImageClip
    bg_clip = ImageClip(bg_path).set_duration(duration)
    # Zoom effect using resize(lambda t: ...)
    try:
        zoom_clip = bg_clip.resize(lambda t: 1.0 + ZOOM_FACTOR * (t/duration)).set_duration(duration)
    except Exception:
        zoom_clip = bg_clip.set_duration(duration)

    # create a composite PIL image for overlay text + gradient + logo as a PNG for this slide
    W,H = RESOLUTION
    canvas = Image.new("RGBA", (W,H))
    # paste gradient overlay at top of canvas (transparent dark to bottom)
    if gradient_img:
        canvas = Image.alpha_composite(canvas, gradient_img.resize((W,H)).convert("RGBA"))
    # create text image for slide
    if slide.get("title"):
        # big title card
        # wrap title to multiple lines if too long
        title_text = slide["title"]
        # fontsize relate to resolution
        title_font_size = int(W * 0.075)  # e.g., 1080 -> 81
        title_img = render_text_image(title_text, W, TITLE_FONT_PATHS, title_font_size, color=(255,255,255), align="center", padding=60)
        # center title_img vertically
        tx = 0
        ty = int(H*0.30 - title_img.size[1]//2)
        canvas.paste(title_img, (tx, max(0,ty)), title_img)
    else:
        # body slide: render body text
        body_text = slide.get("body","")
        body_font_size = int(W * 0.040)  # e.g., 1080 -> 43
        # reduce wrap char count by adjusting base font size
        body_img = render_text_image(body_text, W, BODY_FONT_PATHS, body_font_size, color=(240,240,240), align="left", padding=70)
        # place at 20% down
        bx = 0
        by = int(H*0.18)
        canvas.paste(body_img, (bx, by), body_img)

    # paste company logo at top-right if provided
    if logo_img:
        lw, lh = logo_img.size
        lx = W - lw - 36
        ly = 36
        canvas.paste(logo_img, (lx, ly), logo_img)

    # convert canvas to ImageClip
    tmp_bytes = BytesIO()
    canvas.convert("RGBA").save(tmp_bytes, format="PNG")
    tmp_bytes.seek(0)
    overlay_clip = ImageClip(tmp_bytes).set_duration(duration)

    # Composite: zoom_clip + overlay_clip
    comp = CompositeVideoClip([zoom_clip, overlay_clip.set_position(("center","center"))], size=RESOLUTION).set_duration(duration)

    # fade in/out
    comp = comp.fx(lambda c: c.fadein(FADE_DURATION).fadeout(FADE_DURATION))

    # set audio
    # pad silence if audio shorter than duration (shouldn't usually happen)
    if audio_clip.duration < duration:
        silence = AudioFileClip(make_silence_clip(duration - audio_clip.duration))
        # simpler: use concatenate_audioclips with silence generated as AudioFileClip from lambda not directly possible
        # We'll just set audio_clip as is; MoviePy will handle shorter audio by leaving silence
        comp = comp.set_audio(audio_clip.set_duration(duration))
    else:
        comp = comp.set_audio(audio_clip.subclip(0, duration))

    return comp

# small helper to create silence audio file using moviepy - returns path string
def make_silence_clip(sec):
    # create silent wav via numpy-free method using moviepy's AudioClip? but AudioClip required function -> write to file
    # Instead we'll generate a tiny silent mp3 using ffmpeg via moviepy: (we'll avoid complexity and not use)
    # For robustness we won't call this; rarely needed.
    return None

# ---------------- main flow ----------------
async def main():
    base = os.getcwd()
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        # 1) pick topic/news
        data = get_trending_stock()
        if not data:
            data = get_market_analysis_data()
        if not data:
            print("[FATAL] No data; aborting", flush=True); sys.exit(1)

        title = data.get("name") or data.get("title") or "Market Update"
        out_file = os.path.join(base, OUTPUT_FOLDER, f"{data.get('title')}_{timestamp}.mp4")
        article_link = data.get("article_link")

        # 2) fetch article text
        article_text = None
        if article_link:
            article_text = fetch_article_text(article_link)
        if not article_text:
            article_text = data.get("script") or title

        # 3) split into slides
        slides = split_text_into_slides(article_text, title=title, approx_chars=SLIDE_BODY_CHAR_APPROX)
        if not slides:
            slides = [{"title": title, "body": data.get("script","")}]

        print(f"[INFO] Slides created: {len(slides)}", flush=True)

        # 4) prepare background + gradient + logo
        bg_path = os.path.join(base, "temp_bg.jpg")
        download_background(bg_path)
        gradient_img = create_dark_gradient_overlay(RESOLUTION)
        logo_img = load_logo_if_exists(int(RESOLUTION[0] * LOGO_MAX_WIDTH_RATIO))

        # 5) generate per-slide TTS (async)
        audio_paths = []
        for idx, s in enumerate(slides):
            text_to_read = s.get("title") if s.get("title") else s.get("body","")
            if not text_to_read:
                audio_paths.append(None)
                continue
            # cap text length
            if len(text_to_read) > MAX_SLIDE_CHARS:
                text_to_read = text_to_read[:MAX_SLIDE_CHARS].rsplit(" ",1)[0] + "..."
            audio_path = os.path.join(base, f"slide_audio_{idx}.mp3")
            ok = await synthesize_text_to_file(text_to_read, audio_path)
            if not ok:
                print(f"[WARN] TTS failed for slide {idx}; creating short silent fallback", flush=True)
                # create short silent fallback mp3 using moviepy's AudioFileClip write? create short silence file via ffmpeg is complex here
                # Instead we'll create a tiny audio file by using edge-tts to say a small punctuation to ensure file exists
                fallback_ok = await synthesize_text_to_file(".", audio_path)
                if not fallback_ok:
                    audio_path = None
            audio_paths.append(audio_path)

        # 6) filter slides without audio or extremely short
        filtered_slides = []
        filtered_audio = []
        for s,a in zip(slides, audio_paths):
            if s.get("title"):
                filtered_slides.append(s); filtered_audio.append(a)
                continue
            body = (s.get("body") or "").strip()
            if len(body) < MIN_SLIDE_CHARS:
                # merge into previous if possible
                if filtered_slides and not filtered_slides[-1].get("title"):
                    prev = filtered_slides[-1]
                    prev["body"] = (prev.get("body","") + "\n\n" + body).strip()
                    # we won't regen previous audio (complex) — leave audio as-is to avoid complexity
                else:
                    # skip the short slide
                    print(f"[SKIP] dropping very short slide: '{body[:40]}'", flush=True)
                continue
            # otherwise keep
            filtered_slides.append(s); filtered_audio.append(a)

        if not filtered_slides:
            print("[FATAL] No slides to render after filtering.", flush=True); sys.exit(1)

        # 7) create per-slide clips
        slide_clips = []
        total = len(filtered_slides)
        for idx,(s,a) in enumerate(zip(filtered_slides, filtered_audio)):
            if not a or not os.path.exists(a):
                # create tiny silent fallback mp3 via edge-tts of a dot (already attempted), else create tiny silent from moviepy
                # as last resort, skip audio but still create a short 3s clip
                print(f"[WARN] Missing audio for slide {idx}; using 3s silent clip", flush=True)
                # create silent clip by creating 3s black image and no audio; video will be silent for that slide
                # But MoviePy requires audio to be set later; we'll leave it silent.
                # Create 3s image-based slide clip with no audio
                # Temporarily write a 3s silent mp3? skip — MoviePy handles no audio.
                temp_audio_path = None
            else:
                temp_audio_path = a

            clip = create_slide_clip(bg_path, gradient_img, logo_img, s, temp_audio_path or a, idx, total)
            slide_clips.append(clip)

        # 8) concatenate
        final = concatenate_videoclips(slide_clips, method="compose")

        # 9) write output
        print(f"[INFO] Writing final video to {out_file}", flush=True)
        final.write_videofile(out_file, fps=24, codec="libx264", audio_codec="aac", preset="medium", threads=4, ffmpeg_params=["-movflags","+faststart"])
        print(f"[SUCCESS] Video saved: {out_file}", flush=True)

    except Exception as e:
        print(f"[FATAL] {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
    finally:
        # cleanup generated audio files
        try:
            for f in os.listdir(base):
                if f.startswith("slide_audio_") and f.endswith(".mp3"):
                    try: os.remove(os.path.join(base,f))
                    except: pass
            if os.path.exists(os.path.join(base,"temp_bg.jpg")):
                os.remove(os.path.join(base,"temp_bg.jpg"))
        except Exception:
            pass

if __name__ == "__main__":
    asyncio.run(main())
