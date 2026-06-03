"""
Clarity Lab — Automated Content Pipeline v7 (Final)
Fixes:
- media.displayed = True for Wix cover image
- heroImage with correct Wix file ID
- Logo only overlay (no text) via Pillow
- All status checks
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
from PIL import Image
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

def get_image_brightness(img):
    gray = img.convert("L")
    arr = np.array(gray)
    return float(arr.mean())

# ============================================================
# STEP 1: Pick next topic
# ============================================================

def get_next_topic():
    rows = []
    with open(TOPICS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    published_count = sum(
        1 for r in rows
        if r.get("Status", "").strip().lower() == "published"
    )

    for i, row in enumerate(rows):
        status = row.get("Status", "").strip().lower()
        if status in ("ready", ""):
            print(f"[TOPIC] Selected: {row['Topic / Working Title']}")
            print(f"[VISUAL] Published count: {published_count}")
            return i, rows, row, published_count

    raise Exception("No topics with status 'Ready' found in topics.csv")

def mark_topic_published(index, rows, post_url, master_image_url=""):
    rows[index]["Status"] = "Published"
    rows[index]["Website Published URL"] = post_url
    rows[index]["Publish Status Code"] = "200"
    rows[index]["Workflow Status"] = "Complete"
    if master_image_url:
        rows[index]["Master Image URL"] = master_image_url

    fieldnames = list(rows[0].keys())
    with open(TOPICS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[TOPICS] Status updated to Published")

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
# STEP 3: Generate image via gpt-image-1
# ============================================================

def generate_image(title, core_observation):
    client = OpenAI(api_key=OPENAI_API_KEY)

    image_prompt = (
    f'Create a luxury editorial photograph for a reflective article titled "{title}". '

    f'The visual scene must be inspired by the article theme and central idea: '
    f'"{core_observation}". '

    f'No people. No faces. No silhouettes. No body parts. '

    f'Use symbolic objects, architecture, natural forms, light, shadow, texture, space, '
    f'and composition to express the article meaning. '

    f'Visual style: high-end editorial photography, luxury magazine aesthetic, '
    f'calm sophistication, refined minimalism. '

    f'Palette: warm cream, soft stone, muted beige, warm sand, honey clay, '
    f'soft sage, mist blue, muted terracotta accents. '

    f'Lighting: natural light with strong depth and contrast. '
    f'Deep shadows are welcome. '
    f'Do not flatten the image. '

    f'Image quality: crisp, sharp, high-resolution editorial photography. '
    f'Realistic material textures. '
    f'Clear edges. '
    f'Natural optical detail. '
    f'Professional camera realism. '

    f'Not blurry. '
    f'Not painterly. '
    f'Not illustration. '
    f'Not CGI. '
    f'Not 3D render. '
    f'Not AI-smoothed. '

    f'The image should look like a photograph taken with a professional camera, '
    f'for Architectural Digest, Kinfolk, or a luxury editorial publication. '

    f'Square format.'
)


    print("[GPT-IMAGE] Generating image...")
    response = client.images.generate(
        model="gpt-image-1",
        prompt=image_prompt,
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

    print(f"[GPT-IMAGE] Image saved: {tmp_path}")
    return tmp_path

# ============================================================
# STEP 4: Overlay logo only (no text) via Pillow
# ============================================================

def overlay_logo(image_path):
    """Overlay Clarity Lab logo in top-left corner only. No text."""
    print("[PILLOW] Overlaying logo...")

    img = Image.open(image_path).convert("RGBA")
    W, H = img.size

    brightness = get_image_brightness(img)
    is_dark = brightness < 128
    logo_path = LOGO_WHITE if is_dark else LOGO_DARK

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))

    try:
        logo = Image.open(logo_path).convert("RGBA")
        logo_w = int(W * 0.30)
        logo_ratio = logo.height / logo.width
        logo_h = int(logo_w * logo_ratio)
        logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
        logo_x = int(W * 0.06)
        logo_y = int(H * 0.06)
        overlay.paste(logo, (logo_x, logo_y), logo)
        print(f"[PILLOW] Logo placed — brightness: {brightness:.0f}, using {'white' if is_dark else 'dark'} logo")
    except Exception as e:
        print(f"[PILLOW] Logo error: {e}")

    result = Image.alpha_composite(img, overlay).convert("RGB")

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        result.save(tmp.name, "JPEG", quality=95)
        branded_path = tmp.name

    print(f"[PILLOW] Branded image saved: {branded_path}")
    return branded_path

# ============================================================
# STEP 5: Upload to Cloudinary
# ============================================================

def upload_to_cloudinary(image_path, title):
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD,
        api_key=CLOUDINARY_KEY,
        api_secret=CLOUDINARY_SECRET
    )

    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', title)[:50]
    public_id = f"CL_master/CL_{safe_title}"

    print("[CLOUDINARY] Uploading image...")
    result = cloudinary.uploader.upload(
        image_path,
        public_id=public_id,
        overwrite=False,
        resource_type="image"
    )

    secure_url = result.get("secure_url")
    if not secure_url:
        raise Exception("[CLOUDINARY] No URL returned")

    print(f"[CLOUDINARY] Uploaded: {secure_url[:70]}...")
    return secure_url

# ============================================================
# STEP 6: Import image to Wix Media — get file ID
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
        print(f"[WIX MEDIA] No file ID, using Cloudinary URL")

    return wix_file_id, wix_url

# ============================================================
# STEP 7: Publish to Wix Blog
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

    # Import image to Wix Media
    wix_file_id, wix_url = import_image_to_wix(cloudinary_url, title, wix_headers)

    # Convert content
    html_content = text_to_html(website_text)
    rich_content = convert_html_to_ricos(html_content, wix_headers)
    clean_text = clean_markdown(website_text)
    excerpt = " ".join(clean_text.split()[:40]) + "..."

    # Create draft
    print("[WIX] Creating draft post...")
    draft_response = requests.post(
        "https://www.wixapis.com/blog/v3/draft-posts",
        headers=wix_headers,
        json={
            "draftPost": {
                "title": title,
                "excerpt": excerpt,
                "richContent": rich_content,
                "media": {
                    "wixMedia": {
                        "image": {
                            "id": wix_file_id
                        }
                    },
                    "displayed": True,
                    "custom": True
                },
                "featured": False,
                "hashtags": ["clarity", "reflection", "selfawareness", "InnerOS", "mindfulness"],
                "memberId": "4d7e0085-753e-4aee-b7c6-ed66431fd9c6"
            }
        }
    )
    draft_data = check_response(draft_response, "WIX CREATE DRAFT")
    draft_id = draft_data.get("draftPost", {}).get("id")
    if not draft_id:
        raise Exception(f"[WIX] No draft ID: {draft_data}")
    print(f"[WIX] Draft created: {draft_id}")

    # Verify
    verify_response = requests.get(
        f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}",
        headers=wix_headers
    )
    check_response(verify_response, "WIX VERIFY DRAFT")
    print("[WIX] Draft verified OK")

    # Publish
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
# STEP 8: Publish to Instagram
# ============================================================

def publish_to_instagram(caption, image_url):
    print("[INSTAGRAM] Creating container...")
    container_response = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media",
        data={"image_url": image_url, "caption": caption, "access_token": IG_TOKEN}
    )
    container = container_response.json()

    if "error" in container:
        raise Exception(f"[INSTAGRAM] Container error: {container['error']['message']}")
    if "id" not in container:
        raise Exception(f"[INSTAGRAM] Unexpected: {container}")

    container_id = container["id"]
    print(f"[INSTAGRAM] Container: {container_id}, waiting 5s...")
    time.sleep(5)

    publish_response = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": IG_TOKEN}
    )
    result = publish_response.json()

    if "error" in result:
        raise Exception(f"[INSTAGRAM] Publish error: {result['error']['message']}")
    if "id" not in result:
        raise Exception(f"[INSTAGRAM] Unexpected: {result}")

    print(f"[INSTAGRAM] Published: {result['id']}")
    return result["id"]

# ============================================================
# STEP 9: Publish to Facebook
# ============================================================

def publish_to_facebook(message, image_url):
    print("[FACEBOOK] Publishing...")
    response = requests.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
        data={"url": image_url, "message": message, "access_token": FB_PAGE_TOKEN}
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
    print(f"Clarity Lab Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    index, rows, topic = get_next_topic()

    content = generate_content(topic)
    title   = content["title"]
    ig_text = content["instagram"]
    website = content["website"]

    raw_image_path = generate_image(title, topic["Core Observation"])
    branded_image_path = overlay_logo(raw_image_path)
    cloudinary_url = upload_to_cloudinary(branded_image_path, title)

    post_url = publish_to_wix(title, website, cloudinary_url)

    hashtags = "#clarity #reflection #selfawareness #InnerOS #mindfulness #humandesign #AI"
    ig_caption = f"{ig_text}\n\n{hashtags}"
    publish_to_instagram(ig_caption, cloudinary_url)

    fb_message = f"{ig_text}\n\n{post_url}"
    publish_to_facebook(fb_message, cloudinary_url)

    mark_topic_published(index, rows, post_url, master_image_url=website_url)

    print(f"\n{'='*60}")
    print(f"✅ Done! {title}")
    print(f"   {post_url}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_pipeline()
