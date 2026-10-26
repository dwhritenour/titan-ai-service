"""
howto_docs.py — app how-to guides for the Titan AI agent (v1.1).

Loads the markdown how-to guides from HOWTO_DOCS_DIR (C:\\titan_ai_howto)
— one guide per app, written by each app's owner via the Claude Exchange
(topic 2026-08-07_titan-ai-howto-docs) — and exposes three NATIVE tools:

    list_howto_guides()        -> every guide: file, app name
    get_howto_guide(app)       -> one guide's full markdown
    search_howto_guides(query) -> ranked matches across all guides

Guides are small markdown files, so the whole corpus loads at startup;
updating one = drop the new .md in the folder + restart the service.
YAML frontmatter (if a file was copied straight from the exchange) is
stripped on load.
"""

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("titan-ai.howto")

HOWTO_TOOL_NAMES = {"list_howto_guides", "get_howto_guide", "search_howto_guides"}


def howto_tools_for_anthropic():
    return [
        {
            "name": "list_howto_guides",
            "description": (
                "List the how-to guides for Titan's internal apps (Transfer "
                "e21 order/status code reference"
                "Dashboard, Hub Transfers/picking, Production Control, SE "
                "Department, SE Inspection, Change Log, Titan AI itself). "
                "Guides cover how to USE the apps, our workflows and "
                "processes, and who owns what."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_howto_guide",
            "description": (
                "Get the full how-to guide for one Titan app. Use for ANY "
                "'how do I…' question about our apps or processes — "
                "releasing work orders, picking, recording deliveries, "
                "inspections, logging changes, exporting data. Matching is "
                "forgiving ('transfer app', 'picking', 'inspection' all "
                "work). Answer from the guide and cite it by name."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "app": {
                        "type": "string",
                        "description": "App/guide to fetch, e.g. 'production control' or 'inspection'",
                    }
                },
                "required": ["app"],
            },
        },
        {
            "name": "search_howto_guides",
            "description": (
                "Keyword-search across ALL app how-to guides. Use when "
                "unsure which app a task lives in ('where do I record a "
                "short pick?', 'who do I tell about a failed inspection?') "
                "or for process/ownership questions."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Search terms"},
                },
                "required": ["query"],
            },
        },
    ]


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_STOPWORDS = {"a", "an", "the", "i", "do", "how", "to", "of", "in", "on",
              "for", "is", "it", "my", "and", "or", "what", "where", "who",
              "can", "you", "we", "me", "get", "with"}


def _terms(query):
    return [t for t in re.split(r"[^a-z0-9]+", (query or "").lower())
            if len(t) > 2 and t not in _STOPWORDS]


class HowtoLibrary:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.guides = {}   # filename -> {"title":..., "text":...}

    def refresh(self):
        self.guides = {}
        if not self.folder.exists():
            log.warning("How-to folder %s not found — howto tools return empty",
                        self.folder)
            return 0
        for md in sorted(self.folder.glob("*.md")):
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
                # strip YAML frontmatter if the file came from the exchange
                text = re.sub(r"\A---\n.*?\n---\n+", "", text, flags=re.DOTALL)
                m = re.match(r"\s*#\s*(.+)", text)
                title = m.group(1).strip() if m else md.stem
                self.guides[md.name] = {"title": title, "text": text}
            except Exception as exc:
                log.error("Failed to load %s: %s", md.name, exc)
        return len(self.guides)

    def list_guides(self):
        return {
            "count": len(self.guides),
            "guides": [{"file": name, "title": g["title"]}
                       for name, g in sorted(self.guides.items())],
        }

    def get_guide(self, app):
        if not self.guides:
            return {"error": "No how-to guides are loaded on the server."}
        want = _norm(app)
        best, best_score = None, 0
        for name, g in self.guides.items():
            for cand in (_norm(name.replace(".md", "")), _norm(g["title"])):
                if not cand:
                    continue
                if want == cand:
                    score = 100
                elif want and (want in cand or cand in want):
                    score = 50 + min(len(want), len(cand))
                else:
                    # token overlap fallback ('transfer app' vs 'transferdashboard')
                    tokens = [t for t in re.split(r"[^a-z0-9]+", (app or "").lower()) if t]
                    score = sum(10 for t in tokens if t in cand)
                if score > best_score:
                    best, best_score = name, score
        if best is None or best_score < 10:
            # Fall back to a content search: "picking" should still find
            # the Hub Transfers guide even though no title contains it.
            fallback = self.search(app)
            results = fallback.get("results") or []
            if results:
                best = results[0]["file"]
            else:
                names = ", ".join(g["title"] for g in self.guides.values())
                return {"error": f"No guide matches '{app}'. Available: {names}"}
        g = self.guides[best]
        return {"file": best, "title": g["title"], "content": g["text"]}

    def search(self, query):
        if not self.guides:
            return {"error": "No how-to guides are loaded on the server."}
        terms = _terms(query)
        if not terms:
            return {"error": "Empty query."}
        hits = []
        for name, g in self.guides.items():
            hay = g["text"].lower()
            score = sum(hay.count(t) for t in terms)
            if score > 0:
                # pull the best-matching section heading for context
                section = ""
                for m in re.finditer(r"^###\s*(.+)$", g["text"], re.MULTILINE):
                    seg = g["text"][m.start():m.start() + 800].lower()
                    if any(t in seg for t in terms):
                        section = m.group(1).strip()
                        break
                hits.append({"file": name, "title": g["title"],
                             "score": score, "best_section": section})
        hits.sort(key=lambda h: -h["score"])
        return {"query": query, "results": hits[:5],
                "tip": "Use get_howto_guide for the full guide."}

    def call(self, name, args):
        args = args or {}
        if name == "list_howto_guides":
            result = self.list_guides()
        elif name == "get_howto_guide":
            result = self.get_guide(args.get("app", ""))
        elif name == "search_howto_guides":
            result = self.search(args.get("query", ""))
        else:
            result = {"error": f"Unknown howto tool '{name}'"}
        return json.dumps(result)


_library = None


def get_library(folder):
    global _library
    if _library is None:
        _library = HowtoLibrary(folder)
    return _library
