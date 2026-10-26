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
import urllib.error
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


# ---------------------------------------------------------------------------------------------
# Automation workflows: free n8n templates (official gallery API) and Make templates (public pages).
# We never copy the workflow JSON or the authors' long descriptions: each item gets a short text that
# we compose from facts (trigger, apps, AI nodes) and a link to the official template page.
# ---------------------------------------------------------------------------------------------

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
WORKFLOW_CAP = int(os.environ.get("LAB_WORKFLOW_CAP", "300"))   # new workflow pages per run, so indexing stays sane
MAKE_SHARE = 3                                                    # Make gets 1/3 of the cap, n8n the rest
N8N_PAGE = "https://api.n8n.io/api/templates/search"
N8N_DETAIL = "https://api.n8n.io/api/templates/workflows/"
MAKE_SITEMAP = "https://www.make.com/sitemaps/templates.xml"
REFRESH_ITEMS = 40            # newest known n8n templates re-sent each run so edits by their authors reach the site
MAX_N8N_PAGES = 160           # 100 templates per page; ~14,000 templates exist
PAUSE = 0.7                   # seconds between requests to the same host

WF_GENERIC_APPS = {
    "http request", "code", "set", "edit fields", "if", "switch", "merge", "wait", "sticky note", "no operation, do nothing",
    "respond to webhook", "split out", "aggregate", "loop over items", "filter", "sort", "limit", "date & time", "function",
    "execute workflow", "execute workflow trigger", "remove duplicates", "summarize", "convert to file", "extract from file",
    "html", "xml", "markdown", "crypto", "rename keys", "compare datasets", "stop and error", "error trigger", "webhook",
    "schedule trigger", "manual trigger", "chat trigger", "when chat message received", "form trigger", "n8n form trigger",
}
WF_LANGCHAIN_GENERIC = re.compile(r"\.(agent|agentTool|chainLlm|chainSummarization|chainRetrievalQa|memory\w*|outputParser\w*|textSplitter\w*|documentDefaultDataLoader|toolWorkflow|toolCode|toolHttpRequest|toolThink|toolCalculator|retrieverVectorStore|informationExtractor|textClassifier|sentimentAnalysis|mcpClientTool|mcpTrigger|chatTrigger|manualChatTrigger|chat|openAiAssistant|guardrails)$", re.I)
WF_STRIP = re.compile(r"\s+(Chat Model|Trigger|Tool|Embeddings|Vector Store|Document Loader|Model|Request|API|Node)$", re.I)
WF_SKIP_CATEGORIES = {"app families", "built-in apps", "built in apps", "other"}


def wf_request(url, as_text=False):
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read().decode("utf-8", "replace")
            return raw if as_text else json.loads(raw)
        except urllib.error.HTTPError as error:
            last = error
            if error.code in (400, 401, 403, 404, 410):  # retrying will not help
                break
            time.sleep(8 * (attempt + 1))  # 429 / 5xx: wait and try again politely
        except Exception as error:  # network hiccup
            last = error
            time.sleep(3)
    raise last


def wf_base(name):
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"[^\x00-\x7f]", " ", name or "").lower()).strip("-")


def wf_slug(platform, template_id, name):
    base = wf_base(name)
    slug = f"{platform}-{template_id}" + (f"-{base}" if base else "")
    if len(slug) > 80:
        slug = slug[:81].rsplit("-", 1)[0] if slug[80] != "-" else slug[:80]  # never end in half a word
        slug = slug if slug.count("-") >= 2 else f"{platform}-{template_id}"
    return slug.rstrip("-")


def wf_clean_name(name):
    name = re.sub(r"[\U00010000-\U0010FFFF☀-➿️]", "", name or "")
    name = re.sub(r"https?://\S+|www\.\S+", "", name)
    name = re.sub(r"\s+", " ", name).strip(" -:|,.")
    return name[:140]


def wf_join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def wf_pretty_app(display):
    display = re.sub(r"\s+", " ", display or "").strip().replace(",", " ")
    shorter = WF_STRIP.sub("", display).strip()
    return shorter if len(shorter) >= 2 else display


def wf_sentences(platform_label, apps, trigger, uses_ai, author):
    """Short original text built from facts only: 'summary' (card/meta description) and the page paragraph."""
    where = f"connects {wf_join(apps[:4])}" if apps else "relies on built-in nodes and web requests"
    summary = f"A free {platform_label} workflow that {trigger + ' and ' if trigger else ''}{where}" + (" with AI steps" if uses_ai else "") + "."
    body = [
        f"This free {platform_label} automation template {trigger + ' and ' if trigger else ''}{where}.",
        "It uses language-model or agent nodes, so you will need an API key from your AI provider." if uses_ai else "",
        f"Shared by {author} on the official {platform_label} template gallery." if author else "",
        f"Open the official template page to copy it into your own {platform_label} account, then connect your own credentials before switching it on.",
    ]
    return summary[:300], " ".join(part for part in body if part)


def n8n_trigger_phrase(node_types):
    """node_types: every node type used by the template (workflowInfo.nodeTypes), e.g. 'n8n-nodes-base.scheduleTrigger'."""
    types = [t.split(".")[-1] for t in node_types]
    lowered = [t.lower() for t in types]
    specials = [
        ("webhook", "starts when a webhook is called"), ("scheduletrigger", "runs on a schedule"), ("cron", "runs on a schedule"),
        ("chattrigger", "starts from a chat message"), ("formtrigger", "starts from a form submission"),
        ("manualtrigger", "is started by hand"), ("executeworkflowtrigger", "runs as a sub-workflow"),
    ]
    for key, phrase in specials:
        if key in lowered:
            return phrase
    for original, low in zip(types, lowered):
        if low.endswith("trigger") and low not in ("errortrigger",):
            service = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", original[: -len("Trigger")]).strip()
            service = service[:1].upper() + service[1:]
            if service:
                return f"starts from a {service} event"
    return ""


def n8n_apps(nodes):
    apps, seen = [], set()
    for node in nodes:
        name = node.get("name") or ""
        cats = {c.get("name") for c in (node.get("nodeCategories") or [])}
        if "Core Nodes" in cats or "Helpers" in cats:
            continue
        if name.startswith("@n8n/n8n-nodes-langchain.") and WF_LANGCHAIN_GENERIC.search(name):
            continue
        shown = wf_pretty_app(node.get("displayName") or "")
        key = shown.lower()
        if not shown or key in seen or key in WF_GENERIC_APPS:
            continue
        seen.add(key)
        apps.append(shown)
    return apps[:10]


def n8n_is_free(workflow):
    return not workflow.get("price") and not workflow.get("purchaseUrl")


def n8n_item(workflow):
    """Full item for one template (one detail request for its categories and author)."""
    template_id = workflow["id"]
    name = wf_clean_name(workflow.get("name"))
    if not name:
        return None
    slug = wf_slug("n8n", template_id, name)
    detail = wf_request(f"{N8N_DETAIL}{template_id}").get("workflow", {})
    time.sleep(PAUSE)
    nodes = workflow.get("nodes") or detail.get("nodes") or []
    cats = [c.get("name") for c in (detail.get("categories") or []) if c.get("name")]
    topic = (cats[0] if cats else "") or ("AI" if any("langchain" in (n.get("name") or "") for n in nodes) else "Automation")
    apps = n8n_apps(nodes)
    uses_ai = any("langchain" in (n.get("name") or "") for n in nodes)
    author = wf_clean_name((workflow.get("user") or detail.get("user") or {}).get("name"))[:80]
    node_types = list(((detail.get("workflowInfo") or {}).get("nodeTypes") or {}).keys()) or [n.get("name") or "" for n in nodes]
    uses_ai = uses_ai or any("langchain" in t for t in node_types)
    summary, paragraph = wf_sentences("n8n", apps, n8n_trigger_phrase(node_types), uses_ai, author)
    details = "\n".join([paragraph, "", "Platform: n8n"] + ([f"Apps: {', '.join(apps)}"] if apps else []) + [f"Category: {topic}"] + ([f"Author: {author}"] if author else []))
    return {
        "slug": slug,
        "sourceUrl": f"https://n8n.io/workflows/{template_id}-{wf_base(name)}".rstrip("-") + "/",
        "title": name,
        "summary": summary,
        "details": details,
        "kind": "workflow",
        "topic": topic[:60],
        "author": author,
        "installCommand": None,
        "docsUrl": None,
        "stars": int(workflow.get("totalViews") or 0),
    }


def n8n_items(known, cap):
    """Walks the gallery newest first; sends templates the site does not have yet (up to cap) plus a small refresh."""
    fresh, refresh = [], []
    page = 1
    while len(fresh) < cap and page <= MAX_N8N_PAGES:
        try:
            data = wf_request(f"{N8N_PAGE}?page={page}&rows=100&sort=createdAt:desc")
        except Exception as error:
            print(f"n8n page {page} failed: {error}", file=sys.stderr)
            break
        rows = [w for w in data.get("workflows", []) if n8n_is_free(w) and wf_clean_name(w.get("name"))]
        if not data.get("workflows"):
            break
        by_slug = {wf_slug("n8n", w["id"], wf_clean_name(w["name"])): w for w in rows}
        have = known(list(by_slug))
        for slug, workflow in by_slug.items():
            if slug in have:
                if page == 1 and len(refresh) < REFRESH_ITEMS:
                    refresh.append(workflow)
            elif len(fresh) < cap:
                fresh.append(workflow)
        page += 1
        time.sleep(PAUSE)
    items = []
    for workflow in fresh + refresh:
        try:
            item = n8n_item(workflow)
        except Exception as error:
            print(f"n8n template {workflow.get('id')} failed: {error}", file=sys.stderr)
            continue
        if item:
            items.append(item)
    return items


def make_slugs():
    xml = wf_request(MAKE_SITEMAP, as_text=True)
    slugs = re.findall(r"<loc>https://www\.make\.com/templates/(\d+-[a-z0-9-]+)</loc>", xml)
    slugs = [s for s in slugs if not s.endswith("-new-template")]
    return sorted(slugs, key=lambda s: -int(s.split("-", 1)[0]))  # newest ids first


def make_template(slug):
    html = wf_request(f"https://www.make.com/templates/{slug}", as_text=True)
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    blob = "".join(json.loads(f'"{chunk}"') for chunk in chunks)
    start = blob.find('"template":{"slug"')
    if start < 0:
        return None
    template, _ = json.JSONDecoder().raw_decode(blob[start + len('"template":'):])
    return template


def make_items(known, cap):
    try:
        slugs = make_slugs()
    except Exception as error:
        print(f"make sitemap failed: {error}", file=sys.stderr)
        return []
    items = []
    failures = 0
    # Same slug scheme as n8n: make-<id>-<name from the url>.
    candidates = [(s, wf_slug("make", s.split("-", 1)[0], s.split("-", 1)[1] if "-" in s else "")) for s in slugs]
    for start in range(0, len(candidates), 400):
        if len(items) >= cap:
            break
        part = candidates[start:start + 400]
        have = known([site_slug for _, site_slug in part])
        for page_slug, site_slug in part:
            if len(items) >= cap:
                break
            if site_slug in have:
                continue
            try:
                template = make_template(page_slug)
                failures = 0
            except Exception as error:
                failures += 1
                print(f"make template {page_slug} failed: {error}", file=sys.stderr)
                if failures >= 3:  # the site is blocking us (bot protection): stop politely, try again tomorrow
                    print("make: too many failures in a row, stopping for this run", file=sys.stderr)
                    return items
                continue
            time.sleep(3)  # their pages are heavy: go slowly
            name = wf_clean_name((template or {}).get("name"))
            if not template or not name or name.lower() == "new template":
                continue
            apps = []
            for app in template.get("apps") or []:
                shown = wf_pretty_app(app.get("name") or "")
                if shown and shown.lower() not in WF_GENERIC_APPS and shown.lower() != "flow control" and shown not in apps:
                    apps.append(shown)
            cats = [c.get("name") for c in (template.get("categories") or []) if c.get("name") and c["name"].lower() not in WF_SKIP_CATEGORIES]
            topic = (cats[0] if cats else "Automation")[:60]
            summary, paragraph = wf_sentences("Make", apps[:8], "", False, "")
            details = "\n".join([paragraph, "", "Platform: Make"] + ([f"Apps: {', '.join(apps[:10])}"] if apps else []) + [f"Category: {topic}"])
            items.append({
                "slug": site_slug,
                "sourceUrl": f"https://www.make.com/templates/{page_slug}",
                "title": name,
                "summary": summary,
                "details": details,
                "kind": "workflow",
                "topic": topic,
                "author": "",
                "installCommand": None,
                "docsUrl": None,
                "stars": 0,
            })
    return items


def workflow_items(known, cap=None):
    cap = WORKFLOW_CAP if cap is None else cap
    make_cap = cap // MAKE_SHARE
    items = n8n_items(known, cap - make_cap)
    items += make_items(known, make_cap)
    return items


def known_checker(secret):
    """Asks the site which slugs it already has (authenticated). Without a secret (dry run) everything counts as new."""
    def known(slugs):
        if not secret:
            return set()
        try:
            body = json.dumps({"check": slugs}).encode("utf-8")
            result = http_json(f"{SITE}/api/lab/ingest", {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}, body, "POST")
            return set(result.get("known", []))
        except Exception as error:  # an older site without the check: send as new, the site still dedupes by link
            print(f"known-slug check failed: {error}", file=sys.stderr)
            return set()
    return known


def main():
    dry = "--dry-run" in sys.argv
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    only_workflows = "--workflows-only" in sys.argv
    cap = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--workflow-cap=")), None)
    secret = os.environ.get("LAB_INGEST_SECRET", "")
    if not dry and not secret:
        raise SystemExit("LAB_INGEST_SECRET is not set")
    items = [] if only_workflows else github_items() + huggingface_items()
    if "--skip-workflows" not in sys.argv:
        items += workflow_items(known_checker("" if dry else secret), cap)
    print(f"found {len(items)} candidates")
    if dry:
        for item in items[:400]:
            print(f"{item['kind']:10} {item['stars']:>8}  {item['title']}  <{item['sourceUrl']}>")
        for item in [i for i in items if i["kind"] == "workflow"][:3]:
            print(json.dumps(item, indent=2, ensure_ascii=False))
        return
    added = updated = 0
    for start in range(0, len(items), 50):
        body = json.dumps({"items": items[start:start + 50]}).encode("utf-8")
        result = http_json(f"{SITE}/api/lab/ingest", {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}, body, "POST")
        added += int(result.get("added", 0))
        updated += int(result.get("updated", 0))
    print(f"added {added}, updated {updated}")


if __name__ == "__main__":
    main()
