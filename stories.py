"""
Clarity Lab — Instagram Stories Pipeline
Runs day after main pipeline (Tue/Thu/Sat 9:00 UTC)
Takes last published topic from topics.csv
Creates vertical 9:16 Story image + publishes to Instagram
"""

import os
import csv
import re
import tempfile
import requests
import logging
from datetime import datetime
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import cloudinary
import cloudinary.uploader

from http_utils import HttpClient
from runtime_config import FeatureFlags
from structured_logging import get_logger, log_event

# ============================================================
# CONFIG
# ============================================================

OPENAI_API_KEY     = os.environ["OPENAI_API_KEY"]
CLOUDINARY_CLOUD   = os.environ["CLOUDINARY_CLOUD_NAME"]
CLOUDINARY_KEY     = os.environ["CLOUDINARY_API_KEY"]
CLOUDINARY_SECRET  = os.environ["CLOUDINARY_API_SECRET"]
IG_USER_ID         = os.environ["IG_USER_ID"]
IG_TOKEN           = os.environ["IG_TOKEN"]

TOPICS_FILE        = "topics.csv"
LOGO_DARK          = "config/logo_dark.png"
LOGO_WHITE         = "config/logo_white.png"

FLAGS = FeatureFlags.from_env()
LOGGER = get_logger("stories")
HTTP = HttpClient.from_flags(FLAGS, LOGGER)

# Brand colors
BRAND_CREAM        = (244, 241, 236)   # #F4F1EC
BRAND_DARK         = (31, 31, 31)      # #1F1F1F
BRAND_SAGE         = (168, 173, 160)   # #A8ADA0

# Story types in rotation
STORY_TYPES = ["question", "observation", "invitation"]

# ============================================================
# HELPERS
# ============================================================

def clean_markdown(text):
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def get_font(size, serif=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf" if serif else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if serif else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()

def get_region_brightness(img, box):
    region = img.crop(box).convert("L")
    return float(np.array(region).mean())

def wrap_text_by_width(draw, text, font, max_width):
    words = text.replace("\n", " ").split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def draw_centered_lines(draw, lines, center_x, y, font, fill, line_gap=14):
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]
        draw.text((center_x - line_w / 2, y), line, font=font, fill=fill)
        y += line_h + line_gap
    return y

# ============================================================
# STEP 1: Get last published topic
# ============================================================

def get_last_published_topic():
    rows = []
    with open(TOPICS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # Find last published
    published = [r for r in rows if r.get("Status", "").strip().lower() == "published"]

    if not published:
        raise Exception("No published topics found in topics.csv")

    last = published[-1]
    index = rows.index(last)
    print(f"[STORY] Using last published topic: {last['Topic / Working Title']}")
    return index, last

# ============================================================
# STEP 2: Generate Story text via GPT
# ============================================================

def get_story_type(index):
    return STORY_TYPES[index % len(STORY_TYPES)]

def generate_story_text(topic_row, story_type):
    client = OpenAI(api_key=OPENAI_API_KEY, max_retries=FLAGS.http_max_retries, timeout=FLAGS.http_timeout_seconds)

    type_instructions = {
        "question": """
Write one powerful question for an Instagram Story.
The question should:
- Feel personally recognizable
- Not have an obvious answer
- Create a moment of pause
- Connect to the topic without explaining it
- Be 10-20 words maximum
- End with a question mark
Format: just the question, nothing else.
""",
        "observation": """
Write one quiet observation for an Instagram Story.
The observation should:
- Feel like something the reader already knows but hasn't named
- Be calm, precise, non-judgmental
- Not give advice or explain
- Be 15-25 words maximum
- Feel like a mirror, not a lesson
Format: just the observation, nothing else.
""",
        "invitation": """
Write one soft invitation for an Instagram Story.
The invitation should:
- Connect the topic to what Clarity Lab offers
- Feel warm, not salesy
- End with: "This is what Clarity Lab was built for."
- Be 20-30 words maximum before the final line
Format: the invitation text, then on a new line: "This is what Clarity Lab was built for."
"""
    }

    prompt = f"""
You are writing for Clarity Lab — a reflective AI assistant brand.
Tone: quiet, precise, human, non-marketing, editorial.

Topic: {topic_row['Topic / Working Title']}
Core observation: {topic_row['Core Observation']}

{type_instructions[story_type]}
"""

    print(f"[GPT] Generating Story text (type: {story_type})...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0.7
    )

    text = response.choices[0].message.content.strip()
    print(f"[GPT] Story text: {text[:80]}...")
    return text

# ============================================================
# STEP 3: Create vertical Story image (9:16)
# ============================================================

def create_story_image(master_image_path, story_text, story_type, topic_row):
    """
    Creates a 1080x1920 (9:16) Story image.
    Uses master image as center visual, brand color background,
    logo top, text center/bottom.
    """
    print("[PILLOW] Creating Story image (9:16)...")

    SW, SH = 1080, 1920  # Story dimensions

    # Create brand background
    story_img = Image.new("RGB", (SW, SH), BRAND_CREAM)

    # Load and place master image in center (square, takes ~55% of width)
    master = Image.open(master_image_path).convert("RGB")
    img_size = int(SW * 0.88)
    master = master.resize((img_size, img_size), Image.LANCZOS)

    img_x = (SW - img_size) // 2
    img_y = int(SH * 0.18)
    story_img.paste(master, (img_x, img_y))

    draw = ImageDraw.Draw(story_img)

    # Subtle top and bottom brand areas
    # Top bar
    for y in range(0, img_y):
        alpha = int(255 * (1 - y / img_y)) if img_y > 0 else 255
        # Just use brand cream - already set

    # Bottom gradient overlay on image
    grad_start = img_y + img_size - int(img_size * 0.35)
    for y in range(grad_start, img_y + img_size):
        t = (y - grad_start) / (img_y + img_size - grad_start)
        alpha = int(180 * t)
        r = int(BRAND_CREAM[0] * t + master.getpixel((img_size//2, min(y - img_y, img_size-1)))[0] * (1-t))
        draw.line((img_x, y, img_x + img_size, y), fill=(*BRAND_CREAM, alpha))

    # Re-draw with proper alpha composite
    overlay = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)

    # Bottom gradient on image area
    for y in range(grad_start, img_y + img_size):
        t = (y - grad_start) / max(1, img_y + img_size - grad_start)
        alpha = int(200 * t)
        ov_draw.line((img_x, y, img_x + img_size, y), fill=(*BRAND_CREAM, alpha))

    story_rgba = story_img.convert("RGBA")
    story_rgba = Image.alpha_composite(story_rgba, overlay)
    story_img = story_rgba.convert("RGB")
    draw = ImageDraw.Draw(story_img)

    # ---- LOGO (top center) ----
    logo_area_brightness = 200  # top area is cream, use dark logo
    logo_path = LOGO_DARK

    try:
        logo = Image.open(logo_path).convert("RGBA")
        logo_w = int(SW * 0.22)
        logo_h = int(logo_w * logo.height / logo.width)
        logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
        logo_x = (SW - logo_w) // 2
        logo_y = int(SH * 0.045)
        story_img.paste(logo, (logo_x, logo_y), logo)
        print(f"[PILLOW] Logo placed at top center")
    except Exception as e:
        print(f"[PILLOW] Logo error: {e}")

    draw = ImageDraw.Draw(story_img)

    # ---- STORY TEXT (below image) ----
    text_area_top = img_y + img_size + int(SH * 0.02)
    text_area_bottom = int(SH * 0.94)
    center_x = SW / 2

    if story_type == "invitation":
        # Split at "This is what Clarity Lab was built for."
        parts = story_text.split("This is what Clarity Lab was built for.")
        main_text = parts[0].strip()
        cta_text = "This is what Clarity Lab was built for."
    else:
        main_text = story_text
        cta_text = "Read the full reflection on the site."

    # Main text font
    main_font = get_font(42, serif=True)
    cta_font = get_font(26, serif=False)
    small_font = get_font(22, serif=False)

    max_width = int(SW * 0.78)

    main_lines = wrap_text_by_width(draw, main_text, main_font, max_width)

    # Calculate text block height
    line_h = 42 + 14  # approx
    total_main_h = len(main_lines) * line_h

    # Center text block vertically in bottom area
    text_area_h = text_area_bottom - text_area_top
    text_block_h = total_main_h + 60 + 30  # main + gap + cta
    start_y = text_area_top + (text_area_h - text_block_h) // 2

    start_y = max(start_y, text_area_top + 20)

    # Draw main text
    end_y = draw_centered_lines(
        draw=draw,
        lines=main_lines,
        center_x=center_x,
        y=start_y,
        font=main_font,
        fill=(*BRAND_DARK, 230),
        line_gap=14
    )

    # Draw CTA
    cta_y = end_y + 40
    cta_lines = wrap_text_by_width(draw, cta_text, cta_font, max_width)
    draw_centered_lines(
        draw=draw,
        lines=cta_lines,
        center_x=center_x,
        y=cta_y,
        font=cta_font,
        fill=(*BRAND_SAGE, 200),
        line_gap=10
    )

    # Save
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        story_img.save(tmp.name, "JPEG", quality=95)
        story_path = tmp.name

    print(f"[PILLOW] Story image saved: {story_path}")
    return story_path

# ============================================================
# STEP 4: Upload to Cloudinary
# ============================================================

def upload_story_to_cloudinary(image_path, title):
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD,
        api_key=CLOUDINARY_KEY,
        api_secret=CLOUDINARY_SECRET
    )

    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', title)[:50]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    public_id = f"CL_stories/CL_{safe_title}_story_{timestamp}"

    print("[CLOUDINARY] Uploading Story image...")
    if FLAGS.dry_run:
        planned_url = f"dry-run://cloudinary/{public_id}.jpg"
        log_event(LOGGER, "dry_run_story_upload_skipped", platform="cloudinary", status="skipped", details={"public_id": public_id})
        print(f"[DRY RUN][CLOUDINARY] Would upload Story image as {public_id}")
        return planned_url

    last_error = None
    for attempt in range(1, FLAGS.http_max_retries + 1):
        try:
            result = cloudinary.uploader.upload(
                image_path,
                public_id=public_id,
                overwrite=False,
                resource_type="image"
            )
            break
        except Exception as exc:
            last_error = exc
            if attempt >= FLAGS.http_max_retries:
                raise
            log_event(LOGGER, "cloudinary_story_upload_retry", logging.WARNING, platform="cloudinary", status="retrying", error=str(exc))
            import time
            time.sleep(2 ** (attempt - 1))
    else:
        raise last_error

    secure_url = result.get("secure_url")
    if not secure_url:
        raise Exception("[CLOUDINARY] No URL returned")

    print(f"[CLOUDINARY] Story uploaded: {secure_url[:70]}...")
    return secure_url

# ============================================================
# STEP 5: Publish Story to Instagram
# ============================================================

def publish_instagram_story(image_url):
    print("[INSTAGRAM STORY] Creating story container...")
    if FLAGS.dry_run or not FLAGS.enable_instagram_publishing:
        log_event(LOGGER, "instagram_story_publish_skipped", platform="instagram", status="skipped", details={"dry_run": FLAGS.dry_run, "enabled": FLAGS.enable_instagram_publishing, "image_url": image_url})
        print("[DRY RUN][INSTAGRAM STORY] Would publish story")
        return "dry-run-instagram-story-id"

    container_response = HTTP.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media",
        platform="instagram",
        data={
            "image_url": image_url,
            "media_type": "STORIES",
            "access_token": IG_TOKEN
        }
    )

    container = container_response.json()

    if "error" in container:
        raise Exception(f"[INSTAGRAM STORY] Container error: {container['error']['message']}")
    if "id" not in container:
        raise Exception(f"[INSTAGRAM STORY] Unexpected response: {container}")

    container_id = container["id"]
    print(f"[INSTAGRAM STORY] Container: {container_id}")

    # Wait for processing
    import time
    for attempt in range(1, 11):
        print(f"[INSTAGRAM STORY] Status check {attempt}/10...")
        status_data = HTTP.get(
            f"https://graph.facebook.com/v19.0/{container_id}",
            platform="instagram",
            params={"fields": "status_code,status", "access_token": IG_TOKEN}
        ).json()

        if status_data.get("status_code") == "FINISHED":
            print("[INSTAGRAM STORY] Media ready.")
            break
        if status_data.get("status_code") == "ERROR":
            raise Exception(f"[INSTAGRAM STORY] Processing error: {status_data}")
        time.sleep(10)
    else:
        raise Exception("[INSTAGRAM STORY] Media not ready after waiting")

    # Publish
    print("[INSTAGRAM STORY] Publishing...")
    result = HTTP.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
        platform="instagram",
        data={
            "creation_id": container_id,
            "access_token": IG_TOKEN
        }
    ).json()

    if "error" in result:
        raise Exception(f"[INSTAGRAM STORY] Publish error: {result['error']['message']}")
    if "id" not in result:
        raise Exception(f"[INSTAGRAM STORY] Unexpected: {result}")

    print(f"[INSTAGRAM STORY] Published: {result['id']}")
    return result["id"]

# ============================================================
# MAIN
# ============================================================

def run_stories_pipeline():
    print(f"\n{'='*60}")
    print(f"Clarity Lab Stories Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # Get last published topic
    index, topic = get_last_published_topic()

    # Determine story type (rotates: question / observation / invitation)
    story_type = get_story_type(index)
    print(f"[STORY] Type: {story_type}")

    # Get master image from Cloudinary URL stored in topics.csv
    master_url = topic.get("Master Image URL", "").strip()

    if not master_url:
        raise Exception(
            f"[STORY] No Master Image URL found for topic: {topic['Topic / Working Title']}\n"
            f"Make sure the main pipeline has published this topic first and saved the Master Image URL."
        )

    # Download master image from Cloudinary
    print(f"[STORY] Downloading master image: {master_url[:60]}...")
    r = HTTP.get(master_url, platform="cloudinary")
    if r.status_code != 200:
        raise Exception(f"[STORY] Failed to download master image (HTTP {r.status_code}): {master_url}")
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(r.content)
        master_path = tmp.name
    print(f"[STORY] Master image downloaded: {master_path}")

    # Generate story text
    story_text = generate_story_text(topic, story_type)

    # Create story image
    story_image_path = create_story_image(master_path, story_text, story_type, topic)

    # Upload to Cloudinary
    story_url = upload_story_to_cloudinary(story_image_path, topic["Topic / Working Title"])

    # Publish to Instagram
    publish_instagram_story(story_url)

    print(f"\n{'='*60}")
    print(f"✅ Story published!")
    print(f"   Topic: {topic['Topic / Working Title']}")
    print(f"   Type: {story_type}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_stories_pipeline()
