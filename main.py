
#!/usr/bin/env python3
"""
Cinematic slide video generator (per-slide TTS) that uses Pillow for text rendering
so ImageMagick / TextClip are not required on CI.

Outputs: generated_videos/<title>_<timestamp>.mp4
Place optional company logo at assets/logo.png (recommended).
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

from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy.editor import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip, concatenate_audioclips
from deep_translator import GoogleTranslator
import edge_tts
import yfinance as yf
from bs4 import BeautifulSoup

# ---------- CONFIG ----------
OUTPUT_FOLDER = "generated_videos"
VIDEO_MODE = "PORTRAIT"  # PORTRAIT or LANDSCAPE

if VIDEO_MODE == "PORTRAIT":
    RESOLUTION = (1080, 1920)
else:
    RESOLUTION = (1920, 1080)

VOICE = "te-IN-ShrutiNeural"
MIN_SLIDE_CHARS = 40
MAX_SLIDE_CHARS = 1200
APP_LOGO_PATH = "assets/logo.png"  # optional; watermark; create assets/ folder and put logo.png there
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # common on ubuntu runners
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
]
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?q=80&w=1080&h=1920&fit=crop",
    "https://images.unsplash.com/photo-1535320903710-d9cf63d4040c?q=80&w=1080&h=1920&fit=crop",
]
WATCHLIST = ["RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS","HINDUNILVR.NS","SBIN.NS","BHARTIARTL.NS","ITC.NS","KOTAKBANK.NS","LICI.NS","LT.NS","AXISBANK.NS","ASIANPAINT.NS","MARUTI.NS"]

# cinematic params (you chose 'C' earlier)
FADE_DURATION = 1.2
PADDING_PER_SLIDE = 0.35
ZOOM_FACTOR = 0.06

# ---------------- utilities ----------------
def load_font(size, prefer_bold=False):
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                continue
    # fallback to PIL default
    return ImageFont.load_default()

def _retry_request(func, retries=3, backoff=1.5):
    last = None
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            last = e
            time.sleep(backoff * (2 ** i))
    raise last

# ---------------- get data ----------------
def get_trending_stock():
    random.shuffle(WATCHLIST)
    for ticker in WATCHLIST[:15]:
        try:
            stock = yf.Ticker(ticker)
            news = getattr(stock, "news", None) or []
            if news:
                latest = news[0]
                title = latest.get('title','Market Update')
                link = latest.get('link') or latest.get('url')
                info = getattr(stock, "info", {}) or {}
                name = info.get('shortName', ticker)
                price = info.get('currentPrice',0)
                mcap = int(info.get('marketCap',0)/10000000) if info.get('marketCap') else 0
                script = f"Breaking update on {name}. Current price {price} rupees. {title}."
                return {"type":"news","title":f"News_{ticker}","name":name,"script":script,"article_link":link}
        except Exception:
            continue
    return None

def get_market_analysis_data():
    import random
    indices=[{"ticker":"^NSEI","name":"Nifty 50"},{"ticker":"^NSEBANK","name":"Bank Nifty"}]
    target = random.choice(indices)
    stock = yf.Ticker(target['ticker'])
    hist = stock.history(period="1mo")
    if hist.shape[0] < 2:
        return None
    cur = hist['Close'].iloc[-1]; prev = hist['Close'].iloc[-2]
    change = cur - prev
    pct = (change/prev)*100
    trend = "bullish" if change>0 else "bearish"
    script = f"{target['name']} shows a {trend} move of {abs(round(pct,2))}% today."
    return {"type":"technical","title":f"Technical_{target['name']}","name":target['name'],"script":script,"article_link":None}

# ---------------- article scraping ----------------
def fetch_article_text(url):
    if not url:
        return None
    try:
        headers = {"User-Agent":"Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        paras=[]
        article = soup.find("article")
        if article:
            for p in article.find_all("p"):
                t=p.get_text(strip=True)
                if t: paras.append(t)
        if not paras:
            candidates = soup.find_all(["div","section"])
            best=None; best_count=0
            for c in candidates:
                ps = c.find_all("p")
                if len(ps) > best_count:
                    best_count = len(ps); best = c
            if best and best_count>0:
                for p in best.find_all("p"):
                    t=p.get_text(strip=True)
                    if t: paras.append(t)
        if not paras:
            meta = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name":"description"})
            if meta and meta.get("content"):
                paras = [meta.get("content").strip()]
        if not paras:
            ps = soup.find_all("p")
            for p in ps[:10]:
                t=p.get_text(strip=True)
                if t: paras.append(t)
        if not paras:
            return None
        full = "\n\n".join(paras)
        if len(full) > MAX_SLIDE_CHARS*10:
            full = full[:MAX_SLIDE_CHARS*10].rsplit(" ",1)[0]+"..."
        return full
    except Exception:
        return None

# ---------------- split into slides & merge short ----------------
def split_text_into_slides(text, title=None, approx_chars=700):
    if not text:
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    slides=[]
    if title:
        slides.append({"title":title,"body":""})
    cur=[]; cur_len=0
    for p in paras:
        pl = len(p)
        if cur_len + pl + 2 <= approx_chars:
            cur.append(p); cur_len+=pl+2
        else:
            slides.append({"title":None,"body":"\n\n".join(cur)})
            cur=[p]; cur_len=pl+2
    if cur:
        slides.append({"title":None,"body":"\n\n".join(cur)})

    # merge/skip short slides
    cleaned=[]
    for s in slides:
        body = (s.get("body") or "").strip()
        if body and len(body) < MIN_SLIDE_CHARS:
            if cleaned and not cleaned[-1].get("title"):
                cleaned[-1]["body"] = (cleaned[-1].get("body","") + "\n\n" + body).strip()
            else:
                # try to attach to next later: for simplicity attach to previous or skip
                if cleaned:
                    cleaned[-1]["body"] = (cleaned[-1].get("body","") + "\n\n" + body).strip()
                else:
                    # single short slide -> keep as title slide or skip
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
        print("[WARN] TTS failed for slide:", e)
        # fallback: create a short silent mp3 using moviepy AudioClip
        from moviepy.audio.AudioClip import AudioClip
        silence = AudioClip(lambda t: 0*t, duration=3.0).set_fps(44100)
        silence.write_audiofile(out_path, fps=44100, codec="mp3", verbose=False, logger=None)
        return False

# ---------------- background & gradient & watermark ----------------
def download_background(path):
    for url in FALLBACK_IMAGES:
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200 and r.headers.get("Content-Type","").startswith("image/"):
                with open(path,"wb") as f: f.write(r.content)
                return True
        except Exception:
            continue
    # create solid
    img = Image.new("RGB", RESOLUTION, (18,18,18))
    img.save(path, quality=90)
    return True

def add_dark_gradient_and_logo(input_image_path, out_path, logo_path=None):
    # open bg, add dark gradient overlay and optional logo watermark
    bg = Image.open(input_image_path).convert("RGBA")
    w,h = bg.size

    # create vertical gradient alpha (top lighter, bottom darker)
    gradient = Image.new("L", (1,h))
    for y in range(h):
        # top 0 -> alpha 0.2*255, bottom -> 0.7*255 (darker overlay)
        a = int( (0.2 + 0.5 * (y / h)) * 255 )
        gradient.putpixel((0,y), a)
    alpha = gradient.resize((w,h))
    black = Image.new("RGBA", (w,h), (6,6,8,255))
    black.putalpha(alpha)

    composed = Image.alpha_composite(bg, black)

    # add soft vignette
    vign = Image.new("L", (w,h))
    for y in range(h):
        for x in range(w):
            # distance from center
            dx = (x - w/2)/(w/2)
            dy = (y - h/2)/(h/2)
            d = (dx*dx + dy*dy)**0.5
            # vignette value
            v = int( max(0, min(255, (d*1.2)*255)) )
            vign.putpixel((x,y), v)
    vign_blur = vign.filter(ImageFilter.GaussianBlur(radius=50))
    black2 = Image.new("RGBA",(w,h),(0,0,0))
    black2.putalpha(vign_blur)
    final = Image.alpha_composite(composed, black2)

    # add logo (bottom-right)
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            # scale logo to ~12% width
            lw = int(w * 0.12)
            lh = int(logo.size[1] * (lw / logo.size[0]))
            logo = logo.resize((lw, lh), Image.LANCZOS)
            # paste with 85% opacity
            logo_mask = logo.split()[3].point(lambda p: p * 0.85)
            final.paste(logo, (w - lw - 40, h - lh - 40), mask=logo_mask)
        except Exception:
            pass

    final.convert("RGB").save(out_path, quality=92)

# ---------------- render text to image using PIL ----------------
def render_text_image(title_text, body_text, out_path, title_font_size=86, body_font_size=44):
    # create a blank RGBA canvas and draw title/body
    w,h = RESOLUTION
    canvas = Image.new("RGBA", (w,h), (0,0,0,0))
    draw = ImageDraw.Draw(canvas)

    # fonts
    title_font = load_font(title_font_size)
    body_font = load_font(body_font_size)

    # title (centered near top)
    y_cursor = int(h * 0.12)
    if title_text:
        # wrap title
        max_title_width = int(w * 0.84)
        # naive wrap by characters using textwrap (works fine for most)
        wrapped_title = textwrap.fill(title_text, width=30)
        # measure and draw
        lines = wrapped_title.splitlines()
        for line in lines:
            tw, th = draw.textsize(line, font=title_font)
            draw.text(((w - tw) // 2, y_cursor), line, font=title_font, fill=(255,255,255,255))
            y_cursor += th + 12
        y_cursor += 18

    # body (left aligned, wrapped)
    if body_text:
        left = int(w * 0.07)
        right = int(w * 0.07)
        box_w = w - left - right
        # wrap body_text into lines approximate by characters per line
        approx_chars_per_line = max(30, int(box_w / (body_font_size * 0.45)))
        wrapped_body = textwrap.fill(body_text, width=approx_chars_per_line)
        lines = wrapped_body.splitlines()
        # ensure bottom margin
        max_lines = int((h - y_cursor - 150) / (body_font_size + 6))
        lines = lines[:max_lines]
        for line in lines:
            draw.text((left, y_cursor), line, font=body_font, fill=(240,240,240,255))
            wline, hline = draw.textsize(line, font=body_font)
            y_cursor += hline + 8

    # save
    canvas.convert("RGB").save(out_path, quality=92)

# ---------------- create slide clip using generated image + audio ----------------
def create_slide_clip_from_image(image_path, audio_path, idx, total):
    # load audio to get duration
    audio_clip = AudioFileClip(audio_path)
    base_dur = audio_clip.duration
    duration = max(2.5, base_dur + PADDING_PER_SLIDE)

    img_clip = ImageClip(image_path).set_duration(duration)
    # Ken-Burns zoom: using resize with lambda
    try:
        img_clip = img_clip.resize(lambda t: 1.0 + ZOOM_FACTOR * (t / duration)).set_duration(duration)
    except Exception:
        img_clip = img_clip.set_duration(duration)

    # small footer
    footer_text = f"{idx+1}/{total}"
    # we draw footer via another small ImageClip created by PIL
    footer_img = Image.new("RGBA", (400,80), (0,0,0,0))
    draw = ImageDraw.Draw(footer_img)
    ffont = load_font(28)
    tw, th = draw.textsize(footer_text, font=ffont)
    draw.text((400-tw-10, 10), footer_text, font=ffont, fill=(230,230,230,200))
    footer_img_path = image_path + f".footer.{idx}.png"
    footer_img.convert("RGB").save(footer_img_path, quality=80)
    footer_clip = ImageClip(footer_img_path).set_duration(duration).set_position(("right", RESOLUTION[1]-90))

    comp = CompositeVideoClip([img_clip, footer_clip], size=RESOLUTION).set_duration(duration)
    # cinematic fades
    comp = comp.fx(lambda clip: clip.crossfadein(FADE_DURATION)).fx(lambda clip: clip.crossfadeout(FADE_DURATION))
    # set audio (pad/pad silence)
    if audio_clip.duration < duration:
        silence = AudioFileClip(os.path.join(os.path.dirname(__file__), "silent_placeholder.mp3")) if False else None
        # simple silence using moviepy
        from moviepy.audio.AudioClip import AudioClip
        silence = AudioClip(lambda t: 0*t, duration=(duration - audio_clip.duration)).set_fps(44100)
        audio_final = concatenate_audioclips([audio_clip, silence])
    else:
        audio_final = audio_clip.subclip(0, duration)
    comp = comp.set_audio(audio_final)
    # cleanup footer temp file after it's used? leave for now - will be cleaned at end
    return comp

# ---------------- main flow ----------------
async def main():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    base = os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bg_path = os.path.join(base, "temp_bg.jpg")
    bg_gradient_path = os.path.join(base, "temp_bg_grad.jpg")

    try:
        data = get_trending_stock()
        if not data:
            data = get_market_analysis_data()
        if not data:
            print("[CRITICAL] No data fetched; exiting.")
            sys.exit(1)

        title = data.get("name") or data.get("title")
        final_filename = f"{data.get('title')}_{timestamp}.mp4"
        out_path = os.path.join(base, OUTPUT_FOLDER, final_filename)

        # get article text
        article_text = None
        link = data.get("article_link")
        if link:
            article_text = fetch_article_text(link)
        if not article_text:
            article_text = data.get("script") or f"{title} - Market update."

        # split into slides
        slides = split_text_into_slides(article_text, title=title, approx_chars=700)
        if not slides:
            slides = [{"title": title, "body": data.get("script","")}]

        # download background and overlay gradient and watermark
        download_background(bg_path)
        logo_path = APP_LOGO_PATH if os.path.exists(APP_LOGO_PATH) else None
        add_dark_gradient_and_logo(bg_path, bg_gradient_path, logo_path=logo_path)

        # make per-slide images and per-slide audio
        slide_image_paths = []
        slide_audio_paths = []
        for idx, s in enumerate(slides):
            # build text
            slug_title = s.get("title")
            body = s.get("body", "")
            # skip extremely short slides (should have already merged but double-check)
            if slug_title is None and len(body.strip()) < MIN_SLIDE_CHARS:
                print("[SKIP] skipping tiny slide:", body[:40])
                continue

            # image path
            img_path = os.path.join(base, f"slide_img_{idx}.jpg")
            # render text on top of the pre-made gradient background: we will composite bg+text
            # approach: open bg_gradient_path, paste text image on top
            rendered_text_img = os.path.join(base, f"slide_text_{idx}.png")
            render_text_image(slug_title, body, rendered_text_img, title_font_size=86, body_font_size=44)

            # composite bg + rendered text centered
            bg = Image.open(bg_gradient_path).convert("RGB")
            overlay = Image.open(rendered_text_img).convert("RGBA")
            bg.paste(overlay, (0,0), overlay)
            bg.save(img_path, quality=92)

            slide_image_paths.append(img_path)

            # tts audio file
            to_read = slug_title if slug_title else body
            if not to_read or len(to_read.strip()) == 0:
                # create a short silent mp3
                silent_path = os.path.join(base, f"slide_silent_{idx}.mp3")
                from moviepy.audio.AudioClip import AudioClip
                silence = AudioClip(lambda t: 0*t, duration=2.5).set_fps(44100)
                silence.write_audiofile(silent_path, fps=44100, codec="mp3", verbose=False, logger=None)
                slide_audio_paths.append(silent_path)
            else:
                audio_path = os.path.join(base, f"slide_audio_{idx}.mp3")
                await synthesize_slide_tts(to_read, audio_path)
                slide_audio_paths.append(audio_path)

        if not slide_image_paths:
            print("[CRITICAL] No slide images created; exiting.")
            sys.exit(1)

        # create clips
        clips=[]
        total = len(slide_image_paths)
        for idx, (img_p, aud_p) in enumerate(zip(slide_image_paths, slide_audio_paths)):
            clip = create_slide_clip_from_image(img_p, aud_p, idx, total)
            clips.append(clip)

        final = concatenate_videoclips(clips, method="compose")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        final.write_videofile(out_path, fps=24, codec="libx264", audio_codec="aac", preset="medium", threads=4, ffmpeg_params=["-movflags","+faststart"])
        print("[SUCCESS] Video created:", out_path)

    except Exception as e:
        print("[FATAL]", e)
        traceback.print_exc()
        sys.exit(1)
    finally:
        # cleanup temp files created in repo root
        for fname in os.listdir(base):
            if fname.startswith("slide_img_") or fname.startswith("slide_text_") or fname.startswith("slide_audio_") or fname.startswith("slide_silent_") or fname.startswith("temp_bg"):
                try: os.remove(os.path.join(base, fname))
                except: pass

if __name__ == "__main__":
    asyncio.run(main())
