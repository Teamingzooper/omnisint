"""Infer what a person does from the accounts attributed to them.

Which platforms someone is on is itself evidence: eight code-hosting
accounts and a Kaggle profile says something a list of URLs does not. This
module turns the platform mix, the bios and the profile fields into a short
characterisation.

Two rules keep it honest:

* It summarises only the accounts believed to be *one person*. Summarising a
  handle that 92 different people share would produce confident nonsense,
  which is the exact failure this tool exists to prevent. The scope it used
  is always reported alongside the result.
* It is inference from thin, unverified data. Everything here is phrased as
  what the accounts suggest, never as fact.
"""
from __future__ import annotations

import re
from collections import Counter

from .models import Profile

#: Platform name fragment -> interest area. Matched as a substring against a
#: normalised platform name, so "GitHubGist" and "Github" both hit "github".
PLATFORM_TOPICS: dict[str, str] = {}


def _topic(name: str, *fragments: str) -> None:
    for f in fragments:
        PLATFORM_TOPICS[f] = name


_topic("software development",
       "github", "gitlab", "codeberg", "gitea", "bitbucket", "sourceforge",
       "stackoverflow", "npmjs", "npmpackage", "pypi", "rubygems", "packagist",
       "dockerhub", "codepen", "replit", "hackmd", "gitbook", "launchpad",
       "hackerone", "bugcrowd", "gradle", "devto", "lobsters", "hackernews",
       "digitalocean", "easyeda", "hackaday", "codementor", "topcoder")
_topic("competitive programming / CS",
       "leetcode", "codeforces", "codewars", "hackerrank", "hackerearth",
       "codechef", "atcoder", "vjudge", "codecademy", "geeksforgeeks",
       "cssbattle", "monkeytype", "boot.dev", "cyberdefenders", "hackthebox")
_topic("machine learning / data",
       "kaggle", "huggingface", "colab", "wandb")
_topic("gaming",
       "steam", "roblox", "minecraft", "namemc", "osu", "speedrun", "twitch",
       "kick", "apexlegends", "warframemarket", "nexusmods", "itch", "gamefaqs",
       "nintendolife", "kongregate", "battlenet", "planetminecraft", "nitrotype",
       "exophase", "psnprofiles", "starcitizen", "xboxgamertag", "aniworld",
       "myminifactory", "clapper", "opengameart")
_topic("chess", "chess.com", "chesscom", "lichess")
_topic("music",
       "soundcloud", "bandcamp", "mixcloud", "spotify", "lastfm", "statsfm",
       "beatstars", "bandlab", "reverbnation", "musescore", "smule", "audiojungle",
       "discogs", "genius", "setlist", "promodj", "airbit", "destream")
_topic("visual art / photography",
       "500px", "px500", "35photo", "flickr", "unsplash", "vsco", "deviantart",
       "artstation", "dribbble", "behance", "picsart", "pinterest", "giphy",
       "imgur", "cgtrader", "youpic", "viewbug", "pbase", "smugmug", "jalbum",
       "illustrators", "colourlovers", "coroflot", "carbonmade", "crevado",
       "domestika", "creativemarket", "slides", "speakerdeck", "issuu",
       "themeforest", "videohive", "codecanyon", "niftygateway")
_topic("writing / publishing",
       "medium", "substack", "wordpress", "blogger", "hashnode", "hackernoon",
       "note.com", "teletype", "livejournal", "tumblr", "write.as", "paragraph",
       "velog", "listed", "salon24", "proza", "stihi", "author.today", "wattpad",
       "ficwad", "archiveofourown", "virgool", "habr")
_topic("professional / business",
       "linkedin", "calendly", "crunchbase", "angel", "freelancer", "fiverr",
       "kwork", "upwork", "clarity", "topmate", "sessionize", "microsoftlearn",
       "advfn", "etoro", "tradingview", "smart-lab", "tinkoff", "polymarket")
_topic("crypto / web3",
       "opensea", "rarible", "zora", "warpcast", "polymarket", "niftygateway",
       "cropty", "mercadolivre" if False else "opencollective")
_topic("learning / languages",
       "duolingo", "memrise", "scratch", "coursera", "udemy", "jetpunk",
       "archwiki", "wikipedia", "wikidot", "librarything")
_topic("film / TV / anime",
       "letterboxd", "myanimelist", "anilist", "animeplanet", "mydramalist",
       "filmweb", "flipboard", "odysee", "bitchute", "dailymotion", "vimeo",
       "youtube", "aparat", "nyaa")
_topic("books / reading", "goodreads", "bookcrossing", "akniga", "libraryth")
_topic("travel / outdoors",
       "polarsteps", "couchsurfing", "flyertalk", "tripline", "airliners",
       "geocaching", "inaturalist", "openstreetmap", "garden", "windy",
       "sportstracker", "flightradar24", "boosty")
_topic("food / lifestyle", "zomato", "vivino", "untappd", "yelp")
_topic("maker / hardware",
       "instructables", "thingiverse", "printables", "3dtoday", "arduino",
       "pling", "easyeda")
_topic("social / messaging",
       "twitter", "x(twitter)", "instagram", "facebook", "tiktok", "snapchat",
       "threads", "mastodon", "bluesky", "telegram", "discord", "reddit", "vk",
       "ok.ru", "myspace", "clubhouse", "linktree", "carrd", "bio.site",
       "allmylinks", "omglol", "about.me", "gravatar", "keybase", "disqus")
_topic("commerce / selling",
       "ebay", "etsy", "depop", "grailed", "yaga", "osta", "andelemandele",
       "vinted", "gumroad", "buymeacoffee", "patreon", "ko-fi", "donatealerts",
       "donorbox", "liberapay", "fansly", "kickstarter")

#: Platforms almost everyone has; they say nothing about interests.
_GENERIC = {"gravatar", "disqus", "linktree", "carrd", "biosite", "aboutme",
            "allmylinks", "omglol", "pastebin", "protonmail", "wordpress"}

_STOP = set("""
a an and are as at be been but by for from has have how i if in into is it its
me my of on or our so that the their them then there these they this to too
was we were what when where which who will with you your am at do does doing
just get got make made making all can also more most out up over here new now
his her he she him hers via etc com www http https org net
""".split())


def _norm(platform: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", platform.lower())


def topics_for(platform: str) -> str | None:
    flat = _norm(platform)
    if flat in _GENERIC:
        return None
    for fragment, topic in PLATFORM_TOPICS.items():
        if fragment in flat:
            return topic
    return None


def _subject_accounts(profile: Profile):
    """The accounts we are willing to describe as one person, and why."""
    pinned = [a for a in profile.accounts.values() if a.pinned]
    if pinned:
        return pinned, "accounts you confirmed"

    strong = [a for a in profile.accounts.values()
              if a.attribution_level == "same person"]
    if strong:
        return strong, "accounts attributed to your subject"

    primary = next((p["name"] for p in profile.personas if p.get("primary")), None)
    if primary:
        named = [a for a in profile.accounts.values() if a.persona == primary]
        if named:
            return named, f"accounts under the primary identity '{primary}'"

    return [], "none — no account is yet attributed to a single person"


def _bio_terms(accounts, limit: int = 12) -> list[tuple[str, int]]:
    words = Counter()
    for a in accounts:
        for key in ("bio", "headline", "summary", "title", "about"):
            text = str(a.metadata.get(key) or "")
            for word in re.findall(r"[A-Za-z][A-Za-z'&.+-]{2,}", text):
                w = word.lower().strip(".'&+-")
                if len(w) > 2 and w not in _STOP:
                    words[w] += 1
    return words.most_common(limit)


def _years(accounts) -> tuple[str | None, str | None]:
    years = []
    for a in accounts:
        for key, value in a.metadata.items():
            if "creat" not in key and "joined" not in key and "registered" not in key:
                continue
            m = re.search(r"(19[89]\d|20[0-4]\d)", str(value))
            if m:
                years.append(int(m.group(1)))
    if not years:
        return None, None
    return str(min(years)), str(max(years))


def summarise(profile: Profile) -> dict:
    """A short characterisation of the subject, with its own basis attached."""
    accounts, scope = _subject_accounts(profile)

    by_topic: dict[str, list[str]] = {}
    for a in accounts:
        topic = topics_for(a.platform)
        if topic:
            by_topic.setdefault(topic, []).append(a.platform)
    topics = sorted(({"topic": t, "count": len(p), "platforms": sorted(set(p))}
                     for t, p in by_topic.items()),
                    key=lambda x: (-x["count"], x["topic"]))

    def field(*names):
        seen = []
        for a in accounts:
            for n in names:
                v = a.metadata.get(n)
                if v and str(v).strip() and str(v) not in seen:
                    seen.append(str(v).strip())
        return seen[:5]

    first, last = _years(accounts)
    terms = _bio_terms(accounts)

    if not accounts:
        headline = ("No account is yet attributed to a single person, so there "
                    "is nothing to characterise. Confirm accounts with +, or "
                    "add a name or secondary term to anchor the identity.")
    else:
        bits = []
        if topics:
            lead = topics[0]
            bits.append(f"Most active in {lead['topic']} "
                        f"({lead['count']} account{'s' if lead['count'] != 1 else ''}: "
                        f"{', '.join(lead['platforms'][:4])})")
            rest = [f"{t['topic']} ({t['count']})" for t in topics[1:4]]
            if rest:
                bits.append("also " + ", ".join(rest))
        else:
            bits.append(f"{len(accounts)} account(s), none on a platform that "
                        "implies a particular interest")
        if first and last and first != last:
            bits.append(f"accounts created {first}–{last}")
        elif first:
            bits.append(f"earliest account {first}")
        headline = ". ".join(bits) + "."

    return {
        "scope": scope,
        "account_count": len(accounts),
        "headline": headline,
        "topics": topics,
        "bio_terms": [{"term": w, "n": n} for w, n in terms],
        "employers": field("company", "employer", "organization", "clan"),
        "schools": field("school", "university", "education"),
        "roles": field("job_title", "headline", "occupation", "role", "position"),
        "locations": field("location", "city", "country"),
        "websites": field("website", "url", "blog"),
        "active_from": first,
        "active_to": last,
        "caveat": ("Inferred from which platforms these accounts are on and what "
                   "their bios say. It describes the accounts, not the person — "
                   "treat it as a lead."),
    }
