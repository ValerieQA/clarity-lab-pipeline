"""
Clarity Lab — Automated Content Pipeline
Fixed: visual_index from published_count, removed undefined variables
"""

import os
import csv
import re
import time
import base64
import tempfile
import requests
import logging
from datetime import datetime
from openai import OpenAI
from PIL import Image
import numpy as np
import cloudinary
import cloudinary.uploader

from content_validation import ContentValidationError, parse_article_sections
from http_utils import HttpClient, response_json_or_raise, summarize_response
from publication_state import PublicationState, write_topics
from meta_tokens import validate_facebook_token, validate_instagram_token
from runtime_config import FacebookConfig, FeatureFlags, InstagramConfig
from structured_logging import get_logger, log_event
from prompt_loader import (
    load_prompt,
    load_prompt_with_scenes,
    load_hashtags,
    load_visual_journey,
    load_accent_states,
    load_subject_families,
    load_compositions,
    load_light_states,
    IMAGE_PROMPT_PATH,
    INSTAGRAM_PROMPT_PATH,
    FACEBOOK_PROMPT_PATH,
)

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

FLAGS = FeatureFlags.from_env()
LOGGER = get_logger("pipeline")
HTTP = HttpClient.from_flags(FLAGS, LOGGER)
INSTAGRAM_CONFIG = InstagramConfig.from_env()
FACEBOOK_CONFIG = FacebookConfig.from_env()

# ============================================================
# VISUAL SYSTEM
# Loaded from config/IMAGE_PROMPT.md — edit the file to update palettes/moods.
# visual_index = published_count % len(VISUAL_JOURNEY)
# where published_count = number of rows in topics.csv with Status == "Published"
# ============================================================

VISUAL_JOURNEY   = load_visual_journey()
ACCENT_STATES    = load_accent_states()
SUBJECT_FAMILIES = load_subject_families()
COMPOSITIONS     = load_compositions()
LIGHT_STATES     = load_light_states()


def _cycle(items, index, fallback):
    """Item by index, wrapping. Never raises on an empty list."""
    return items[index % len(items)] if items else fallback

def get_visual_state(index):
    return VISUAL_JOURNEY[index % len(VISUAL_JOURNEY)]

def get_accent_state(index):
    if index % 3 == 0:
        return ACCENT_STATES[index % len(ACCENT_STATES)]
    return "no strong accent, only subtle natural variation"

# ============================================================
# HELPERS
# ============================================================

def check_response(response, step_name):
    return response_json_or_raise(response, step_name)

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

def mark_topic_state(index, rows, post_url, master_image_url, state: PublicationState):
    final_status = state.finalize().value
    rows[index]["Pipeline State"] = final_status
    rows[index]["Workflow Status"] = "Complete" if final_status == "completed" else final_status
    rows[index]["Status"] = "Published" if final_status == "completed" else "Partial Failure" if final_status == "partial_failure" else rows[index].get("Status", "Ready")
    rows[index]["Website Published URL"] = post_url
    rows[index]["Publish Status Code"] = "200" if final_status == "completed" else "207" if final_status == "partial_failure" else "500"
    errors = []
    for platform, result in state.platform_results.items():
        rows[index][f"{platform.capitalize()} Status"] = result.status
        if platform == "threads" and result.external_id:
            rows[index]["Threads External ID"] = result.external_id
        if result.error:
            errors.append(f"{platform}: {result.error[:200]}")
    rows[index]["Publication Errors"] = " | ".join(errors)

    write_topics(TOPICS_FILE, rows)
    print(f"[TOPICS] State updated to {final_status}")

# ============================================================
# STEP 2: Generate content via GPT
# ============================================================

def generate_content(topic_row):
    client = OpenAI(api_key=OPENAI_API_KEY, max_retries=FLAGS.http_max_retries, timeout=FLAGS.http_timeout_seconds)
    base_prompt = load_prompt(PROMPT_FILE)

    user_message = (
        f"Topic: {topic_row['Topic / Working Title']}\n"
        f"Core observation: {topic_row['Core Observation']}\n"
        f"Audience question: {topic_row['Audience Question']}\n"
        f"Content pillar: {topic_row['Content Pillar']}\n"
    )

    last_error = None
    for attempt in range(1, FLAGS.http_max_retries + 1):
        print(f"[GPT] Generating article content (attempt {attempt})...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": base_prompt + "\n\n" + user_message}],
            max_tokens=2000,
            temperature=0.7
        )

        raw = response.choices[0].message.content
        try:
            content = parse_content(raw)
            print("[GPT] Content generated and validated successfully")
            return content
        except ContentValidationError as exc:
            last_error = exc
            log_event(LOGGER, "article_output_invalid", logging.WARNING, platform="openai", status="retrying", error=str(exc))
    raise Exception(f"[GPT] Article output remained invalid after retries: {last_error}")

def parse_content(raw_text):
    sections = parse_article_sections(raw_text)
    print(f"[PARSE] Title: {sections['title']}")
    return sections

def _recent_scene_ids(rows, limit: int = 40) -> str:
    """Scene codes used in recent publications, so the model does not repeat one."""
    ids = [r.get("Scene ID", "").strip() for r in rows if r.get("Scene ID", "").strip()]
    return ", ".join(ids[-limit:]) if ids else "none yet"


def generate_channel_text(prompt_path, topic_row, website_url, recent_scenes, max_tokens=400):
    """Channel-specific text written from that channel's own prompt file."""
    client = OpenAI(api_key=OPENAI_API_KEY,
                    max_retries=FLAGS.http_max_retries,
                    timeout=FLAGS.http_timeout_seconds)

    filled = load_prompt_with_scenes(prompt_path).format(
        title=topic_row.get("Topic / Working Title", ""),
        core_observation=topic_row.get("Core Observation", ""),
        audience_question=topic_row.get("Audience Question", ""),
        content_pillar=topic_row.get("Content Pillar", ""),
        website_url=website_url or "",
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content":
                   f"{filled}\n\nScenes already used recently \u2014 do not reuse: {recent_scenes}"}],
        max_tokens=max_tokens,
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


# ============================================================
# STEP 3: Generate image via gpt-image-1
# ============================================================

def generate_image(title, core_observation, visual_state, accent_state,
                   subject_state, composition_state, light_state):
    client = OpenAI(api_key=OPENAI_API_KEY)

    base_image_prompt = load_prompt(IMAGE_PROMPT_PATH)
    image_prompt = base_image_prompt.format(
        title=title,
        core_observation=core_observation,
        visual_state_name=visual_state["name"],
        visual_state_mood=visual_state["mood"],
        visual_state_palette=visual_state["palette"],
        accent_state=accent_state,
        subject_state=subject_state,
        composition_state=composition_state,
        light_state=light_state,
    )

    print(f"[GPT-IMAGE] Generating image (visual: {visual_state['name']})...")
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
    if FLAGS.dry_run:
        planned_url = f"dry-run://cloudinary/{public_id}.jpg"
        log_event(LOGGER, "dry_run_cloudinary_upload_skipped", platform="cloudinary", status="skipped", details={"public_id": public_id})
        print(f"[DRY RUN][CLOUDINARY] Would upload image as {public_id}")
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
            log_event(LOGGER, "cloudinary_upload_retry", logging.WARNING, platform="cloudinary", status="retrying", error=str(exc))
            time.sleep(2 ** (attempt - 1))
    else:
        raise last_error

    secure_url = result.get("secure_url")
    if not secure_url:
        raise Exception("[CLOUDINARY] No URL returned")

    print(f"[CLOUDINARY] Uploaded: {secure_url[:70]}...")
    return secure_url

# ============================================================
# STEP 6: Import image to Wix Media
# ============================================================

def import_image_to_wix(cloudinary_url, title, wix_headers):
    print("[WIX MEDIA] Importing image...")

    safe_title = re.sub(r'[^a-zA-Z0-9_\-]', '_', title)[:50]

    response = HTTP.post(
        "https://www.wixapis.com/site-media/v1/files/import",
        platform="wix",
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
    response = HTTP.post(
        "https://www.wixapis.com/ricos/v1/ricos-document/convert/to-ricos",
        platform="wix",
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

    if FLAGS.dry_run or not FLAGS.enable_wix_publishing:
        log_event(LOGGER, "wix_publish_skipped", platform="wix", status="skipped", details={"dry_run": FLAGS.dry_run, "enabled": FLAGS.enable_wix_publishing, "title": title})
        print(f"[DRY RUN][WIX] Would publish article: {title}")
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        return f"dry-run://wix/post/{slug}"

    wix_file_id, wix_url = import_image_to_wix(cloudinary_url, title, wix_headers)

    html_content = text_to_html(website_text)
    rich_content = convert_html_to_ricos(html_content, wix_headers)
    clean_text = clean_markdown(website_text)
    excerpt = " ".join(clean_text.split()[:40]) + "..."

    print("[WIX] Creating draft post...")
    draft_response = HTTP.post(
        "https://www.wixapis.com/blog/v3/draft-posts",
        platform="wix",
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
                "categoryIds": ["30d2d3ab-fde8-4f90-b197-15d126335622"],
                "memberId": "4d7e0085-753e-4aee-b7c6-ed66431fd9c6"
            }
        }
    )
    draft_data = check_response(draft_response, "WIX CREATE DRAFT")
    draft_id = draft_data.get("draftPost", {}).get("id")
    if not draft_id:
        raise Exception(f"[WIX] No draft ID: {draft_data}")
    print(f"[WIX] Draft created: {draft_id}")

    check_response(
        HTTP.get(f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}", platform="wix", headers=wix_headers),
        "WIX VERIFY DRAFT"
    )
    print("[WIX] Draft verified OK")

    check_response(
        HTTP.post(f"https://www.wixapis.com/blog/v3/draft-posts/{draft_id}/publish", platform="wix", headers=wix_headers),
        "WIX PUBLISH"
    )

    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    post_url = f"https://www.inneros.online/post/{slug}"
    print(f"[WIX] Published: {post_url}")
    return post_url

# ============================================================
# STEP 8: Publish to Instagram
# ============================================================

def publish_to_instagram(caption, image_url):
    print("[INSTAGRAM] Creating container...")
    if FLAGS.dry_run or not FLAGS.enable_instagram_publishing:
        log_event(LOGGER, "instagram_publish_skipped", platform="instagram", status="skipped", details={"dry_run": FLAGS.dry_run, "enabled": FLAGS.enable_instagram_publishing, "caption_preview": caption[:160]})
        print("[DRY RUN][INSTAGRAM] Would publish image post")
        return "dry-run-instagram-id"

    # Pre-publish token validation — skip platform rather than fail entire pipeline.
    _ig_check = validate_instagram_token(INSTAGRAM_CONFIG, HTTP, LOGGER)
    if not _ig_check.valid:
        log_event(LOGGER, "instagram_token_invalid_skipping", logging.ERROR, platform="instagram",
                  status="skipped", error=_ig_check.error)
        print(f"[INSTAGRAM] Token invalid — skipping publish. Run retry after fixing IG_TOKEN secret.")
        raise Exception(f"[INSTAGRAM] Token invalid ({_ig_check.status}): {_ig_check.error}")

    container_response = HTTP.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media",
        platform="instagram",
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

    result = HTTP.post(
        f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish",
        platform="instagram",
        data={"creation_id": container_id, "access_token": IG_TOKEN}
    ).json()

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
    if FLAGS.dry_run or not FLAGS.enable_facebook_publishing:
        log_event(LOGGER, "facebook_publish_skipped", platform="facebook", status="skipped", details={"dry_run": FLAGS.dry_run, "enabled": FLAGS.enable_facebook_publishing, "message_preview": message[:160]})
        print("[DRY RUN][FACEBOOK] Would publish photo post")
        return "dry-run-facebook-id"

    # Pre-publish token validation — skip platform rather than fail entire pipeline.
    _fb_check = validate_facebook_token(FACEBOOK_CONFIG, HTTP, LOGGER)
    if not _fb_check.valid:
        log_event(LOGGER, "facebook_token_invalid_skipping", logging.ERROR, platform="facebook",
                  status="skipped", error=_fb_check.error)
        print(f"[FACEBOOK] Token invalid — skipping publish. Run retry after fixing FB_PAGE_TOKEN secret.")
        raise Exception(f"[FACEBOOK] Token invalid ({_fb_check.status}): {_fb_check.error}")

    result = HTTP.post(
        f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos",
        platform="facebook",
        data={"url": image_url, "message": message, "access_token": FB_PAGE_TOKEN}
    ).json()

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
    log_event(LOGGER, "pipeline_started", status="dry_run" if FLAGS.dry_run else "running", details=FLAGS.__dict__)

    index, rows, topic, visual_index = get_next_topic()
    state = PublicationState(topic_id=topic.get("ID", ""))

    visual_state      = get_visual_state(visual_index)
    accent_state      = get_accent_state(visual_index)
    subject_state     = _cycle(SUBJECT_FAMILIES, visual_index,
                               "an ordinary surface, closely observed")
    composition_state = _cycle(COMPOSITIONS, visual_index,
                               "one object off centre, most of the frame empty")
    light_state       = _cycle(LIGHT_STATES, visual_index,
                               "one window, bright near it, falling off into shadow")
    print(f"[VISUAL] {visual_state['name']} | subject {visual_index % max(len(SUBJECT_FAMILIES), 1)}"
          f" | comp {visual_index % max(len(COMPOSITIONS), 1)}"
          f" | light {visual_index % max(len(LIGHT_STATES), 1)}")

    content = generate_content(topic)
    title   = content["title"]
    ig_text = content["instagram"]
    website = content["website"]

    raw_image_path = generate_image(
        title, topic["Core Observation"], visual_state, accent_state,
        subject_state, composition_state, light_state,
    )
    branded_image_path = overlay_logo(raw_image_path)

    cloudinary_url = upload_to_cloudinary(branded_image_path, title)

    post_url = ""
    if FLAGS.enable_wix_publishing or FLAGS.dry_run:
        try:
            post_url = publish_to_wix(title, website, cloudinary_url)
            state.set_platform("wix", FLAGS.enable_wix_publishing and not FLAGS.dry_run, "published", url=post_url)
        except Exception as exc:
            state.set_platform("wix", FLAGS.enable_wix_publishing and not FLAGS.dry_run, "failed", error=str(exc))
            log_event(LOGGER, "wix_publish_failed", logging.ERROR, platform="wix", status="failed", error=str(exc))
    else:
        state.set_platform("wix", False, "skipped")

    recent_scenes = _recent_scene_ids(rows)

    try:
        ig_text = generate_channel_text(INSTAGRAM_PROMPT_PATH, topic, post_url, recent_scenes)
    except Exception as exc:
        log_event(LOGGER, "instagram_text_fallback", logging.WARNING,
                  platform="openai", status="fallback", error=str(exc))

    try:
        fb_message = generate_channel_text(FACEBOOK_PROMPT_PATH, topic, post_url, recent_scenes)
    except Exception as exc:
        log_event(LOGGER, "facebook_text_fallback", logging.WARNING,
                  platform="openai", status="fallback", error=str(exc))
        fb_message = f"{ig_text}\n\n{post_url}"

    hashtags   = load_hashtags()
    ig_caption = f"{ig_text}\n\n{hashtags}".strip()

    # Save captions at generation time — before any publish attempt.
    if not FLAGS.dry_run:
        rows[index]["IG Caption"]      = ig_caption
        rows[index]["FB Message"]      = fb_message
        rows[index]["Master Image URL"] = cloudinary_url
        write_topics(TOPICS_FILE, rows)

    try:
        ig_id = publish_to_instagram(ig_caption, cloudinary_url)
        state.set_platform("instagram", FLAGS.enable_instagram_publishing and not FLAGS.dry_run, "published", external_id=ig_id)
    except Exception as exc:
        state.set_platform("instagram", FLAGS.enable_instagram_publishing and not FLAGS.dry_run, "failed", error=str(exc))
        log_event(LOGGER, "instagram_publish_failed", logging.ERROR, platform="instagram", status="failed", error=str(exc))

    try:
        fb_id = publish_to_facebook(fb_message, cloudinary_url)
        state.set_platform("facebook", FLAGS.enable_facebook_publishing and not FLAGS.dry_run, "published", external_id=fb_id)
    except Exception as exc:
        state.set_platform("facebook", FLAGS.enable_facebook_publishing and not FLAGS.dry_run, "failed", error=str(exc))
        log_event(LOGGER, "facebook_publish_failed", logging.ERROR, platform="facebook", status="failed", error=str(exc))

    state.set_platform("threads", FLAGS.enable_threads_publishing and not FLAGS.dry_run, "skipped")
    if FLAGS.dry_run:
        print("[DRY RUN] topics.csv will not be updated")
    else:
        mark_topic_state(index, rows, post_url, cloudinary_url, state)

    final_status = state.finalize().value
    failed = [p for p, r in state.platform_results.items() if r.status == "failed"]

    print(f"\n{'='*60}")
    if failed:
        print(f"⚠️  Done with failures! {title}")
        print(f"   {post_url}")
        print(f"   Failed platforms: {', '.join(failed)}")
    else:
        print(f"✅ Done! {title}")
        print(f"   {post_url}")
    print(f"{'='*60}\n")

    if final_status == "partial_failure":
        raise SystemExit(1)

if __name__ == "__main__":
    run_pipeline()
