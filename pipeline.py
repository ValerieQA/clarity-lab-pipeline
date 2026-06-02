"""
Clarity Lab — Automated Content Pipeline v13

Updates:
- One master image for Website, Instagram, Facebook
- No people at all
- No GPT-generated logos, symbols, circles, letters, monograms, or text
- Real logo added only via Pillow
- Logo moved lower and slightly closer to center
- Image prompt no longer hardcodes object lists
- Instagram text added via Pillow, centered symmetrically in lower third
- Instagram text is shorter, narrower, and more editorial
"""

import os
import csv
import re
import time
import base64
import tempfile
import requests
from datetime import datetime
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import cloudinary
import cloudinary.uploader

# ============================================================
# CONFIG
# ============================================================

OPENAI_API_KEY     = os.environ["OPENAI_API_KEY"]
CLOUDINARY_CLOUD   = os.environ["CLOUDINARY_CLOUD_NAME"]
CLOUDINARY_KEY     = os.environ["CLOUDINARY_API_KEY"]
CLOUDINARY_SECRET  = os.environ["CLOUDINARY_API_SECRET"]
WIX_SITE_ID        = os.environ["WIX_SITE_ID"]
WIX_API_KEY        = os.environ["WIX_API_KEY"]
IG_USER_ID         = os.environ["IG_USER_ID"]
IG_TOKEN           = os.environ["IG_TOKEN"]
FB_PAGE_ID         = os.environ["FB_PAGE_ID"]
FB_PAGE_TOKEN      = os.environ["FB_PAGE_TOKEN"]

TOPICS_FILE        = "topics.csv"
PROMPT_FILE        = "config/prompt.md"
LOGO_DARK          = "config/logo_dark.png"
LOGO_WHITE         = "config/logo_white.png"

# ============================================================
# VISUAL SYSTEM
# ============================================================

VISUAL_JOURNEY = [
    {"name": "Morning Mist", "mood": "fresh clarity, quiet beginning, soft light", "palette": "mist blue, pale cream, light stone, soft grey-blue, airy white"},
    {"name": "Pale Sky", "mood": "lightness, openness, space to breathe", "palette": "pale sky blue, cloud white, soft beige, muted horizon blue"},
    {"name": "Sea Foam", "mood": "airy calm, subtle movement, emotional spaciousness", "palette": "sea foam green, blue-grey, soft cream, washed natural tones"},
    {"name": "Soft Sage", "mood": "gentle balance, grounded growth, natural quiet", "palette": "soft sage, muted olive, cream, linen, warm grey"},
    {"name": "Warm Leaf", "mood": "natural warmth, subtle energy, living stillness", "palette": "warm green, muted leaf, beige, soft gold, natural shadow"},
    {"name": "Sand Dune", "mood": "comfort, inner stability, warm ground", "palette": "sand beige, dune cream, pale clay, soft taupe, warm light"},
    {"name": "Honey Clay", "mood": "soft warmth, nourishment, human presence", "palette": "honey beige, clay, cream, warm ochre, muted caramel"},
    {"name": "Linen Earth", "mood": "earthy depth, quiet introspection, texture", "palette": "linen, stone, earth beige, warm grey, muted brown"},
    {"name": "Dust Rose", "mood": "transition, softening, emotional nuance", "palette": "dust rose, muted terracotta, soft beige, pale clay, warm shadow"},
    {"name": "Dusty Blue", "mood": "deepening, inner depth, calm concentration", "palette": "dusty blue, slate blue, cream, soft grey, muted navy"},
    {"name": "Deep Evening", "mood": "reflection, quiet depth, elegant shadow", "palette": "deep navy accents, dusty blue, warm cream, muted gold, soft shadow"},
    {"name": "Twilight", "mood": "integration, rest, pause before renewal", "palette": "twilight blue, mauve-grey, muted lilac, soft peach, dusk cream"},
    {"name": "Return To Mist", "mood": "renewal, clarity returning, a new cycle", "palette": "mist blue, pale cream, soft grey-blue, quiet white, distant green"},
]

ACCENT_STATES = [
    "muted terracotta",
    "soft golden hour",
    "dusty mauve",
    "muted lilac",
    "deep olive",
    "ocean teal",
]

# ============================================================
# HELPERS
# ============================================================

def check_response(response, step_name):
    if response.status_code not in (200, 201):
        raise Exception(
            f"[{step_name}] FAILED — HTTP {response.status_code}\n"
            f"Response: {response.text[:500]}"
        )
    return response.json()

def clean_markdown(text):
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def text_to_html(text):
    text = clean_markdown(text)
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs)

def get_region_brightness(img, box):
    region = img.crop(box).convert("L")
    arr = np.array(region)
    return float(arr.mean())

def get_visual_state(index):
    return VISUAL_JOURNEY[index % len(VISUAL_JOURNEY)]

def get_accent_state(index):
    if index % 3 == 0:
        return ACCENT_STATES[index % len(ACCENT_STATES)]
    return "no strong accent, only subtle natural variation"

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

def wrap_text_by_width(draw, text, font, max_width):
    words = clean_markdown(text).replace("\n", " ").split()
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

def draw_centered_lines(draw, lines, center_x, y, font, fill, line_gap=10):
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]
        draw.text((center_x - line_w / 2, y), line, font=font, fill=fill)
        y += line_h + line_gap
    return y

def get_instagram_phrase(ig_text, title):
    clean = clean_markdown(ig_text)
    lines = [line.strip() for line in clean.split("\n") if line.strip()]

    for line in lines:
        if "Read the full reflection" not in line and 20 <= len(line) <= 80:
            return line

    words = clean.split()
    phrase = " ".join(words[:10]) if words else title
    return phrase.strip()

# ============================================================
# STEP 1: Pick next topic
# ============================================================

def get_next_topic():
    rows = []
    with open(TOPICS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    for i, row in enumerate(rows):
        status = row.get("Status", "").strip().lower()
        if status in ("ready", ""):
            print(f"[TOPIC] Selected: {row['Topic / Working Title']}")
            return i, rows, row

    raise Exception("No topics with status 'Ready' found in topics.csv")

def mark_topic_published(index, rows, post_url):
    rows[index]["Status"] = "Published"
    rows[index]["Website Published URL"] = post_url
    rows[index]["Publish Status Code"] = "200"
    rows[index]["Workflow Status"] = "Complete"

    fieldnames = list(rows[0].keys())
    with open(TOPICS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print("[TOPICS] Status updated to Published")

# ============================================================
# STEP 2: Generate content via GPT
# ============================================================

def load_prompt():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()

def generate_content(topic_row):
    client = OpenAI(api_key=OPENAI_API_KEY)
    base_prompt = load_prompt()

    user_message = (
        f"Topic: {topic_row['Topic / Working Title']}\n"
        f"Core observation: {topic_row['Core Observation']}\n"
        f"Audience question: {topic_row['Audience Question']}\n"
        f"Content pillar: {topic_row['Content Pillar']}\n"
    )

    print("[GPT] Generating article content...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": base_prompt + "\n\n" + user_message}],
        max_tokens=2000,
        temperature=0.7
    )

    raw = response.choices[0].message.content
    print("[GPT] Content generated successfully")
    return parse_content(raw)

def parse_content(raw_text):
    patterns = {
        "title":     r"===TITLE===\s*(.*?)(?====|\Z)",
        "instagram": r"===INSTAGRAM===\s*(.*?)(?====|\Z)",
        "website":   r"===WEBSITE===\s*(.*?)(?====|\Z)",
        "geo":       r"===GEO===\s*(.*?)(?====|\Z)",
    }

    sections = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, raw_text, re.DOTALL)
        sections[key] = match.group(1).strip() if match else ""

    if not sections.get("title"):
        raise Exception("[PARSE] Title is empty")
    if not sections.get("website"):
        raise Exception("[PARSE] Website article is empty")

    print(f"[PARSE] Title: {sections['title']}")
    return sections

# ============================================================
# STEP 3: Build master image prompt
# ============================================================

def build_master_image_prompt(title, core_observation, audience_question, visual_state, accent_state):
    return f"""
Create one master image for a reflective Clarity Lab article.

This image will be used across Website, Instagram, and Facebook.
It must be one coherent visual world.

Article title:
"{title}"

Core observation:
"{core_observation}"

Audience question:
"{audience_question}"

The visual scene should emerge primarily from the article topic and core observation.
The image should be topic-oriented first.

Visual hierarchy:
70% article topic and core observation.
20% visual journey state.
10% subtle accent variation.

Visual journey state:
{visual_state["name"]}

Mood:
{visual_state["mood"]}

Palette direction:
{visual_state["palette"]}

Optional accent:
{accent_state}

The palette influences mood and color treatment, but should not dictate the subject matter.
Favor semantic relevance over decorative consistency.

Visual language:
quiet,
contemplative,
editorial,
luxury,
reflective,
timeless,
minimal,
architectural,
symbolic,
spacious.

Scene rule:
The scene should be topic-driven.
Objects, environments, materials, and symbols should emerge naturally from the article theme.
Favor atmosphere over objects.
Favor meaning over literal illustration.
Favor space over decoration.

Luxury editorial direction:
Think quiet luxury, refined visual rhythm, timeless editorial photography, natural materials, architectural calm, textured surfaces, air, shadow, and light.
The image should feel expensive, quiet, minimal, intelligent, and spacious.
Avoid generic lifestyle imagery.
Avoid social media template aesthetics.
Avoid sentimental scenes.
Avoid motivational poster style.

Light and contrast:
Use a light-first palette, but do not make the image flat.
Use elegant contrast.
Use deep shadows as design elements.
Allow 30–40% darker tonal areas if they create depth, structure, luxury, and visual rhythm.
Keep the overall image calm, luminous, and breathable.
Use natural light, sculptural shadows, soft gradients, and material depth.
Avoid harsh cinematic drama.
Avoid muddy olive or overly saturated green.
Avoid heavy dark backgrounds.
Avoid washed-out low-contrast beige.

Human rule:
No people at all.
No human figures.
No portraits.
No faces.
No silhouettes.
No hands.
No bodies.
No shadows of people.
No implied person as the subject.

Branding and text rule:
Do not generate any logo.
Do not draw Clarity Lab logo.
Do not draw logo placeholders.
Do not create circles, monograms, initials, letters, symbols, emblems, stamps, watermarks, or brand marks.
Do not include text.
Do not include typography.
Do not include fake letters.
Do not include decorative circular marks.
Logo and Instagram text will be added later with code.

Avoid literal illustration.
Do not show obvious symbols like brains, lightbulbs, icons, charts, arrows, or motivational graphics.
Express the idea indirectly through atmosphere, composition, symbolism, light, space, materials, nature, architecture, water, interiors, landscapes, movement, or stillness.

Avoid repeating visual compositions from recent posts.
The feed should feel like one evolving visual conversation.

Format:
Square 1024x1024.

Composition:
Leave clean negative space in the upper-left area for a small logo overlay.
Leave calm negative space in the lower third or lower center for a short Instagram text overlay.
The image should work cleanly as a website cover, Instagram post, and Facebook image.
"""

# ============================================================
# STEP 4: Generate master image
# ============================================================

def generate_master_image(title, core_observation, audience_question, visual_state, accent_state):
    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = build_master_image_prompt(
        title=title,
        core_observation=core_observation,
        audience_question=audience_question,
        visual_state=visual_state,
        accent_state=accent_state
    )

    print("[GPT-IMAGE] Generating one master image...")
    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size="1024x1024",
        n=1
    )

    image_data = response.data[0].b64_json
    if not image_data:
        raise Exception("[GPT-IMAGE] No image data returned")

    image_bytes = base64.b64decode(image_data)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    print(f"[GPT-IMAGE] Master image saved: {tmp_path}")
    return tmp_path

# ============================================================
# STEP 5A: Overlay exact Clarity Lab logo only
# ============================================================

def overlay_logo(image_path):
    print("[PILLOW] Overlaying exact logo...")

    img = Image.open(image_path).convert("RGBA")
    W, H = img.size

    logo_area = (
        int(W * 0.08),
        int(H * 0.07),
        int(W * 0.36),
        int(H * 0.26)
    )
    local_brightness = get_region_brightness(img, logo_area)

    logo_path = LOGO_DARK if local_brightness > 135 else LOGO_WHITE

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))

    try:
        logo = Image.open(logo_path).convert("RGBA")
        logo_w = int(W * 0.17)
        logo_ratio = logo.height / logo.width
        logo_h = int(logo_w * logo_ratio)
        logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

        logo_x = int(W * 0.10)
        logo_y = int(H * 0.11)

        overlay.paste(logo, (logo_x, logo_y), logo)
        print(f"[PILLOW] Logo placed — local brightness: {local_brightness:.0f}")
    except Exception as e:
        print(f"[PILLOW] Logo error: {e}")

    result = Image.alpha_composite(img, overlay).convert("RGB")

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        result.save(tmp.name, "JPEG", quality=95)
        branded_path = tmp.name

    print(f"[PILLOW] Branded image saved: {branded_path}")
    return branded_path

# ============================================================
# STEP 5B: Instagram editorial text
# ============================================================

def overlay_instagram_editorial(image_path, title, ig_text):
    print("[PILLOW] Creating Instagram editorial image...")

    img = Image.open(image_path).convert("RGBA")
    W, H = img.size

    logo_area = (
        int(W * 0.08),
        int(H * 0.07),
        int(W * 0.36),
        int(H * 0.26)
    )
    local_brightness = get_region_brightness(img, logo_area)
    logo_path = LOGO_DARK if local_brightness > 135 else LOGO_WHITE

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Soft lower-third veil for readability, not a hard box.
    for y in range(int(H * 0.58), H):
        alpha = int(45 * ((y - int(H * 0.58)) / (H - int(H * 0.58))))
        draw.line((0, y, W, y), fill=(255, 248, 238, alpha))

    try:
        logo = Image.open(logo_path).convert("RGBA")
        logo_w = int(W * 0.17)
        logo_ratio = logo.height / logo.width
        logo_h = int(logo_w * logo_ratio)
        logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

        logo_x = int(W * 0.085)
        logo_y = int(H * 0.080)

        overlay.paste(logo, (logo_x, logo_y), logo)
    except Exception as e:
        print(f"[PILLOW] Instagram logo error: {e}")

    draw = ImageDraw.Draw(overlay)

    phrase = get_instagram_phrase(ig_text, title)

    phrase_font = get_font(34, serif=True)
    small_font = get_font(14, serif=False)

    center_x = W / 2
    max_width = int(W * 0.62)

    phrase_lines = wrap_text_by_width(draw, phrase, phrase_font, max_width)
    phrase_lines = phrase_lines[:2]

    line_heights = []
    for line in phrase_lines:
        bbox = draw.textbbox((0, 0), line, font=phrase_font)
        line_heights.append(bbox[3] - bbox[1])

    total_height = sum(line_heights) + max(0, len(phrase_lines) - 1) * 10

    text_block_center_y = int(H * 0.745)
    start_y = int(text_block_center_y - total_height / 2)

    text_color = (34, 40, 41, 235)
    small_color = (64, 69, 69, 190)

    draw_centered_lines(
        draw=draw,
        lines=phrase_lines,
        center_x=center_x,
        y=start_y,
        font=phrase_font,
        fill=text_color,
        line_gap=10
    )

    bottom = "READ THE FULL REFLECTION ON THE SITE."
    bbox = draw.textbbox((0, 0), bottom, font=small_font)
    bottom_w = bbox[2] - bbox[0]
    draw.text(
        (center_x - bottom_w / 2, int(H * 0.89)),
        bottom,
        font=small_font,
        fill=small_color
    )

    result = Image.alpha_composite(img, overlay).convert("RGB")

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        result.save(tmp.name, "JPEG", quality=95)
        instagram_path = tmp.name

    print(f"[PILLOW] Instagram editorial image saved: {instagram_path}")
    return instagram_path

# ============================================================
# STEP 6: Upload to Cloudinary
# ============================================================

def upload_to_cloudinary(image_path, title, variant):
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD,
        api_key=CLOUDINARY_KEY,
        api_secret=CLOUDINARY_SECRET
    )

    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', title)[:55]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    public_id = f"CL_master/CL_{safe_title}_{variant}_{timestamp}"

    print(f"[CLOUDINARY] Uploading {variant} image...")
    result = cloudinary.uploader.upload(
        image_path,
        public_id=public_id,
        overwrite=False,
        resource_type="image"
    )

    secure_url = result.get("secure_url")
    if not secure_url:
        raise Exception("[CLOUDINARY] No URL returned")

    print(f"[CLOUDINARY] Uploaded {variant}: {secure_url[:70]}...")
    return secure_url

# ============================================================
# STEP 7: Import image to Wix Media
# ============================================================

def import_image_to_wix(cloudinary_url, title, wix_headers):
    print("[WIX MEDIA] Importing image...")

    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', title)[:50]

    response = requests.post(
        "https://www.wixapis.com/site-media/v1/files/import",
        headers=wix_headers,
        json={
            "url": cloudinary_url,
            "displayName": f"CL_{safe_title}",
            "mimeType": "image/jpeg"
        }
    )

    if response.status_code not in (200, 201):
        print(f"[WIX MEDIA] Import failed (HTTP {response.status_code}): {response.text[:200]}")
        return None, cloudinary_url

    data = response.json()
    file_info = data.get("file", {})
    wix_file_id = file_info.get("id") or file_info.get("fileId")
    wix_url = file_info.get("url") or cloudinary_url

    if wix_file_id:
        print(f"[WIX MEDIA] File ID: {wix_file_id}")
    else:
        print("[WIX MEDIA] No file ID, using Cloudinary URL")

    return wix_file_id, wix_url

# ============================================================
# STEP 8: Publish to Wix Blog
# ============================================================

def convert_html_to_ricos(html_content, wix_headers):
    print("[WIX] Converting to Ricos...")

    response = requests.post(
        "https://www.wixapis.com/ricos/v1/ricos-document/convert/to-ricos",
        headers=wix_headers,
        json={"html": html_content}
    )

    data = check_response(response, "WIX RICOS")
    rich_content = data.get("document")

    if not rich_content:
        raise Exception("[WIX RICOS] No document in response")

    return rich_content

def publish_to_wix(title, website_text, cloudinary_url):
    wix_headers = {
        "Authorization": WIX_API_KEY,
        "wix-site-id": WIX_SITE_ID,
        "Content-Type": "application/json"
    }

    wix_file_id, wix_url = import_image_to_wix(cloudinary_url, title, wix_headers)

    html_content = text_to_html(website_text)
    rich_content = convert_html_to_ricos(html_content, wix_headers)
    clean_text = clean_markdown(website_text)
    excerpt = " ".join(clean_text.split()[:40]) + "..."

    media_block = {
        "displayed": True,
        "custom": True
    }

    if wix_file_id:
        media_block["wixMedia"] = {
            "image": {
                "id": wix_file_id
            }
        }

    print("[WIX] Creating draft post...")

    draft_response = requests.post(
        "https://www.wixapis.com/blog/v3/draft-posts",
        headers=wix_headers,
        json={
            "draftPost": {
                "title": title,
                "excerpt": excerpt,
                "richContent": rich_content,
                "media": media_block,
                "featured": False,
                "hashtags": [
                    "clarity",
                    "reflection",
                    "selfawareness",
                    "InnerOS",
                    "mindfulness"
                ],
                "memberId": "4d7e0085-753e-4aee-b7c6-ed66431fd9c6"
            }
        }
    )

    draft_data = check_response(draft_response, "WIX CREATE DRAFT")
    draft_id = draft_data.get("draftPost", {}).get("id")

    if not draft_id:
        raise Exception(f"[WIX] No draft ID: {draft_data}")

    print(f"[WIX] Draft created: {draft_id}")

    verify_response = requests.get(
        f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}",
        headers=wix_headers
    )

    check_response(verify_response, "WIX VERIFY DRAFT")
    print("[WIX] Draft verified OK")

    print("[WIX] Publishing...")

    publish_response = requests.post(
        f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}/publish",
        headers=wix_headers
    )

    check_response(publish_response, "WIX PUBLISH")

    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    post_url = f"https://www.inneros.online/post/{slug}"

    print(f"[WIX] Published: {post_url}")
    return post_url

# ============================================================
# STEP 9: Publish to Instagram
# ============================================================

def publish_to_instagram(caption, image_url):
    print("[INSTAGRAM] Creating container...")

    container_response = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media",
        data={
            "image_url": image_url,
            "caption": caption,
            "access_token": IG_TOKEN
        }
    )

    container = container_response.json()

    if "error" in container:
        raise Exception(f"[INSTAGRAM] Container error: {container['error']['message']}")
    if "id" not in container:
        raise Exception(f"[INSTAGRAM] Unexpected: {container}")

    container_id = container["id"]
    print(f"[INSTAGRAM] Container created: {container_id}")

    # Wait until Instagram finishes processing the image
    for attempt in range(1, 11):
        print(f"[INSTAGRAM] Checking container status... attempt {attempt}/10")

        status_response = requests.get(
            f"https://graph.facebook.com/v19.0/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": IG_TOKEN
            }
        )

        status_data = status_response.json()
        print(f"[INSTAGRAM] Status: {status_data}")

        status_code = status_data.get("status_code")

        if status_code == "FINISHED":
            print("[INSTAGRAM] Media ready.")
            break

        if status_code == "ERROR":
            raise Exception(f"[INSTAGRAM] Media processing error: {status_data}")

        time.sleep(10)

    else:
        raise Exception("[INSTAGRAM] Media was not ready after waiting")

    print("[INSTAGRAM] Publishing...")

    publish_response = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
        data={
            "creation_id": container_id,
            "access_token": IG_TOKEN
        }
    )

    result = publish_response.json()

    if "error" in result:
        raise Exception(f"[INSTAGRAM] Publish error: {result['error']['message']}")
    if "id" not in result:
        raise Exception(f"[INSTAGRAM] Unexpected: {result}")

    print(f"[INSTAGRAM] Published: {result['id']}")
    return result["id"]

# ============================================================
# STEP 10: Publish to Facebook
# ============================================================

def publish_to_facebook(message, image_url):
    print("[FACEBOOK] Publishing...")

    response = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
        data={
            "url": image_url,
            "message": message,
            "access_token": FB_PAGE_TOKEN
        }
    )

    result = response.json()

    if "error" in result:
        raise Exception(f"[FACEBOOK] Error: {result['error']['message']}")
    if "id" not in result:
        raise Exception(f"[FACEBOOK] Unexpected: {result}")

    print(f"[FACEBOOK] Published: {result['id']}")
    return result["id"]

# ============================================================
# MAIN
# ============================================================

def run_pipeline():
    print(f"\n{'='*60}")
    print(f"Clarity Lab Pipeline v13 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    index, rows, topic = get_next_topic()

    visual_state = get_visual_state(index)
    accent_state = get_accent_state(index)

    print(f"[VISUAL] State: {visual_state['name']}")
    print(f"[VISUAL] Accent: {accent_state}")

    content = generate_content(topic)

    title   = content["title"]
    ig_text = content["instagram"]
    website = content["website"]

    core_observation = topic["Core Observation"]
    audience_question = topic["Audience Question"]

    master_raw = generate_master_image(
        title=title,
        core_observation=core_observation,
        audience_question=audience_question,
        visual_state=visual_state,
        accent_state=accent_state
    )

    website_image = overlay_logo(master_raw)
    instagram_image = overlay_instagram_editorial(master_raw, title, ig_text)

    website_url = upload_to_cloudinary(website_image, title, "website")
    instagram_url = upload_to_cloudinary(instagram_image, title, "instagram")

    post_url = publish_to_wix(title, website, website_url)

    hashtags = "#clarity #reflection #selfawareness #InnerOS #mindfulness #humandesign #AI"

    ig_caption = f"{ig_text}\n\nRead the full article → link in bio\n\n{hashtags}"
    publish_to_instagram(ig_caption, instagram_url)

    fb_text = ig_text[:500] if len(ig_text) > 500 else ig_text
    fb_message = f"{fb_text}\n\nRead the full article → {post_url}"
    publish_to_facebook(fb_message, website_url)

    mark_topic_published(index, rows, post_url)

    print(f"\n{'='*60}")
    print(f"✅ Done! {title}")
    print(f"   {post_url}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_pipeline()
