"""HEEEXY Lab feed: finds strong, free, openly licensed AI projects on GitHub and Hugging Face
and sends them to https://heeexy.app/lab. Runs daily on GitHub Actions; standard library only.

Environment: GITHUB_TOKEN (Actions token, read-only search), LAB_INGEST_SECRET (shared with the site).
Use --dry-run to print what would be sent.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

SITE = os.environ.get("LAB_SITE", "https://heeexy.app")
LICENSES = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "mpl-2.0", "unlicense", "cc0-1.0", "0bsd", "cc-by-4.0"}
TODAY = dt.date.today()
PUSHED = (TODAY - dt.timedelta(days=120)).isoformat()
NEW = (TODAY - dt.timedelta(days=45)).isoformat()

# (kind, topic shown on the site, GitHub search query)
SEARCHES = [
    ("mcp", "MCP servers", "topic:mcp-server stars:>=300"),
    ("mcp", "MCP servers", "topic:model-context-protocol stars:>=300"),
    ("skill", "Agent skills", "topic:claude-skills stars:>=40"),
    ("skill", "Agent skills", "topic:agent-skills stars:>=40"),
    ("skill", "Agent skills", "topic:claude-code stars:>=500"),
    ("agent", "AI agents", "topic:ai-agents stars:>=3000"),
    ("agent", "AI agents", "topic:autonomous-agents stars:>=2000"),
    ("agent", "AI agents", "topic:multi-agent stars:>=2000"),
    ("tool", "LLM apps", "topic:llm stars:>=8000"),
    ("tool", "Generative AI", "topic:generative-ai stars:>=5000"),
    ("tool", "RAG & search", "topic:rag stars:>=3000"),
    ("tool", "Local AI", "topic:local-llm stars:>=1500"),
    ("tool", "Image generation", "topic:stable-diffusion stars:>=4000"),
    ("tool", "Voice & audio AI", "topic:text-to-speech stars:>=3000"),
    ("tool", "New on GitHub", f"topic:ai created:>={NEW} stars:>=400"),
    ("tool", "New on GitHub", f"topic:llm created:>={NEW} stars:>=400"),
    ("automation", "Automation", "topic:n8n stars:>=200"),
    ("automation", "Automation", "topic:workflow-automation stars:>=2000"),
    ("automation", "Automation", "topic:browser-automation stars:>=2000"),
    ("prompt", "Prompts", "topic:prompt-engineering stars:>=1500"),
    ("prompt", "Prompts", "topic:prompts stars:>=1500"),
    ("course", "Learn AI", "topic:llm-course stars:>=500"),
    ("course", "Learn AI", "topic:awesome-list topic:llm stars:>=1500"),
    ("course", "Learn AI", "topic:awesome-list topic:artificial-intelligence stars:>=3000"),
    ("template", "Templates", "topic:ai-template stars:>=300"),
]

SINGLE = {
    "mcp": "MCP server", "skill": "agent skill", "agent": "AI agent framework", "tool": "AI tool",
    "automation": "automation project", "prompt": "prompt collection", "course": "learning resource",
    "template": "template", "model": "open model",
}
UPPER = {"ai", "llm", "llms", "mcp", "api", "ui", "ux", "gpt", "rag", "sdk", "cli", "ocr", "tts", "stt", "pdf", "sql", "seo", "ml", "nlp", "gui", "os", "vlm", "n8n"}


def http_json(url, headers=None, data=None, method=None):
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "heeexy-lab-feed", **(headers or {})})
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.loads(response.read().decode("utf-8"))


def humanize(name, keep_dots=False):
    words = re.split(r"[-_\s]+" if keep_dots else r"[-_\s.]+", name)
    out = []
    for word in words:
        if not word:
            continue
        low = word.lower()
        out.append(low.upper() if low in UPPER else (word if any(c.isupper() for c in word[1:]) else word[:1].upper() + word[1:]))
    return " ".join(out)[:120]


def clean_text(text):
    text = re.sub(r"[\U00010000-\U0010FFFF☀-➿️]", "", text or "")
    text = re.sub(r":[a-z0-9_+-]+:", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Drop sentences with links or calls to join/follow: they read as spam on a product page.
    parts = re.split(r"(?<=[.!?])\s+|\s+[|·•]\s+", text)
    kept = [part for part in parts if part and not PROMO.search(part)]
    text = " ".join(kept).strip(" -:|,")
    return text if not text or text.endswith((".", "!", "?")) else text + "."


PROMO = re.compile(r"https?://|www\.|discord|join (us|here|our)|follow (us|here)|star (us|this)|subscribe|telegram|wechat|twitter|x\.com", re.I)


def mostly_english(text):
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 20 and sum(1 for c in letters if c.isascii()) / len(letters) > 0.9


def github_items():
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    seen, items = set(), []
    for kind, topic, query in SEARCHES:
        q = f"{query} archived:false pushed:>={PUSHED}"
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": q, "sort": "stars", "order": "desc", "per_page": 30})
        try:
            data = http_json(url, headers)
        except Exception as error:  # one failed search never stops the feed
            print(f"search failed ({query}): {error}", file=sys.stderr)
            continue
        time.sleep(2.5)  # search API: 30 requests a minute
        for repo in data.get("items", []):
            full = repo["full_name"].lower()
            license_id = ((repo.get("license") or {}).get("spdx_id") or "").lower()
            desc = clean_text(repo.get("description"))
            if full in seen or license_id not in LICENSES or repo.get("fork") or not mostly_english(desc) or len(desc) < 30:
                continue
            seen.add(full)
            owner, name = repo["full_name"].split("/", 1)
            title = humanize(name)
            if " " not in title and len(title) < 9 and owner.lower() != name.lower():  # "Editor" -> "Pascalorg Editor", but "ollama/ollama" stays "Ollama"
                title = f"{humanize(owner)} {title}"
            stars = int(repo.get("stargazers_count") or 0)
            topics = ", ".join((repo.get("topics") or [])[:8])
            pushed = (repo.get("pushed_at") or "")[:10]
            details = "\n".join(filter(None, [
                f"{title} is a free, open-source {SINGLE[kind]} published on GitHub by {owner}.",
                "",
                desc,
                "",
                f"GitHub stars: {stars:,}",
                f"License: {repo['license'].get('spdx_id')} (free to use)",
                f"Language: {repo.get('language')}" if repo.get("language") else "",
                f"Topics: {topics}" if topics else "",
                f"Last updated: {pushed}" if pushed else "",
                "",
                "How to get it: open the repository on GitHub, read the README and follow the setup steps. "
                "HEEEXY lists it in the Lab because it is popular, actively maintained and openly licensed.",
            ]))
            items.append({
                "sourceUrl": repo["html_url"],
                "title": title,
                "summary": desc[:300],
                "details": details,
                "kind": kind,
                "topic": topic,
                "author": owner[:80],
                "installCommand": None,
                "docsUrl": repo.get("homepage") if (repo.get("homepage") or "").startswith("https://") else None,
                "stars": stars,
            })
    return items


TASKS = {
    "text-generation": "text generation", "image-text-to-text": "vision-language", "text-to-image": "image generation",
    "text-to-speech": "text-to-speech", "automatic-speech-recognition": "speech recognition", "text-to-video": "video generation",
    "image-to-video": "image-to-video", "feature-extraction": "embeddings", "image-segmentation": "image segmentation",
    "any-to-any": "multimodal", "image-to-image": "image editing", "text-to-audio": "audio generation",
}


def huggingface_items():
    url = "https://huggingface.co/api/models?" + urllib.parse.urlencode({"sort": "trendingScore", "direction": "-1", "limit": "100"})
    try:
        models = http_json(url)
    except Exception as error:
        print(f"huggingface failed: {error}", file=sys.stderr)
        return []
    items = []
    for model in models:
        tags = model.get("tags") or []
        license_id = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), "")
        task = TASKS.get(model.get("pipeline_tag") or "")
        if license_id not in LICENSES or not task or model.get("gated") or model.get("private"):
            continue
        org, name = model["id"].split("/", 1) if "/" in model["id"] else ("", model["id"])
        if not org:
            continue
        likes = int(model.get("likes") or 0)
        downloads = int(model.get("downloads") or 0)
        if likes < 150:
            continue
        title = humanize(name, keep_dots=True)
        summary = f"{title} by {org}: a free, openly licensed {task} model on Hugging Face ({license_id.upper()})."
        details = "\n".join([
            f"{title} is an open {task} model published on Hugging Face by {org}.",
            "",
            f"Task: {task}",
            f"License: {license_id.upper()} (free to use, check the model card for conditions)",
            f"Likes on Hugging Face: {likes:,}",
            f"Downloads last month: {downloads:,}",
            "",
            "How to use it: open the model page on Hugging Face, read the model card and try it with the "
            "Transformers library, Ollama, or a hosted inference provider. HEEEXY lists trending open models in the Lab.",
        ])
        items.append({
            "sourceUrl": f"https://huggingface.co/{model['id']}",
            "title": title,
            "summary": summary[:300],
            "details": details,
            "kind": "model",
            "topic": task.capitalize(),
            "author": org[:80],
            "installCommand": None,
            "docsUrl": None,
            "stars": likes,
        })
    return items


def main():
    items = github_items() + huggingface_items()
    print(f"found {len(items)} candidates")
    if "--dry-run" in sys.argv:
        for item in items[:400]:
            print(f"{item['kind']:10} {item['stars']:>8}  {item['title']}  <{item['sourceUrl']}>")
        return
    secret = os.environ["LAB_INGEST_SECRET"]
    added = updated = 0
    for start in range(0, len(items), 50):
        body = json.dumps({"items": items[start:start + 50]}).encode("utf-8")
        result = http_json(f"{SITE}/api/lab/ingest", {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}, body, "POST")
        added += int(result.get("added", 0))
        updated += int(result.get("updated", 0))
    print(f"added {added}, updated {updated}")


if __name__ == "__main__":
    main()
