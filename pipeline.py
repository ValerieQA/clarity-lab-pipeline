"""
Clarity Lab — Automated Content Pipeline v4
Fixes:
- Image upload via /site-media/v1/files/import (correct endpoint)
- Markdown headers stripped from article text
- All status checks in place
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
    """Remove markdown headers and extra formatting from article text."""
    # Remove markdown headers (# ## ###)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    # Remove horizontal rules
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
    # Clean up extra blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def text_to_html(text):
    text = clean_markdown(text)
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs)

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
    print(f"[TOPICS] Status updated to Published")

# ============================================================
# STEP 2: Generate article content via GPT
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
        f'Calm, minimal, atmospheric photograph-style image '
        f'for a reflective article titled "{title}". '
        f'Style: warm coffee tones, soft blues, muted beige and cream palette. '
        f'Soft natural light, shadows, minimal composition. '
        f'Abstract or still life: books, stones, ceramics, plants, soft textures. '
        f'NO people, NO text, NO logos. '
        f'Mood: quiet, precise, human, thoughtful. '
        f'High-end editorial photography for a mindfulness publication. '
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
# STEP 4: Upload image to Cloudinary
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
# STEP 5: Import image to Wix Media
# ============================================================

def import_image_to_wix(cloudinary_url, title, wix_headers):
    """
    Import image from Cloudinary URL into Wix Media.
    Uses /site-media/v1/files/import endpoint.
    Returns Wix media file ID for use in coverMedia.
    Falls back to Cloudinary URL if import fails.
    """
    print("[WIX MEDIA] Importing image...")

    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', title)[:50]

    response = requests.post(
        "https://www.wixapis.com/site-media/v1/files/import",
        headers=wix_headers,
        json={
            "url": cloudinary_url,
            "displayName": f"CL_{safe_title}",
            "mimeType": "image/png"
        }
    )

    if response.status_code not in (200, 201):
        print(f"[WIX MEDIA] Import failed (HTTP {response.status_code}): {response.text[:200]}")
        print("[WIX MEDIA] Falling back to Cloudinary URL")
        return None, cloudinary_url

    data = response.json()
    file_info = data.get("file", {})
    wix_file_id = file_info.get("id") or file_info.get("fileId")
    wix_url = file_info.get("url") or file_info.get("fileUrl") or cloudinary_url

    if wix_file_id:
        print(f"[WIX MEDIA] Imported. File ID: {wix_file_id}")
    else:
        print(f"[WIX MEDIA] Imported. URL: {wix_url[:70]}...")

    return wix_file_id, wix_url

# ============================================================
# STEP 6: Publish article to Wix Blog
# ============================================================

def convert_html_to_ricos(html_content, wix_headers):
    print("[WIX] Converting content to Ricos...")
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
    wix_file_id, cover_url = import_image_to_wix(cloudinary_url, title, wix_headers)

    # Build cover media object
    if wix_file_id:
        cover_media = {
            "image": {
                "id": wix_file_id,
                "url": cover_url
            }
        }
    else:
        cover_media = {
            "image": {
                "url": cover_url
            }
        }

    # Convert text to Ricos
    html_content = text_to_html(website_text)
    rich_content = convert_html_to_ricos(html_content, wix_headers)

    # Clean excerpt
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
                "coverMedia": cover_media,
                "featured": False,
                "hashtags": ["clarity", "reflection", "selfawareness", "InnerOS", "mindfulness"],
                "memberId": "4d7e0085-753e-4aee-b7c6-ed66431fd9c6"
            }
        }
    )
    draft_data = check_response(draft_response, "WIX CREATE DRAFT")

    draft_id = draft_data.get("draftPost", {}).get("id")
    if not draft_id:
        raise Exception(f"[WIX] No draft ID in response: {draft_data}")
    print(f"[WIX] Draft created: {draft_id}")

    # Verify draft
    verify_response = requests.get(
        f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}",
        headers=wix_headers
    )
    check_response(verify_response, "WIX VERIFY DRAFT")
    print("[WIX] Draft verified OK")

    # Publish
    print("[WIX] Publishing post...")
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
# STEP 7: Publish to Instagram
# ============================================================

def publish_to_instagram(caption, image_url):
    print("[INSTAGRAM] Creating media container...")
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
        raise Exception(f"[INSTAGRAM] Unexpected response: {container}")

    container_id = container["id"]
    print(f"[INSTAGRAM] Container: {container_id}, waiting 5s...")
    time.sleep(5)

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
        raise Exception(f"[INSTAGRAM] Unexpected response: {result}")

    print(f"[INSTAGRAM] Published: {result['id']}")
    return result["id"]

# ============================================================
# STEP 8: Publish to Facebook
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
        raise Exception(f"[FACEBOOK] Unexpected response: {result}")

    print(f"[FACEBOOK] Published: {result['id']}")
    return result["id"]

# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline():
    print(f"\n{'='*60}")
    print(f"Clarity Lab Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # Step 1: Get topic
    index, rows, topic = get_next_topic()

    # Step 2: Generate content
    content = generate_content(topic)
    title   = content["title"]
    ig_text = content["instagram"]
    website = content["website"]

    # Step 3: Generate image
    image_path = generate_image(title, topic["Core Observation"])

    # Step 4: Upload to Cloudinary
    cloudinary_url = upload_to_cloudinary(image_path, title)

    # Step 5-6: Publish to Wix (includes Wix Media import)
    post_url = publish_to_wix(title, website, cloudinary_url)

    # Step 7: Publish to Instagram
    hashtags = "#clarity #reflection #selfawareness #InnerOS #mindfulness #humandesign #AI"
    ig_caption = f"{ig_text}\n\nRead the full article → link in bio\n\n{hashtags}"
    publish_to_instagram(ig_caption, cloudinary_url)

    # Step 8: Publish to Facebook
    fb_message = f"{ig_text}\n\nRead the full article → {post_url}"
    publish_to_facebook(fb_message, cloudinary_url)

    # Step 9: Mark topic as published
    mark_topic_published(index, rows, post_url)

    print(f"\n{'='*60}")
    print(f"✅ Pipeline complete!")
    print(f"   Title:   {title}")
    print(f"   Article: {post_url}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_pipeline()
