"""
Clarity Lab — Automated Content Pipeline
Runs via GitHub Actions on schedule (Mon/Wed/Fri)
One topic per run: article → image → publish to Wix + Instagram + Facebook
"""

import os
import csv
import re
import time
import requests
import tempfile
from datetime import datetime
from openai import OpenAI
import cloudinary
import cloudinary.uploader

# ============================================================
# CONFIG — all secrets from GitHub Secrets / environment vars
# ============================================================

OPENAI_API_KEY      = os.environ["OPENAI_API_KEY"]
CLOUDINARY_CLOUD    = os.environ["CLOUDINARY_CLOUD_NAME"]
CLOUDINARY_KEY      = os.environ["CLOUDINARY_API_KEY"]
CLOUDINARY_SECRET   = os.environ["CLOUDINARY_API_SECRET"]

WIX_SITE_ID         = os.environ["WIX_SITE_ID"]
WIX_API_KEY         = os.environ["WIX_API_KEY"]

IG_USER_ID          = os.environ["IG_USER_ID"]
IG_TOKEN            = os.environ["IG_TOKEN"]

FB_PAGE_ID          = os.environ["FB_PAGE_ID"]
FB_PAGE_TOKEN       = os.environ["FB_PAGE_TOKEN"]

TOPICS_FILE         = "topics.csv"
PROMPT_FILE         = "config/prompt.md"
GEO_PROMPT_FILE     = "config/geo_prompt.md"

# ============================================================
# STEP 1: Pick next topic from topics.csv
# ============================================================

def get_next_topic():
    rows = []
    with open(TOPICS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    for i, row in enumerate(rows):
        if row.get("Status", "").strip().lower() in ("ready", ""):
            print(f"[TOPIC] Selected: {row['Topic / Working Title']}")
            return i, rows, row

    raise Exception("No topics with status 'Ready' found in topics.csv")

def mark_topic_published(index, rows, post_url):
    rows[index]["Status"] = "Published"
    rows[index]["Website Published URL"] = post_url
    rows[index]["Publish Status Code"] = "200"

    fieldnames = list(rows[0].keys())
    with open(TOPICS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[TOPICS] Marked as Published")

# ============================================================
# STEP 2: Generate article, Instagram post, GEO block via GPT
# ============================================================

def load_prompt():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()

def generate_content(topic_row):
    client = OpenAI(api_key=OPENAI_API_KEY)
    base_prompt = load_prompt()

    user_message = f"""
Topic: {topic_row['Topic / Working Title']}
Core observation: {topic_row['Core Observation']}
Audience question: {topic_row['Audience Question']}
Content pillar: {topic_row['Content Pillar']}
"""

    full_prompt = base_prompt + "\n\n" + user_message

    print("[GPT] Generating article content...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": full_prompt}],
        max_tokens=2000,
        temperature=0.7
    )

    raw = response.choices[0].message.content
    print("[GPT] Content generated successfully")
    return parse_content(raw)

def parse_content(raw_text):
    sections = {}

    patterns = {
        "title":     r"===TITLE===\s*(.*?)(?====|\Z)",
        "instagram": r"===INSTAGRAM===\s*(.*?)(?====|\Z)",
        "website":   r"===WEBSITE===\s*(.*?)(?====|\Z)",
        "geo":       r"===GEO===\s*(.*?)(?====|\Z)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, raw_text, re.DOTALL)
        sections[key] = match.group(1).strip() if match else ""

    print(f"[PARSE] Title: {sections.get('title', 'N/A')}")
    return sections

# ============================================================
# STEP 3: Generate image via DALL-E
# ============================================================

def generate_image(title, core_observation):
    client = OpenAI(api_key=OPENAI_API_KEY)

    image_prompt = f"""
Create a calm, minimal, atmospheric photograph-style image for a reflective article titled "{title}".

Style requirements:
- Warm coffee tones, soft blues, muted beige and cream palette
- Soft natural light, shadows, minimal composition
- Abstract or still life: books, stones, ceramics, plants, soft textures
- NO people, NO text, NO logos
- The mood should feel: quiet, precise, human, thoughtful
- Similar to high-end editorial photography for a mindfulness or philosophy publication
- Aspect ratio: square (1:1)
"""

    print("[DALL-E] Generating image...")
    response = client.images.generate(
        model="dall-e-3",
        prompt=image_prompt,
        size="1024x1024",
        quality="standard",
        n=1
    )

    image_url = response.data[0].url
    print(f"[DALL-E] Image generated: {image_url[:60]}...")
    return image_url

# ============================================================
# STEP 4: Upload image to Cloudinary
# ============================================================

def upload_to_cloudinary(image_url, title):
    cloudinary.config(
        cloud_name=CLOUDINARY_CLOUD,
        api_key=CLOUDINARY_KEY,
        api_secret=CLOUDINARY_SECRET
    )

    public_id = f"CL_master/CL_{title.replace(' ', '_')[:50]}"

    print(f"[CLOUDINARY] Uploading image...")
    result = cloudinary.uploader.upload(
        image_url,
        public_id=public_id,
        overwrite=False,
        resource_type="image"
    )

    secure_url = result["secure_url"]
    print(f"[CLOUDINARY] Uploaded: {secure_url[:60]}...")
    return secure_url

# ============================================================
# STEP 5: Publish article to Wix Blog
# ============================================================

def convert_html_to_ricos(html_content, wix_headers):
    response = requests.post(
        "https://www.wixapis.com/ricos/v1/ricos-document/convert/to-ricos",
        headers=wix_headers,
        json={"html": html_content}
    )
    if response.status_code != 200:
        raise Exception(f"Ricos conversion failed: {response.text}")
    return response.json().get("document")

def text_to_html(text):
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs)

def publish_to_wix(title, website_text, image_url):
    wix_headers = {
        "Authorization": WIX_API_KEY,
        "wix-site-id": WIX_SITE_ID,
        "Content-Type": "application/json"
    }

    html_content = text_to_html(website_text)
    rich_content = convert_html_to_ricos(html_content, wix_headers)

    excerpt = website_text[:200].strip() + "..."

    draft_body = {
        "draftPost": {
            "title": title,
            "excerpt": excerpt,
            "richContent": rich_content,
            "coverMedia": {
                "image": {"url": image_url}
            },
            "featured": False,
            "hashtags": ["clarity", "reflection", "selfawareness", "InnerOS", "mindfulness"]
        }
    }

    print("[WIX] Creating draft post...")
    draft_response = requests.post(
        "https://www.wixapis.com/blog/v3/draft-posts",
        headers=wix_headers,
        json=draft_body
    )

    if draft_response.status_code not in (200, 201):
        raise Exception(f"Wix draft creation failed: {draft_response.text}")

    draft_id = draft_response.json()["draftPost"]["id"]
    print(f"[WIX] Draft created: {draft_id}")

    print("[WIX] Publishing post...")
    publish_response = requests.post(
        f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}/publish",
        headers=wix_headers
    )

    if publish_response.status_code not in (200, 201):
        raise Exception(f"Wix publish failed: {publish_response.text}")

    post_id = publish_response.json().get("postId", draft_id)
    post_url = f"https://www.inneros.online/post/{title.lower().replace(' ', '-')}"
    print(f"[WIX] Published: {post_url}")
    return post_url

# ============================================================
# STEP 6: Publish to Instagram
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

    if "id" not in container:
        raise Exception(f"Instagram container error: {container}")

    container_id = container["id"]
    time.sleep(5)  # wait for container to be ready

    print("[INSTAGRAM] Publishing...")
    publish_response = requests.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
        data={
            "creation_id": container_id,
            "access_token": IG_TOKEN
        }
    )
    result = publish_response.json()

    if "id" not in result:
        raise Exception(f"Instagram publish error: {result}")

    print(f"[INSTAGRAM] Published: {result['id']}")
    return result["id"]

# ============================================================
# STEP 7: Publish to Facebook
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

    if "id" not in result:
        raise Exception(f"Facebook publish error: {result}")

    print(f"[FACEBOOK] Published: {result['id']}")
    return result["id"]

# ============================================================
# MAIN PIPELINE
# ============================================================

def build_ig_caption(instagram_text, article_url):
    hashtags = "#clarity #reflection #selfawareness #InnerOS #mindfulness #humandesign #AI"
    return f"{instagram_text}\n\nRead the full article → link in bio\n\n{hashtags}"

def build_fb_message(instagram_text, article_url):
    return f"{instagram_text}\n\nRead the full article → {article_url}"

def run_pipeline():
    print(f"\n{'='*60}")
    print(f"Clarity Lab Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # Step 1: Get topic
    index, rows, topic = get_next_topic()

    # Step 2: Generate content
    content = generate_content(topic)
    title       = content["title"]
    ig_text     = content["instagram"]
    website     = content["website"]

    # Step 3: Generate image
    image_url_raw = generate_image(title, topic["Core Observation"])

    # Step 4: Upload to Cloudinary
    image_url = upload_to_cloudinary(image_url_raw, title)

    # Step 5: Publish to Wix
    post_url = publish_to_wix(title, website, image_url)

    # Step 6: Publish to Instagram
    ig_caption = build_ig_caption(ig_text, post_url)
    publish_to_instagram(ig_caption, image_url)

    # Step 7: Publish to Facebook
    fb_message = build_fb_message(ig_text, post_url)
    publish_to_facebook(fb_message, image_url)

    # Step 8: Mark as published
    mark_topic_published(index, rows, post_url)

    print(f"\n{'='*60}")
    print(f"✅ Pipeline complete: {title}")
    print(f"   Article: {post_url}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_pipeline()
