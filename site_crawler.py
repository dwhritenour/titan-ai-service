"""
site_crawler.py — titanfci.com knowledge source for Titan AI (v1.3).

Crawls the company website into a local text index and exposes three
NATIVE tools:

    search_website(query)   -> ranked page matches (public + secure)
    get_webpage(page)       -> one page's full extracted text
    (the CAD model index and site-PDF index appear as synthetic pages,
     searchable like any other)

Scope:
- PUBLIC side: same-domain HTML pages, walked from WEBSITE_URL.
- SECURE side (optional): if WEBSITE_USERNAME/PASSWORD are set, the
  crawler logs in via the site's login form and walks the pages under
  WEBSITE_SECURE_START_URLS (consignment sites, solid-model listings).
  Plain inventory pages are e21 data — Nexus answers those fresher, so
  keep inventory URLs OUT of the secure start list.
- Solid models: any link that looks like a CAD file (.step/.stp/.igs/
  .iges/.x_t/.sldprt, or a download link labelled 'model'/'CAD') is
  collected into a synthetic "CAD Model Index" page with SKU-ish
  context, so "is there a solid model for the YS61?" is answerable
  with a direct link.
- Site PDFs (IOMs etc.) are not downloaded in v1, but their links are
  collected into a synthetic "Site Document Index" page.

Freshness: the cache (website_cache.json) refreshes in a background
thread at service start when older than WEBSITE_REFRESH_DAYS. Questions
keep answering from the existing cache while a crawl runs.
"""

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urldefrag, urlparse

log = logging.getLogger("titan-ai.website")

WEBSITE_TOOL_NAMES = {"search_website", "get_webpage"}

CAD_EXTS = (".step", ".stp", ".igs", ".iges", ".x_t", ".x_b", ".sldprt", ".sat")
SKIP_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".css", ".js",
             ".woff", ".woff2", ".ttf", ".mp4", ".webp", ".zip", ".exe")

# URL substrings never worth crawling: the WordPress admin dashboard
# (a logged-in crawler otherwise wanders every plugin settings page),
# the logout link (a GET on it kills the secure session mid-crawl),
# WP internals, and auth/utility pages that only add noise. Substring
# match, case-insensitive. Secure START urls bypass this list, so
# nothing here can block a deliberately configured start page.
SKIP_URL_PARTS = ("/wp-admin", "/wp-login", "/wp-json", "/xmlrpc.php",
                  "action=logout", "wp-login.php?action",
                  "/log-in", "/login/register", "/login/password-reset",
                  "/search/")

_STOPWORDS = {"a", "an", "the", "i", "do", "how", "to", "of", "in", "on",
              "for", "is", "it", "my", "and", "or", "what", "where", "who",
              "can", "you", "we", "me", "get", "with", "our", "your"}


def website_tools_for_anthropic():
    return [
        {
            "name": "search_website",
            "description": (
                "Search the indexed content of Titan's website "
                "(www.titanfci.com) — public product pages, resources, "
                "news, AND the secure dealer side: consignment-site "
                "inventory pages, the CAD/solid-model index, and the site "
                "document (IOM/PDF) index. Use for questions about the "
                "website, consignment stock, whether a solid model exists "
                "for a SKU, or anything not found in Nexus/literature. "
                "Cite answers with the page URL."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        {
            "name": "get_webpage",
            "description": (
                "Get the full extracted text of one indexed page of "
                "titanfci.com (by URL or title from search_website). "
                "Special pages: 'CAD Model Index' (every solid-model "
                "download link found, with context) and 'Site Document "
                "Index' (every PDF/IOM link found)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"page": {"type": "string",
                                        "description": "URL or title"}},
                "required": ["page"],
            },
        },
    ]


def _clean_text(html):
    """HTML -> readable text (BeautifulSoup, lazily imported)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
    return title, text, soup


class WebsiteLibrary:
    def __init__(self, base_url, cache_path, max_pages=300, refresh_days=7,
                 login_url=None, username=None, password=None,
                 secure_start_urls=None, delay=0.4):
        self.base_url = base_url.rstrip("/")
        self.domain = urlparse(self.base_url).netloc
        self.cache_path = Path(cache_path)
        self.max_pages = max_pages
        self.refresh_days = refresh_days
        self.login_url = login_url
        self.username = username
        self.password = password
        self.secure_start_urls = [u.strip() for u in (secure_start_urls or [])
                                  if u.strip()]
        self.delay = delay
        self.pages = {}        # url -> {"title","text","secure","fetched_at"}
        self._crawling = False

    # ── cache ────────────────────────────────────────────────────────

    def load_cache(self):
        if self.cache_path.exists():
            try:
                self.pages = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except Exception:
                self.pages = {}
        return len(self.pages)

    def _save_cache(self):
        try:
            self.cache_path.write_text(json.dumps(self.pages), encoding="utf-8")
        except Exception as exc:
            log.warning("Could not save website cache: %s", exc)

    def is_stale(self):
        # A near-empty index is a failed/blocked crawl, however fresh
        # its timestamps look — always retry those.
        if len(self.pages) < 5:
            return True
        newest = max((p.get("fetched_at", "") for p in self.pages.values()),
                     default="")
        try:
            age = datetime.now() - datetime.fromisoformat(newest)
            return age > timedelta(days=self.refresh_days)
        except Exception:
            return True

    def refresh_in_background(self):
        """Start a crawl in a daemon thread if stale and not running."""
        if self._crawling or not self.is_stale():
            return False
        t = threading.Thread(target=self._crawl_safe, daemon=True,
                             name="website-crawl")
        t.start()
        return True

    def _crawl_safe(self):
        self._crawling = True
        try:
            self.crawl()
        except Exception:
            log.exception("Website crawl failed — serving old cache")
        finally:
            self._crawling = False

    # ── crawling ─────────────────────────────────────────────────────

    def _session(self):
        import requests
        s = requests.Session()
        s.headers["User-Agent"] = ("TitanAI-internal-crawler/1.0 "
                                   "(titan-ai-service; contact Dave)")
        return s

    # Names WordPress and common login plugins use for the username box.
    _USER_FIELD_HINTS = ("log", "user_login", "username", "user", "email",
                         "user_email", "login")

    def _parse_login_form(self, html, page_url):
        """Find the form that actually contains a password input (pages
        often carry other forms first — search bars, newsletter signups).
        Returns (action, data, user_field, pass_field) or None."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for form in soup.find_all("form"):
            pass_field = None
            user_field = None
            user_candidates = []
            data = {}
            for inp in form.find_all("input"):
                name = inp.get("name")
                if not name:
                    continue
                itype = (inp.get("type") or "text").lower()
                if itype == "password" and pass_field is None:
                    pass_field = name
                elif itype in ("text", "email"):
                    user_candidates.append(name)
                elif itype == "hidden":
                    data[name] = inp.get("value", "")
            if not pass_field:
                continue                      # search form, etc. — skip
            # Prefer a username-looking name; else first text/email input.
            for cand in user_candidates:
                if cand.lower() in self._USER_FIELD_HINTS:
                    user_field = cand
                    break
            if user_field is None and user_candidates:
                user_field = user_candidates[0]
            if user_field is None:
                continue
            action = urljoin(page_url, form.get("action") or page_url)
            return action, data, user_field, pass_field
        return None

    def _login(self, session):
        """Form login: GET the login page, find the form WITH a password
        field (never the site search bar), carry over hidden fields
        (CSRF etc.), post credentials. Falls back to the standard
        WordPress wp-login.php endpoint if the page's login form is
        rendered by JavaScript and invisible in the raw HTML."""
        r = session.get(self.login_url, timeout=30)
        found = self._parse_login_form(r.text, r.url)

        if found is None:
            # WordPress fallback: the core login endpoint accepts a
            # plain POST regardless of how the themed login page looks.
            parsed = urlparse(r.url)
            wp_login = f"{parsed.scheme}://{parsed.netloc}/wp-login.php"
            log.info("No password form in HTML at %s — trying WordPress "
                     "fallback %s", self.login_url, wp_login)
            r2 = session.get(wp_login, timeout=30)
            if r2.status_code == 200:
                found = self._parse_login_form(r2.text, r2.url)
            if found is None:
                raise RuntimeError(
                    "Could not find a login form with a password field at "
                    f"{self.login_url} (or {wp_login}). If the login form "
                    "is JavaScript-rendered, set WEBSITE_LOGIN_URL to the "
                    "site's plain login endpoint.")

        action, data, user_field, pass_field = found
        data[user_field] = self.username
        data[pass_field] = self.password
        data.setdefault("rememberme", "forever")   # harmless if unused
        r = session.post(action, data=data, timeout=30)
        r.raise_for_status()
        # Sanity check: if the response still shows a password box, the
        # credentials were probably rejected.
        if self._parse_login_form(r.text, r.url) is not None:
            log.warning("Login POST to %s returned a page that still has "
                        "a login form — credentials may be wrong; "
                        "continuing anyway", action)
        else:
            log.info("Secure login OK via %s (fields %s/%s)",
                     action, user_field, pass_field)
        return session

    def _sitemap_urls(self, session, root):
        """Fetch sitemap(_index).xml and return the page URLs it lists.
        Handles one level of sitemap-index nesting (WordPress style)."""
        found = []
        for name in ("sitemap_index.xml", "sitemap.xml"):
            try:
                r = session.get(f"{root}/{name}", timeout=30)
                if r.status_code != 200 or "<loc>" not in r.text:
                    continue
                locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
                for loc in locs:
                    if loc.lower().endswith(".xml"):      # nested sitemap
                        try:
                            r2 = session.get(loc, timeout=30)
                            found += re.findall(
                                r"<loc>\s*([^<\s]+)\s*</loc>", r2.text)
                        except Exception:
                            pass
                    else:
                        found.append(loc)
                if found:
                    log.info("Sitemap at %s/%s listed %s URLs",
                             root, name, len(found))
                    break
            except Exception as exc:
                log.warning("Sitemap fetch %s failed: %s", name, exc)
        return found

    def crawl(self):
        started = time.monotonic()
        session = self._session()
        new_pages = {}
        cad_links = []     # (link_url, context)
        pdf_links = []

        # Resolve redirects on the base URL and adopt the FINAL domain —
        # www.titanfci.com actually redirects to titanfci.co, and a
        # strict single-domain filter would otherwise reject every link.
        root = self.base_url
        domains = {self.domain, self.domain.replace("www.", "")}
        try:
            r0 = session.get(self.base_url, timeout=30, allow_redirects=True)
            final = urlparse(r0.url)
            root = f"{final.scheme}://{final.netloc}"
            domains |= {final.netloc, final.netloc.replace("www.", ""),
                        "www." + final.netloc.replace("www.", "")}
            log.info("Website root resolved: %s -> %s (domains: %s)",
                     self.base_url, root, sorted(domains))
        except Exception as exc:
            log.warning("Base URL resolve failed (%s) — using %s as-is",
                        exc, self.base_url)

        def eligible(url):
            p = urlparse(url)
            low = url.lower()
            return (p.netloc in domains
                    and not any(part in low for part in SKIP_URL_PARTS)
                    and not low.endswith(SKIP_EXTS)
                    and not low.endswith(".pdf")
                    and not low.endswith(CAD_EXTS))

        def is_denied(page):
            """True if a cached page is really the members-only 'Oops'
            stub (or similar login wall), not real content. The secure
            walk re-crawls these — a public crawl caches them for every
            dealer-side URL in the sitemap, and skipping them left the
            CAD/inventory pages permanently stubbed (v1.3 bug #2)."""
            text = page.get("text", "")
            title = (page.get("title") or "").lower()
            return ("members-only zone" in text
                    or title.strip() == "oops"
                    or (len(text) < 2500
                        and ("login now" in text.lower()
                             or "log in below" in text.lower())))

        def walk(start_urls, secure, budget=None):
            # Per-walk page budget. The public and secure walks each get
            # their own allowance; a shared cap let a 300-page public
            # crawl starve the secure walk to zero (v1.3 bug — login
            # succeeded, then the loop exited before fetching anything,
            # which is also why the CAD index came back empty).
            budget = self.max_pages if budget is None else budget
            added = 0
            queue = list(start_urls)
            seen = set(queue)
            while queue and added < budget:
                url = queue.pop(0)
                # Secure pages are few and have hung before (slow-drip
                # responses defeat the 30s read timeout) — pre-log each
                # one so a hang identifies its URL. Public side just
                # logs progress.
                if secure:
                    log.info("secure fetch: %s", url)
                elif added and added % 25 == 0 and url not in new_pages:
                    log.info("public walk: %s pages so far, %s queued",
                             added, len(queue))
                try:
                    r = session.get(url, timeout=30)
                    if r.status_code != 200 or "text/html" not in \
                            r.headers.get("Content-Type", ""):
                        continue
                    title, text, soup = _clean_text(r.text)
                    if len(text) > 100:
                        if url not in new_pages:
                            added += 1
                        new_pages[url] = {
                            "title": title or url,
                            "text": text[:40000],
                            "secure": secure,
                            "fetched_at": datetime.now().isoformat(),
                        }
                    # Is this page CAD-flavored? WordPress Download
                    # Manager serves files through ?wpdmdl=NNN links with
                    # no file extension, so on model pages we classify
                    # wpdmdl links as CAD downloads; elsewhere they're
                    # documents (spec sheets/IOMs) for the doc index.
                    page_is_cad = ("3dmodel" in url.lower()
                                   or "cad" in (title or "").lower()
                                   or "3d " in (title or "").lower())
                    for a in soup.find_all("a", href=True):
                        link, _ = urldefrag(urljoin(url, a["href"]))
                        low = link.lower()
                        atext = (a.get_text(" ", strip=True) or "")
                        context = " ".join(
                            (atext, title or url)).strip()[:200]
                        if low.endswith(CAD_EXTS) or (
                                "wpdmdl=" in low and page_is_cad) or (
                                "model" in atext.lower()
                                and ("download" in low or low.endswith(".zip"))):
                            cad_links.append((link, context, secure))
                        elif low.endswith(".pdf") or "wpdmdl=" in low:
                            pdf_links.append((link, context, secure))
                        elif (eligible(link) and link not in seen
                                and not (secure and link in new_pages
                                         and not is_denied(new_pages[link]))):
                            # The secure walk skips pages the public walk
                            # already read FOR REAL (re-crawling them
                            # overwrote secure:False flags and burned
                            # budget) — but it DOES re-crawl 'Oops'
                            # login-wall stubs, which is where the CAD
                            # series and dealer inventory pages live.
                            seen.add(link)
                            queue.append(link)
                    time.sleep(self.delay)
                except Exception as exc:
                    log.warning("Crawl skip %s: %s", url, exc)
            return added

        # public side — sitemap-first (WordPress publishes one); fall
        # back to link-walking from the resolved root if none exists.
        sitemap_pages = [u for u in self._sitemap_urls(session, root)
                         if eligible(u)]
        if sitemap_pages:
            walk(sitemap_pages[: self.max_pages], secure=False)
        else:
            walk([root], secure=False)
        public_count = len(new_pages)

        # secure side
        if self.username and self.password and self.login_url:
            try:
                self._login(session)
                if not self.secure_start_urls:
                    log.warning("Secure login OK but WEBSITE_SECURE_START_URLS "
                                "is empty — no secure pages to crawl")
                n_secure = walk(self.secure_start_urls or [], secure=True)
                log.info("Secure walk: %s pages from %s start URL(s)",
                         n_secure, len(self.secure_start_urls))
            except Exception:
                log.exception("Secure-side crawl failed — public side kept")

        # synthetic index pages
        if cad_links:
            lines = [f"- {ctx} — {url}" + ("  [secure]" if sec else "")
                     for url, ctx, sec in sorted(set(cad_links))]
            new_pages["titan-ai://cad-model-index"] = {
                "title": "CAD Model Index",
                "text": "Solid model / CAD downloads found on titanfci.com:\n"
                        + "\n".join(lines),
                "secure": True,
                "fetched_at": datetime.now().isoformat(),
            }
        if pdf_links:
            lines = [f"- {ctx} — {url}" + ("  [secure]" if sec else "")
                     for url, ctx, sec in sorted(set(pdf_links))]
            new_pages["titan-ai://site-document-index"] = {
                "title": "Site Document Index",
                "text": "PDF documents (IOMs, flyers, etc.) found on "
                        "titanfci.com:\n" + "\n".join(lines),
                "secure": False,
                "fetched_at": datetime.now().isoformat(),
            }

        if new_pages:
            self.pages = new_pages
            self._save_cache()
        log.info("Website crawl done: %s pages (%s public), %s CAD links, "
                 "%s PDFs, %.0fs",
                 len(new_pages), public_count, len(set(cad_links)),
                 len(set(pdf_links)), time.monotonic() - started)
        return len(new_pages)

    # ── tools ────────────────────────────────────────────────────────

    def search(self, query):
        if not self.pages:
            return {"error": "The website index is empty (crawl may still "
                             "be running, or the site is unreachable)."}
        terms = [t for t in re.split(r"[^a-z0-9]+", (query or "").lower())
                 if len(t) > 2 and t not in _STOPWORDS]
        if not terms:
            return {"error": "Empty query."}
        hits = []
        for url, p in self.pages.items():
            hay = (p["title"] + "\n" + p["text"]).lower()
            score = sum(hay.count(t) for t in terms)
            if score > 0:
                hits.append({"url": url, "title": p["title"],
                             "secure": p["secure"], "score": score,
                             "preview": p["text"][:400]})
        hits.sort(key=lambda h: -h["score"])
        return {"query": query, "results": hits[:6],
                "tip": "Use get_webpage(url) for the full page."}

    def get_page(self, page):
        if not self.pages:
            return {"error": "The website index is empty."}
        want = (page or "").strip().lower()
        for url, p in self.pages.items():
            if want in (url.lower(), p["title"].lower()):
                return {"url": url, "title": p["title"],
                        "secure": p["secure"], "content": p["text"]}
        # forgiving match
        for url, p in self.pages.items():
            if want and (want in url.lower() or want in p["title"].lower()):
                return {"url": url, "title": p["title"],
                        "secure": p["secure"], "content": p["text"]}
        result = self.search(page)
        if result.get("results"):
            best = result["results"][0]
            p = self.pages[best["url"]]
            return {"url": best["url"], "title": p["title"],
                    "secure": p["secure"], "content": p["text"]}
        return {"error": f"No indexed page matches '{page}'."}

    def call(self, name, args):
        args = args or {}
        if name == "search_website":
            result = self.search(args.get("query", ""))
        elif name == "get_webpage":
            result = self.get_page(args.get("page", ""))
        else:
            result = {"error": f"Unknown website tool '{name}'"}
        return json.dumps(result)


_library = None


def get_library(config):
    global _library
    if _library is None:
        _library = WebsiteLibrary(
            base_url=config.WEBSITE_URL,
            cache_path=config.WEBSITE_CACHE_PATH,
            max_pages=config.WEBSITE_MAX_PAGES,
            refresh_days=config.WEBSITE_REFRESH_DAYS,
            login_url=config.WEBSITE_LOGIN_URL or None,
            username=config.WEBSITE_USERNAME or None,
            password=config.WEBSITE_PASSWORD or None,
            secure_start_urls=(config.WEBSITE_SECURE_START_URLS or "").split(","),
        )
        _library.load_cache()
    return _library


if __name__ == "__main__":
    # Standalone test:  venv\Scripts\python site_crawler.py
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import config as _cfg
    lib = get_library(_cfg)
    print(f"Cached pages: {len(lib.pages)} (stale: {lib.is_stale()})")
    print("Crawling now (foreground)…")
    n = lib.crawl()
    print(f"Crawled {n} pages.")
    for url, p in list(lib.pages.items())[:10]:
        print(" -", p["title"], "|", url, "| secure:", p["secure"])