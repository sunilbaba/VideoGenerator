#!/usr/bin/env python3
"""
CI-friendly slides video generator:
 - Uses PIL to render text slides (no ImageMagick/TextClip)
 - Per-slide TTS (edge-tts) in Telugu
 - Company logo watermark (logo.png in repo root) - optional
 - Dark gradient overlay for readability
 - Ken-Burns zoom, fade-in/out cinematic transitions
 - Outputs MP4 to generated_videos/
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

# third-party libs (install in requirements.txt)
import yfinance as yf
import edge_tts
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
from moviepy.video.fx.all import fadein, fadeout
from PIL import Image, ImageDraw, ImageFont
from deep_translator import GoogleTranslator
from bs4 import BeautifulSoup

# ========== CONFIG ==========
OUTPUT_FOLDER = "generated_videos"
VIDEO_MODE = "PORTRAIT"   # "PORTRAIT" or "LANDSCAPE"
if VIDEO_MODE == "PORTRAIT":
    RESOLUTION = (1080, 1920)
else:
    RESOLUTION = (1920, 1080)

VOICE = "te-IN-ShrutiNeural"
MIN_SLIDE_CHARS = 40
MAX_SLIDE_CHARS = 1200
PADDING_PER_SLIDE = 0.35   # seconds padding per slide
FADE_DURATION = 1.2
ZOOM_FACTOR = 0.06         # 6% zoom during slide
APP_LOGO_FILENAME = "logo.png"  # optional logo in repo root
FONT_PRIMARY = None        # will be auto-detected
FONT_BOLD = None

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

# ========================== Helpers ==========================
def log(*args, **kwargs):
    print(*args, **kwargs, flush=True)

def _retry_request(func, retries=3, backoff=1.5):
    last = None
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            last = e
            sleep_t = backoff * (2 ** i)
            log(f"[RETRY] attempt {i+1}/{retries} failed: {e} — sleeping {sleep_t:.1f}s")
            time.sleep(sleep_t)
    raise last

# ========================== Fonts ==========================
def find_font_paths():
    """
    Try common DejaVu fonts on ubuntu runners. Return (regular_path, bold_path) or (None, None).
    """
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ]
    reg = None
    bold = None
    for p in candidates:
        if os.path.exists(p):
            if "Bold" in os.path.basename(p) or "-B" in os.path.basename(p) or "Ubuntu-B" in p:
                if not bold:
                    bold = p
            else:
                if not reg:
                    reg = p
    return reg, bold

def load_fonts():
    global FONT_PRIMARY, FONT_BOLD
    reg, bold = find_font_paths()
    try:
        if reg:
            FONT_PRIMARY = ImageFont.truetype(reg, size=48)
            log(f"[INFO] Loaded primary font: {reg}")
        else:
            FONT_PRIMARY = ImageFont.load_default()
            log("[WARN] Default PIL font loaded (no DejaVu found).")
        if bold:
            FONT_BOLD = ImageFont.truetype(bold, size=72)
            log(f"[INFO] Loaded bold font: {bold}")
        else:
            # try using primary with larger size as fallback
            FONT_BOLD = ImageFont.truetype(reg, size=72) if reg else ImageFont.load_default()
    except Exception as e:
        log("[WARN] Font load failed, using defaults:", e)
        FONT_PRIMARY = ImageFont.load_default()
        FONT_BOLD = ImageFont.load_default()

# ========================== Data selection ==========================
def get_trending_stock():
    log("[*] Scanning watchlist for news...")
    random.shuffle(WATCHLIST)
    for ticker in WATCHLIST[:15]:
        try:
            stock = yf.Ticker(ticker)
            news = getattr(stock, "news", None) or []
            if news and len(news) > 0:
                latest = news[0]
                title = latest.get("title", "Market Update")
                publisher = latest.get("publisher", "News")
                link = latest.get("link") or latest.get("url")
                info = getattr(stock, "info", {}) or {}
                name = info.get("shortName", ticker)
                price = info.get("currentPrice", 0)
                mcap = int(info.get("marketCap", 0) / 10000000) if info.get("marketCap") else 0
                script = f"Breaking Stock Market Update on {name}. Price: {price} rupees. {title}. Market cap: {mcap} crore."
                return {"type":"news","title":f"News_{ticker}","name":name,"script":script,"article_link":link}
        except Exception as e:
            log(f"[WARN] error checking {ticker}: {e}")
            continue
    return None

def get_market_analysis_data():
    log("[*] No news found, using market analysis fallback.")
    indices = [{"ticker":"^NSEI","name":"Nifty 50"},{"ticker":"^NSEBANK","name":"Bank Nifty"}]
    target = random.choice(indices)
    try:
        stock = yf.Ticker(target["ticker"])
        hist = stock.history(period="1mo")
        if hist.shape[0] < 2:
            raise ValueError("not enough history")
        current = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2]
        change = current - prev
        pct = (change/prev)*100
        trend = "bullish" if change>0 else "bearish"
        script = f"{target['name']} shows a {trend} move of {abs(round(pct,2))}% today at {int(current)} points."
        return {"type":"technical","title":f"Technical_{target['name']}","name":target['name'],"script":script,"article_link":None}
    except Exception as e:
        log("[ERROR] market analysis failed:", e)
        return None

# ========================== Scrape article ==========================
def fetch_article_text(url):
    if not url:
        return None
    try:
        log(f"[*] Fetching article: {url}")
        headers = {"User-Agent":"Mozilla/5.0 (compatible; Bot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        paragraphs = []
        article_tag = soup.find("article")
        if article_tag:
            for p in article_tag.find_all("p"):
                t = p.get_text(strip=True)
                if t:
                    paragraphs.append(t)
        if not paragraphs:
            # heuristic: pick largest div with many <p>
            candidates = soup.find_all(["div","section"])
            best = None
            best_count = 0
            for c in candidates:
                ps = c.find_all("p")
                if len(ps) > best_count:
                    best_count = len(ps)
                    best = c
            if best and best_count>0:
                for p in best.find_all("p"):
                    t = p.get_text(strip=True)
                    if t:
                        paragraphs.append(t)
        if not paragraphs:
            meta = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name":"description"})
            if meta and meta.get("content"):
                paragraphs = [meta.get("content").strip()]
        if not paragraphs:
            ps = soup.find_all("p")
            for p in ps[:10]:
                t = p.get_text(strip=True)
                if t:
                    paragraphs.append(t)
        if not paragraphs:
            log("[WARN] Could not extract article paragraphs.")
            return None
        full = "\n\n".join(paragraphs)
        if len(full) > MAX_SLIDE_CHARS*10:
            full = full[:MAX_SLIDE_CHARS*10].rsplit(" ",1)[0] + "..."
        return full
    except Exception as e:
        log("[WARN] fetch_article_text failed:", e)
        return None

# ========================== Split slides & short slide handling ==========================
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
        plen = len(p)
        if cur_len + plen + 2 <= approx_chars:
            cur.append(p); cur_len += plen + 2
        else:
            slides.append({"title": None, "body": "\n\n".join(cur)})
            cur = [p]; cur_len = plen + 2
    if cur:
        slides.append({"title": None, "body": "\n\n".join(cur)})
    # merge/skip very short slides
    out = []
    for s in slides:
        body = (s.get("body") or "").strip()
        if len(body) < MIN_SLIDE_CHARS:
            if out and not out[-1].get("title"):
                # merge to previous
                out[-1]["body"] = (out[-1].get("body","") + "\n\n" + body).strip()
            else:
                # if first slide is short, keep it (title may exist) else drop
                if s.get("title"):
                    out.append(s)
                else:
                    # attempt to append to next by making it pending: just append now
                    out.append(s)
        else:
            out.append(s)
    if len(out) > 14:
        return split_text_into_slides(text, title=title, approx_chars=1200)
    return out

# ========================== Background / gradient / logo ==========================
def download_background(path):
    for url in FALLBACK_IMAGES:
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            ctype = r.headers.get("Content-Type","")
            if ctype.startswith("image/"):
                with open(path,"wb") as f: f.write(r.content)
                return True
        except Exception:
            continue
    # fallback: solid color
    img = Image.new("RGB", RESOLUTION, (12,12,12))
    img.save(path, quality=90)
    return True

def apply_dark_gradient(img, top_opacity=220, bottom_opacity=90):
    """
    Overlay a vertical dark gradient to help text readability.
    top_opacity, bottom_opacity in 0-255 (alpha)
    """
    w,h = img.size
    gradient = Image.new("L", (1,h))
    for y in range(h):
        # linear interpolation
        a = int(top_opacity + (bottom_opacity - top_opacity) * (y / h))
        gradient.putpixel((0,y), max(0, min(255,a)))
    alpha = gradient.resize((w,h))
    black = Image.new("RGBA", (w,h), color=(0,0,0,0))
    black.putalpha(alpha)
    base = img.convert("RGBA")
    combined = Image.alpha_composite(base, black)
    return combined.convert("RGB")

def add_logo_watermark(img, logo_path, size_ratio=0.12, margin=36, opacity=200):
    """
    Paste logo at top-left with margin. size_ratio relative to width.
    """
    try:
        logo = Image.open(logo_path).convert("RGBA")
        w,h = img.size
        target_w = int(w * size_ratio)
        # maintain aspect
        aspect = logo.width / logo.height
        target_h = int(target_w / aspect)
        logo = logo.resize((target_w, target_h), Image.LANCZOS)
        # apply opacity
        if opacity < 255:
            alpha = logo.split()[3].point(lambda p: p * (opacity/255.0))
            logo.putalpha(alpha)
        img_rgba = img.convert("RGBA")
        img_rgba.paste(logo, (margin, margin), logo)
        return img_rgba.convert("RGB")
    except Exception as e:
        log("[WARN] add_logo_watermark failed:", e)
        return img

# ========================== Render slide image with PIL ==========================
def render_slide_image(slide, out_path, logo_path=None):
    """
    Draws a slide image using PIL and saves PNG to out_path.
    slide = {'title':..., 'body':...}
    """
    W,H = RESOLUTION
    # background base image - we create a simple neutral gradient background
    base = Image.new("RGB", (W,H), (18,18,18))
    draw = ImageDraw.Draw(base)

    # optionally use a background image if we saved one under bg.png (downloaded earlier)
    bg_file = "bg_image.jpg"
    if os.path.exists(bg_file):
        try:
            bg = Image.open(bg_file).convert("RGB")
            bg = bg.resize((W,H), Image.LANCZOS)
            base = bg
            draw = ImageDraw.Draw(base)
        except Exception:
            pass

    # overlay dark gradient for readability
    base = apply_dark_gradient(base, top_opacity=200, bottom_opacity=60)
    draw = ImageDraw.Draw(base)

    # draw content (title or body)
    padding_x = 80
    usable_w = W - padding_x*2

    if slide.get("title"):
        # Title card
        title_text = slide["title"]
        font = FONT_BOLD if FONT_BOLD else FONT_PRIMARY
        # adaptive size: try to fit in two lines
        fontsize = 100
        # find largest fontsize that fits roughly
        for sz in (100, 90, 80, 72, 60, 48):
            f = ImageFont.truetype(font.path, sz) if hasattr(font, "path") else ImageFont.load_default()
            # measure text wrapped to two lines
            lines = textwrap.wrap(title_text, width=24)
            w_needed = max([draw.textsize(line, font=f)[0] for line in lines]) if lines else 0
            if w_needed < usable_w:
                fontsize = sz
                break
        try:
            f = ImageFont.truetype(font.path, fontsize) if hasattr(font, "path") else font
        except Exception:
            f = FONT_BOLD if FONT_BOLD else FONT_PRIMARY
        # center text vertically a bit above middle
        lines = textwrap.wrap(title_text, width=24)
        y = int(H*0.28)
        for line in lines:
            w_t, h_t = draw.textsize(line, font=f)
            x = int((W - w_t)/2)
            draw.text((x, y), line, font=f, fill=(255,255,255))
            y += h_t + 8
    else:
        # Body card
        body_text = slide.get("body","")
        font = FONT_PRIMARY
        # choose fontsize by checking text length
        fontsize = 44 if VIDEO_MODE=="PORTRAIT" else 36
        try:
            if hasattr(font, "path"):
                f = ImageFont.truetype(font.path, fontsize)
            else:
                f = font
        except Exception:
            f = FONT_PRIMARY
        # wrap text to fit usable_w (determine chars per line heuristically)
        avg_char_width = f.getsize("A")[0] if hasattr(f, "getsize") else 10
        chars_per_line = max(30, int(usable_w / (avg_char_width+0.1)))
        wrapped = textwrap.fill(body_text, width=chars_per_line)
        # draw starting y slightly lower top
        y = int(H*0.18)
        lines = wrapped.split("\n")
        for line in lines:
            w_t, h_t = draw.textsize(line, font=f)
            x = int((W - w_t)/2)
            draw.text((x, y), line, font=f, fill=(240,240,240))
            y += h_t + 8

    # logo watermark
    if logo_path and os.path.exists(logo_path):
        try:
            base = add_logo_watermark(base, logo_path, size_ratio=0.12, margin=36, opacity=210)
        except Exception as e:
            log("[WARN] watermark failed:", e)

    # Save PNG
    base.save(out_path, format="PNG", optimize=True)
    return out_path

# ========================== Per-slide TTS ==========================
async def synthesize_slide_tts(text, out_path):
    """
    Translate to Telugu and synthesize with edge-tts.
    """
    try:
        telugu = GoogleTranslator(source='auto', target='te').translate(text)
        comm = edge_tts.Communicate(telugu, VOICE)
        await comm.save(out_path)
        return True
    except Exception as e:
        log("[ERROR] synthesize_slide_tts failed:", e)
        traceback.print_exc()
        return False

# ========================== Compose clips ==========================
def make_zoomed_imageclip(img_path, duration):
    """
    Return ImageClip that applies a gentle zoom (moviepy resize with function)
    """
    clip = ImageClip(img_path).set_duration(duration)
    try:
        clip = clip.resize(lambda t: 1.0 + ZOOM_FACTOR * (t / duration))
    except Exception:
        clip = clip.set_duration(duration)
    return clip

# ========================== Main flow ==========================
async def main():
    load_fonts()
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    base_dir = os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bg_file = os.path.join(base_dir, "bg_image.jpg")
    logo_path = os.path.join(base_dir, APP_LOGO_FILENAME)
    try:
        # 1. topic
        data = get_trending_stock()
        if not data:
            data = get_market_analysis_data()
        if not data:
            log("[CRITICAL] no data found. exiting.")
            sys.exit(1)
        title = data.get("name") or data.get("title")
        out_filename = f"{data.get('title')}_{timestamp}.mp4"
        out_path = os.path.join(base_dir, OUTPUT_FOLDER, out_filename)

        # 2. article text
        article_text = None
        link = data.get("article_link")
        if link:
            if link.startswith("/"):
                link = None
            else:
                article_text = fetch_article_text(link)
        if not article_text:
            article_text = data.get("script") or f"{title} - market update."

        # 3. slides
        slides = split_text_into_slides(article_text, title=title, approx_chars=700)
        if not slides:
            slides = [{"title": title, "body": data.get("script","")}]

        log(f"[*] Slides created: {len(slides)}")

        # 4. download bg if possible
        download_background(bg_file)

        # 5. generate per-slide images & audio
        slide_images = []
        slide_audios = []
        for idx, s in enumerate(slides):
            img_path = os.path.join(base_dir, f"slide_{idx}.png")
            # render slide image with gradient + optional footer + watermark
            render_slide_image(s, img_path, logo_path if os.path.exists(logo_path) else None)
            slide_images.append(img_path)
            # prepare text to speak: prefer title for title slides, else body
            to_speak = s.get("title") if s.get("title") else s.get("body","")
            if not to_speak or len(to_speak.strip())==0:
                # create a short silent audio as fallback (3 seconds)
                audio_file = os.path.join(base_dir, f"slide_{idx}.mp3")
                silence = AudioFileClip(make_silent_audio(3.0))
                # but making silence via moviepy is heavier; instead create empty file using edge-tts with a dot? simpler: use small TTS
                ok = await synthesize_slide_tts(" ", audio_file)
                slide_audios.append(audio_file)
                continue
            # cap
            if len(to_speak) > MAX_SLIDE_CHARS:
                to_speak = to_speak[:MAX_SLIDE_CHARS].rsplit(" ",1)[0] + "..."
            audio_file = os.path.join(base_dir, f"slide_{idx}.mp3")
            ok = await synthesize_slide_tts(to_speak, audio_file)
            if not ok:
                # fallback silent
                log(f"[WARN] TTS failed for slide {idx}, creating small silent mp3.")
                # create silent mp3 using ffmpeg via moviepy is heavy; as fallback, create tiny TTS of '.' so there is an audio file
                _ = await synthesize_slide_tts(".", audio_file)
            slide_audios.append(audio_file)

        # 6. create clips (ImageClip + set_audio using each slide's audio duration + padding)
        clips = []
        for idx, (img_p, aud_p) in enumerate(zip(slide_images, slide_audios)):
            # get audio duration using AudioFileClip
            audio_clip = None
            try:
                audio_clip = AudioFileClip(aud_p)
                audio_dur = audio_clip.duration
            except Exception as e:
                log("[WARN] could not load audio clip, defaulting to 4s:", e)
                audio_dur = 4.0
            duration = max(3.5, audio_dur + PADDING_PER_SLIDE)
            img_clip = make_zoomed_imageclip(img_p, duration)
            # fade
            img_clip = fadein(img_clip, FADE_DURATION)
            img_clip = fadeout(img_clip, FADE_DURATION)
            # set audio
            try:
                aclip = AudioFileClip(aud_p)
                # pad audio if shorter than duration
                if aclip.duration < duration:
                    # create silence using numpy? simpler: keep audio as-is; video duration will be duration, moviepy will handle mismatch
                    pass
                img_clip = img_clip.set_audio(aclip)
            except Exception as e:
                log("[WARN] set audio failed for slide", idx, e)
            clips.append(img_clip)

        if not clips:
            log("[CRITICAL] no clips created.")
            sys.exit(1)

        # 7. concatenate (method compose keeps size)
        final = concatenate_videoclips(clips, method="compose")

        # 8. write file
        log(f"[*] Writing final video to {out_path} ...")
        final.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", preset="medium", threads=4, ffmpeg_params=["-movflags"," +faststart"])
        log("[SUCCESS] Video saved:", out_path)

    except Exception as e:
        log("[FATAL] Error during generation:", e)
        traceback.print_exc()
        sys.exit(1)
    finally:
        # cleanup temp slide images and audios
        try:
            for fname in os.listdir(base_dir):
                if fname.startswith("slide_") and (fname.endswith(".png") or fname.endswith(".mp3")):
                    try: os.remove(os.path.join(base_dir, fname))
                    except: pass
            if os.path.exists(bg_file):
                try: os.remove(bg_file)
                except: pass
        except Exception:
            pass

# small helper to create silent audio (used earlier only if needed)
def make_silent_audio(duration):
    """
    Create a temporary silent audio file path using ffmpeg would be ideal.
    But moviepy AudioClip requires a function; we avoided heavy usage.
    If needed later refine.
    """
    # Not used in main flow - kept for future
    return None

if __name__ == "__main__":
    asyncio.run(main())
