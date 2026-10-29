import json, math, os, sys, urllib.parse, urllib.request
from datetime import datetime, timezone

def get(url):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "super-partner-step"}
    if "api.github.com" in url and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15) as r:
            return json.load(r)
    except Exception as e:
        return {"error": str(e)[:120]}

query, language = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""
count = int(sys.argv[3]) if len(sys.argv) > 3 else 5
q = f"{query} fork:false archived:false" + (f" language:{language}" if language else "")
found = get("https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": q, "sort": "stars", "per_page": count}))
if "items" not in found:
    sys.exit(f"search failed: {found.get('error') or found.get('message')}")
now, ranked = datetime.now(timezone.utc), []
for repo in found["items"]:
    name = repo["full_name"]
    days = (now - datetime.fromisoformat(repo["pushed_at"].replace("Z", "+00:00"))).days
    upkeep = 30 if days <= 90 else 20 if days <= 365 else 10 if days <= 730 else 0
    community = min(25, round(5 * math.log10(repo["stargazers_count"] + 1)))
    top = get(f"https://api.github.com/repos/{name}/contents/")
    names = {item["name"].lower() for item in top} if isinstance(top, list) else set()
    tests = 10 if names & {"test", "tests", "spec", "__tests__", "testing"} else 0
    ci = 10 if names & {".github", ".circleci", ".gitlab-ci.yml", ".travis.yml"} else 0
    docs = 5 if any(n.startswith("readme") for n in names) else 0
    card = get(f"https://api.securityscorecards.dev/projects/github.com/{name}")
    security = round(card["score"] * 2) if isinstance(card.get("score"), (int, float)) else 10
    ranked.append({"repo": name, "score": upkeep + community + tests + ci + docs + security,
                   "stars": repo["stargazers_count"], "pushed_days_ago": days,
                   "license": (repo.get("license") or {}).get("spdx_id") or "NONE",
                   "tests": bool(tests), "ci": bool(ci), "scorecard": card.get("score"),
                   "branch": repo["default_branch"], "about": (repo.get("description") or "")[:120]})
for row in sorted(ranked, key=lambda row: -row["score"]):
    print(json.dumps(row, ensure_ascii=False))
