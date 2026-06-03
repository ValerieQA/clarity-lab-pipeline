"""
Clarity Lab — Threads Pipeline
Runs Mon/Wed/Fri (same day as main pipeline) + Tue/Thu independently
Three content types in rotation: spark, question, thread_series
"""

import os
import csv
import re
import time
import requests
from datetime import datetime
from openai import OpenAI

# ============================================================
# CONFIG
# ============================================================

OPENAI_API_KEY     = os.environ["OPENAI_API_KEY"]
THREADS_USER_ID    = os.environ["THREADS_USER_ID"]
THREADS_TOKEN      = os.environ["THREADS_TOKEN"]

TOPICS_FILE        = "topics.csv"
PROMPT_FILE        = "config/prompt.md"

# Content types in rotation
CONTENT_TYPES = ["spark", "question", "thread_series"]

# ============================================================
# HELPERS
# ============================================================

def clean_markdown(text):
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'^[-*_]{3,}$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def truncate_to_limit(text, limit=500):
    if len(text) <= limit:
        return text
    return text[:limit-3].rsplit(' ', 1)[0] + "..."

# ============================================================
# STEP 1: Get topic
# ============================================================

def get_topic_for_threads():
    """
    On Mon/Wed/Fri: use last published topic (connects to article).
    On Tue/Thu: use last published topic but different angle.
    """
    rows = []
    with open(TOPICS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    published = [r for r in rows if r.get("Status", "").strip().lower() == "published"]

    if not published:
        # Fallback: use first ready topic
        ready = [r for r in rows if r.get("Status", "").strip().lower() in ("ready", "")]
        if not ready:
            raise Exception("No topics available in topics.csv")
        topic = ready[0]
        index = rows.index(topic)
    else:
        topic = published[-1]
        index = rows.index(topic)

    print(f"[THREADS] Topic: {topic['Topic / Working Title']}")
    return index, topic

def get_content_type(index):
    return CONTENT_TYPES[index % len(CONTENT_TYPES)]

# ============================================================
# STEP 2: Generate Threads content via GPT
# ============================================================

def generate_threads_content(topic_row, content_type):
    client = OpenAI(api_key=OPENAI_API_KEY)

    type_prompts = {

        "spark": """
Write one Spark post for Threads (like Twitter/X).

A Spark is:
- One sharp observation or insight
- 1-3 sentences maximum
- No explanation, no conclusion
- Reads like something you suddenly noticed
- Provokes recognition, not agreement
- Calm but precise — not aggressive, not soft
- Under 280 characters ideally, 500 max

The reader should feel: "I know this. I've never said it this way."

Do NOT:
- Give advice
- Use hashtags
- Use emojis
- Sound motivational
- Sound like a caption

Return ONLY the post text. Nothing else.
""",

        "question": """
Write one Question post for Threads.

A Question post is:
- One question, nothing else
- The question should have no obvious answer
- It should create a moment of genuine pause
- It should feel personal without being intimate
- It should connect to the topic without explaining the topic
- Under 200 characters ideally

The reader should feel: "I don't actually know the answer to this."

Do NOT:
- Add context or explanation
- Use rhetorical questions with obvious answers
- Sound like a quiz or survey
- Use hashtags or emojis

Return ONLY the question. Nothing else.
""",

        "thread_series": """
Write a Thread series for Threads (3-4 connected posts).

Structure:
Post 1: One observation that lands quietly. Sets the scene.
Post 2: The contradiction or tension inside that observation.
Post 3: One precise question that opens it up.
Post 4 (optional): Soft invitation — "Full reflection on the site. Link in bio."

Rules:
- Each post max 500 characters
- Posts connect but each can stand alone
- Tone: calm, editorial, precise, non-marketing
- No hashtags, no emojis
- The series should feel like one thought unfolding

Format your response exactly like this:
===POST1===
[text]
===POST2===
[text]
===POST3===
[text]
===POST4===
[text]
"""
    }

    prompt = f"""
You are writing for Clarity Lab — a reflective AI assistant brand.

Brand voice: quiet, precise, human, non-marketing, editorial.
Platform: Threads (like Twitter — fast, text-first, conversational).

Topic: {topic_row['Topic / Working Title']}
Core observation: {topic_row['Core Observation']}
Audience question: {topic_row['Audience Question']}

{type_prompts[content_type]}
"""

    print(f"[GPT] Generating Threads content (type: {content_type})...")
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.8
    )

    text = response.choices[0].message.content.strip()
    print(f"[GPT] Content generated")
    return text

# ============================================================
# STEP 3: Parse thread series
# ============================================================

def parse_thread_series(raw_text):
    patterns = {
        "post1": r"===POST1===\s*(.*?)(?====|\Z)",
        "post2": r"===POST2===\s*(.*?)(?====|\Z)",
        "post3": r"===POST3===\s*(.*?)(?====|\Z)",
        "post4": r"===POST4===\s*(.*?)(?====|\Z)",
    }
    posts = []
    for key in ["post1", "post2", "post3", "post4"]:
        match = re.search(patterns[key], raw_text, re.DOTALL)
        if match:
            text = match.group(1).strip()
            if text:
                posts.append(text)
    return posts

# ============================================================
# STEP 4: Publish to Threads
# ============================================================

def create_threads_container(text, reply_to_id=None):
    """Create a single Threads media container."""
    params = {
        "text": truncate_to_limit(clean_markdown(text)),
        "media_type": "TEXT",
        "access_token": THREADS_TOKEN
    }
    if reply_to_id:
        params["reply_to_id"] = reply_to_id

    response = requests.post(
        f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads",
        data=params
    )
    result = response.json()

    if "error" in result:
        raise Exception(f"[THREADS] Container error: {result['error']['message']}")
    if "id" not in result:
        raise Exception(f"[THREADS] Unexpected response: {result}")

    return result["id"]

def publish_threads_container(container_id):
    """Publish a created container."""
    response = requests.post(
        f"https://graph.threads.net/v1.0/{THREADS_USER_ID}/threads_publish",
        data={
            "creation_id": container_id,
            "access_token": THREADS_TOKEN
        }
    )
    result = response.json()

    if "error" in result:
        raise Exception(f"[THREADS] Publish error: {result['error']['message']}")
    if "id" not in result:
        raise Exception(f"[THREADS] Unexpected publish response: {result}")

    return result["id"]

def publish_single_post(text):
    """Create and publish one Threads post."""
    container_id = create_threads_container(text)
    time.sleep(3)
    post_id = publish_threads_container(container_id)
    print(f"[THREADS] Post published: {post_id}")
    return post_id

def publish_thread_series(posts):
    """
    Publish a thread series.
    Each post replies to the previous one.
    """
    print(f"[THREADS] Publishing thread series ({len(posts)} posts)...")
    post_ids = []
    reply_to_id = None

    for i, post_text in enumerate(posts):
        print(f"[THREADS] Publishing post {i+1}/{len(posts)}...")
        container_id = create_threads_container(post_text, reply_to_id=reply_to_id)
        time.sleep(3)
        post_id = publish_threads_container(container_id)
        post_ids.append(post_id)
        reply_to_id = post_id  # each post replies to previous
        time.sleep(5)  # small delay between posts

    print(f"[THREADS] Thread series published: {len(post_ids)} posts")
    return post_ids

# ============================================================
# MAIN
# ============================================================

def run_threads_pipeline():
    print(f"\n{'='*60}")
    print(f"Clarity Lab Threads Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    index, topic = get_topic_for_threads()
    content_type = get_content_type(index)
    print(f"[THREADS] Content type: {content_type}")

    raw_content = generate_threads_content(topic, content_type)

    if content_type == "thread_series":
        posts = parse_thread_series(raw_content)
        if not posts:
            raise Exception("[THREADS] Failed to parse thread series")
        publish_thread_series(posts)
    else:
        publish_single_post(raw_content)

    print(f"\n{'='*60}")
    print(f"✅ Threads published!")
    print(f"   Topic: {topic['Topic / Working Title']}")
    print(f"   Type: {content_type}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    run_threads_pipeline()
