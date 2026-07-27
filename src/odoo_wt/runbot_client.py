import urllib.request
import re
import json
from typing import Optional, Tuple
from .app_config import debug_log

def find_runbot_batch_url(branch_name: str) -> Optional[Tuple[str, str]]:
    """
    Queries Runbot search for the given branch and returns a tuple (batch_url, timestamp_str)
    of the most recent batch, or None.
    """
    if not branch_name:
        return None
        
    search_url = f"https://runbot.odoo.com/runbot?search={branch_name}"
    debug_log(f"Searching Runbot search index for branch: '{branch_name}' (URL: {search_url})")
    req = urllib.request.Request(
        search_url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
        debug_log(f"Downloaded search index page successfully. Length: {len(html)} characters")
        
        # Odoo Runbot links batches inside href="/runbot/batch/<id>" with title="YYYY-MM-DD HH:MM:SS"
        match = re.search(r'href="/runbot/batch/(\d+)" title="([^"]+)"', html)
        if match:
            batch_id = match.group(1)
            timestamp_str = match.group(2)
            debug_log(f"Matched batch on index! ID: {batch_id}, Timestamp: {timestamp_str}")
            return f"https://runbot.odoo.com/runbot/batch/{batch_id}", timestamp_str
            
        # Fallback to match just batch ID if title is not present
        match_id = re.search(r'href="/runbot/batch/(\d+)"', html)
        if match_id:
            batch_id = match_id.group(1)
            debug_log(f"Matched batch on index! ID: {batch_id} (fallback no timestamp)")
            return f"https://runbot.odoo.com/runbot/batch/{batch_id}", ""
        debug_log("No matching batch found on index page.")
    except Exception as e:
        debug_log(f"Exception during Runbot search index fetch: {e}")
    return None

def check_batch_details(batch_url: str) -> Tuple[int, int, int, int]:
    """
    Queries the Runbot batch page and returns a tuple of build counts:
    (success_count, failed_count, warning_count, running_count)
    """
    req = urllib.request.Request(
        batch_url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
        
        slot_badges = re.findall(r'<div[^>]*class="[^"]*slot_button_group[^"]*"[^>]*>\s*<(?:span|a)[^>]*class="btn btn-(success|danger|warning|default|info) disabled"', html)
        success = slot_badges.count("success")
        failed = slot_badges.count("danger")
        warning = slot_badges.count("warning")
        running = html.count("fa-spinner") + html.count("fa-circle-o-notch") + slot_badges.count("info")
        
        return success, failed, warning, running
    except Exception:
        return 0, 0, 0, 0

def query_branch_status(branch_name: str) -> Optional[Tuple[str, str, int, int, int, int, Optional[str], Optional[str]]]:
    """
    Queries Runbot search and parses status counts + PR links in a SINGLE request.
    Returns: (batch_url, timestamp, success, failed, warning, running, odoo_pr_url, enterprise_pr_url)
    """
    if not branch_name:
        return None
        
    if branch_name.isdigit() and len(branch_name) >= 6:
        # Symmetrically support raw batch ID queries, bypassing the search index entirely
        batch_id = branch_name
        batch_url = f"https://runbot.odoo.com/runbot/batch/{batch_id}"
        ts_str = "Recent"
        odoo_pr = None
        enterprise_pr = None
        upgrade_pr = None
        
        try:
            debug_log(f"Direct raw Batch ID detected! Downloading detailed batch page content from: {batch_url}")
            req_batch = urllib.request.Request(
                batch_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req_batch, timeout=5) as response:
                batch_html = response.read().decode('utf-8')
            debug_log(f"Successfully downloaded detailed batch page directly. Length: {len(batch_html)} characters")
        except Exception as e:
            debug_log(f"Direct batch page download failed: {e}")
            return None
            
        slot_badges = re.findall(r'<div[^>]*class="[^"]*slot_button_group[^"]*"[^>]*>\s*<(?:span|a)[^>]*class="btn btn-(success|danger|warning|default|info) disabled"', batch_html)
        success = slot_badges.count("success")
        failed = slot_badges.count("danger")
        warning = slot_badges.count("warning")
        running = batch_html.count("fa-spinner") + batch_html.count("fa-circle-o-notch") + slot_badges.count("info")
        debug_log(f"Direct Batch parsed -> success: {success}, failed: {failed}, warning: {warning}, running: {running}")
        
        return batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr

    search_url = f"https://runbot.odoo.com/runbot?search={branch_name}"
    debug_log(f"Querying Runbot search index for branch: '{branch_name}' (URL: {search_url})")
    req = urllib.request.Request(
        search_url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
        debug_log(f"Downloaded search index page successfully. Length: {len(html)} characters")
            
        # Parse Batch ID and Timestamp
        match = re.search(r'href="/runbot/batch/(\d+)" title="([^"]+)"', html)
        if match:
            batch_id = match.group(1)
            ts_str = match.group(2)
            batch_url = f"https://runbot.odoo.com/runbot/batch/{batch_id}"
            debug_log(f"Matched batch on index! ID: {batch_id}, URL: {batch_url}")
            
            # Symmetrically search backward to capture the entire bundle_row including its column 1 GitHub dropdown links!
            tile_start = html.find(f'href="/runbot/batch/{batch_id}"')
            if tile_start != -1:
                row_start = html.rfind('<div class="row bundle_row">', 0, tile_start)
                block = html[row_start:tile_start+4000] if row_start != -1 else html[tile_start:tile_start+4000]
            else:
                block = html
            
            # Symmetrically fetch the actual batch detailed page to parse the complete build statuses (including minor/hidden failures and warnings!)
            try:
                debug_log(f"Downloading detailed batch page content from: {batch_url}")
                req_batch = urllib.request.Request(
                    batch_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                )
                with urllib.request.urlopen(req_batch, timeout=5) as response:
                    batch_html = response.read().decode('utf-8')
                debug_log(f"Successfully downloaded detailed batch page. Length: {len(batch_html)} characters")
            except Exception as e:
                debug_log(f"Failed to download detailed batch page ({e}), falling back to dashboard block.")
                batch_html = block # Fallback to block if batch page fails
            
            slot_badges = re.findall(r'<div[^>]*class="[^"]*slot_button_group[^"]*"[^>]*>\s*<(?:span|a)[^>]*class="btn btn-(success|danger|warning|default|info) disabled"', batch_html)
            success = slot_badges.count("success")
            failed = slot_badges.count("danger")
            warning = slot_badges.count("warning")
            running = batch_html.count("fa-spinner") + batch_html.count("fa-circle-o-notch") + slot_badges.count("info")
            debug_log(f"Parsed build counts -> success: {success}, failed: {failed}, warning: {warning}, running: {running}")
            
            # If the batch exists but has no completed or spinning builds yet, it is preparing/pending
            if success == 0 and failed == 0 and warning == 0 and running == 0:
                running = 1
            
            # Parse linked Pull Requests from the matched block/tile only
            odoo_pr = None
            enterprise_pr = None
            upgrade_pr = None
            pr_links = re.findall(r'href="(https://github.com/odoo(?:-dev)?/([^/]+)/pull/\d+)"', block)
            for url, repo in pr_links:
                if repo == "odoo" and not odoo_pr:
                    odoo_pr = url
                elif repo == "enterprise" and not enterprise_pr:
                    enterprise_pr = url
                elif repo == "upgrade" and not upgrade_pr:
                    upgrade_pr = url
            debug_log(f"Extracted PR links -> Odoo: {odoo_pr}, Enterprise: {enterprise_pr}, Upgrade: {upgrade_pr}")
            
            return batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr
            
        # Fallback if title is not present
        match_id = re.search(r'href="/runbot/batch/(\d+)"', html)
        if match_id:
            batch_id = match_id.group(1)
            batch_url = f"https://runbot.odoo.com/runbot/batch/{batch_id}"
            debug_log(f"Matched batch on index (fallback no title)! ID: {batch_id}, URL: {batch_url}")
            
            # Symmetrically search backward to capture the entire bundle_row including its column 1 GitHub dropdown links!
            tile_start = html.find(f'href="/runbot/batch/{batch_id}"')
            if tile_start != -1:
                row_start = html.rfind('<div class="row bundle_row">', 0, tile_start)
                block = html[row_start:tile_start+4000] if row_start != -1 else html[tile_start:tile_start+4000]
            else:
                block = html
            
            # Symmetrically fetch the actual batch detailed page to parse the complete build statuses (including minor/hidden failures and warnings!)
            try:
                debug_log(f"Downloading detailed batch page content from: {batch_url} (fallback)")
                req_batch = urllib.request.Request(
                    batch_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                )
                with urllib.request.urlopen(req_batch, timeout=5) as response:
                    batch_html = response.read().decode('utf-8')
                debug_log(f"Successfully downloaded detailed batch page (fallback). Length: {len(batch_html)} characters")
            except Exception as e:
                debug_log(f"Failed to download detailed batch page ({e}), falling back to dashboard block.")
                batch_html = block # Fallback to block if batch page fails
            
            slot_badges = re.findall(r'<div[^>]*class="[^"]*slot_button_group[^"]*"[^>]*>\s*<(?:span|a)[^>]*class="btn btn-(success|danger|warning|default|info) disabled"', batch_html)
            success = slot_badges.count("success")
            failed = slot_badges.count("danger")
            warning = slot_badges.count("warning")
            running = batch_html.count("fa-spinner") + batch_html.count("fa-circle-o-notch") + slot_badges.count("info")
            debug_log(f"Parsed build counts (fallback) -> success: {success}, failed: {failed}, warning: {warning}, running: {running}")
            
            # If the batch exists but has no completed or spinning builds yet, it is preparing/pending
            if success == 0 and failed == 0 and warning == 0 and running == 0:
                running = 1
            
            # Parse linked Pull Requests from the matched block/tile only
            odoo_pr = None
            enterprise_pr = None
            upgrade_pr = None
            pr_links = re.findall(r'href="(https://github.com/odoo(?:-dev)?/([^/]+)/pull/\d+)"', block)
            for url, repo in pr_links:
                if repo == "odoo" and not odoo_pr:
                    odoo_pr = url
                elif repo == "enterprise" and not enterprise_pr:
                    enterprise_pr = url
                elif repo == "upgrade" and not upgrade_pr:
                    upgrade_pr = url
            debug_log(f"Extracted PR links (fallback) -> Odoo: {odoo_pr}, Enterprise: {enterprise_pr}, Upgrade: {upgrade_pr}")
            
            return batch_url, "", success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr
    except Exception:
        pass
    return None

_gh_auth_status = None

def is_gh_authenticated() -> bool:
    global _gh_auth_status
    if _gh_auth_status is not None:
        return _gh_auth_status
        
    import shutil
    if not shutil.which("gh"):
        _gh_auth_status = False
        return False
        
    import subprocess
    try:
        subprocess.run(["gh", "auth", "status"], capture_output=True, check=True, timeout=15)
        _gh_auth_status = True
        return True
    except Exception:
        _gh_auth_status = False
        return False

def fetch_repo_comments(repo_name: str, pr_number: str) -> list:
    """
    Fetches latest review comments and issue comments for a PR using high-speed GraphQL.
    """
    import subprocess
    import json
    
    comments = []
    cmd = ["gh", "pr", "view", pr_number, "-R", repo_name, "--json", "comments,reviews"]
    debug_log(f"Fetching GitHub PR comments for repo '{repo_name}' PR #{pr_number} using 'gh pr view'...")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
        if res.stdout.strip():
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                # 1. Parse global comments
                raw_comments = data.get("comments", [])
                if isinstance(raw_comments, list):
                    for item in raw_comments:
                        if isinstance(item, dict):
                            author_obj = item.get("author")
                            if author_obj and isinstance(author_obj, dict):
                                login = author_obj.get("login")
                                if login:
                                    body_text = item.get("body", "")
                                    if body_text.strip():
                                        comments.append({
                                            "user": login,
                                            "created_at": item.get("createdAt", ""),
                                            "html_url": item.get("url", ""),
                                            "body": body_text,
                                            "is_ent": "enterprise" in repo_name,
                                            "is_upg": "upgrade" in repo_name
                                        })
                # 2. Parse reviews
                raw_reviews = data.get("reviews", [])
                if isinstance(raw_reviews, list):
                    for item in raw_reviews:
                        if isinstance(item, dict):
                            author_obj = item.get("author")
                            if author_obj and isinstance(author_obj, dict):
                                login = author_obj.get("login")
                                if login:
                                    body_text = item.get("body", "")
                                    if body_text.strip():
                                        comments.append({
                                            "user": login,
                                            "created_at": item.get("submittedAt", ""),
                                            "html_url": f"https://github.com/{repo_name}/pull/{pr_number}",
                                            "body": body_text,
                                            "is_ent": "enterprise" in repo_name,
                                            "is_upg": "upgrade" in repo_name
                                        })
        debug_log(f"Fetched and parsed {len(comments)} global/review comments via 'gh pr view'.")
    except Exception as e:
        debug_log(f"Exception during 'gh pr view' comments fetch: {e}")
        pass

    # 3. Fetch inline review comments using standard GitHub pulls/comments API
    try:
        cmd_inline = ["gh", "api", f"repos/{repo_name}/pulls/{pr_number}/comments"]
        debug_log(f"Fetching inline files-changed review comments via standard: 'gh api repos/{repo_name}/pulls/{pr_number}/comments'")
        res_inline = subprocess.run(cmd_inline, capture_output=True, text=True, check=True, timeout=15)
        if res_inline.stdout.strip():
            raw_inline = json.loads(res_inline.stdout)
            if isinstance(raw_inline, list):
                for item in raw_inline:
                    if isinstance(item, dict):
                        user_obj = item.get("user")
                        if user_obj and isinstance(user_obj, dict):
                            login = user_obj.get("login")
                            if login:
                                body_text = item.get("body", "")
                                if body_text.strip():
                                    comments.append({
                                        "user": login,
                                        "created_at": item.get("created_at", ""),
                                        "html_url": item.get("html_url", ""),
                                        "body": body_text,
                                        "is_ent": "enterprise" in repo_name,
                                        "is_upg": "upgrade" in repo_name
                                    })
        debug_log(f"Successfully fetched and parsed total of {len(comments)} comments combined.")
    except Exception as e:
        debug_log(f"Exception during 'gh api pulls/comments' fetch: {e}")
        pass
        
    return comments

def get_latest_pr_comment(odoo_pr_url: Optional[str], enterprise_pr_url: Optional[str], upgrade_pr_url: Optional[str] = None) -> Optional[dict]:
    """
    Fetches the absolute latest human PR comment from Odoo Community, Enterprise, or Upgrade PRs.
    """
    if not is_gh_authenticated():
        debug_log("Skipping GitHub comments lookup because 'gh' CLI is not authenticated.")
        return None
        
    odoo_pr_num = None
    if odoo_pr_url:
        match = re.search(r'/pull/(\d+)', odoo_pr_url)
        if match:
            odoo_pr_num = match.group(1)
            
    ent_pr_num = None
    if enterprise_pr_url:
        match = re.search(r'/pull/(\d+)', enterprise_pr_url)
        if match:
            ent_pr_num = match.group(1)
            
    upg_pr_num = None
    if upgrade_pr_url:
        match = re.search(r'/pull/(\d+)', upgrade_pr_url)
        if match:
            upg_pr_num = match.group(1)
            
    if not odoo_pr_num and not ent_pr_num and not upg_pr_num:
        debug_log("No linked Pull Requests found on batch, skipping comments lookup.")
        return None
        
    import concurrent.futures
    all_comments = []
    
    debug_log(f"Gathering latest PR comments from Odoo, Enterprise, and Upgrade PRs (Odoo PR: {odoo_pr_num}, Enterprise PR: {ent_pr_num}, Upgrade PR: {upg_pr_num})...")
    debug_log("Spawning concurrent ThreadPoolExecutor to fetch repo comments from GitHub...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        if odoo_pr_num:
            futures.append(executor.submit(fetch_repo_comments, "odoo/odoo", odoo_pr_num))
        if ent_pr_num:
            futures.append(executor.submit(fetch_repo_comments, "odoo/enterprise", ent_pr_num))
        if upg_pr_num:
            futures.append(executor.submit(fetch_repo_comments, "odoo/upgrade", upg_pr_num))
            
        for fut in concurrent.futures.as_completed(futures):
            try:
                all_comments.extend(fut.result())
            except Exception:
                continue
                
    BOT_LOGINS = {
        "robodoo", "fw-bot", "runbot", "github-actions[bot]", 
        "runbot-odoo", "runbot-enterprise", "mergebot"
    }
    
    human_comments = []
    for c in all_comments:
        user_lower = c["user"].lower()
        if any(bot in user_lower for bot in BOT_LOGINS):
            continue
        if not c["created_at"]:
            continue
        human_comments.append(c)
        
    if not human_comments:
        return None
        
    import datetime
    def parse_time(c_dict):
        iso_str = c_dict["created_at"].replace("Z", "")
        if "." in iso_str:
            iso_str = iso_str.split(".")[0]
        try:
            return datetime.datetime.fromisoformat(iso_str)
        except Exception:
            return datetime.datetime.min
            
    human_comments.sort(key=parse_time, reverse=True)
    latest = human_comments[0]
    
    # Sanitize the body text to a flat, single-line format
    body = latest.get("body", "")
    body_clean = " ".join(body.split())
    latest["body_clean"] = body_clean
    
    now = datetime.datetime.utcnow()
    c_time = parse_time(latest)
    delta = now - c_time
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0: total_seconds = 0
    
    if total_seconds < 60:
        relative = "just now"
    elif total_seconds < 3600:
        relative = f"{total_seconds // 60}m ago"
    elif total_seconds < 86400:
        relative = f"{total_seconds // 3600}h ago"
    else:
        days = total_seconds // 86400
        relative = "yesterday" if days == 1 else f"{days}d ago"
        
    latest["relative"] = relative
    debug_log(f"Latest comment resolved -> User: @{latest['user']} ({latest['relative']}), Body snippet: '{latest['body_clean'][:60]}...'")
    
    # Symmetrically extract the history of the last 10 comments chronologically
    history = []
    for c in human_comments[:10]:
        c_body = c.get("body", "")
        c_body_clean = " ".join(c_body.split())
        if len(c_body_clean) > 90:
            c_body_clean = c_body_clean[:90].strip() + "..."
            
        c_time = parse_time(c)
        c_delta = now - c_time
        c_seconds = int(c_delta.total_seconds())
        if c_seconds < 0: c_seconds = 0
        
        if c_seconds < 60:
            c_relative = "just now"
        elif c_seconds < 3600:
            c_relative = f"{c_seconds // 60}m ago"
        elif c_seconds < 86400:
            c_relative = f"{c_seconds // 3600}h ago"
        else:
            c_days = c_seconds // 86400
            c_relative = "yesterday" if c_days == 1 else f"{c_days}d ago"
            
        history.append({
            "user": c["user"],
            "relative": c_relative,
            "body": c_body,
            "body_clean": c_body_clean,
            "html_url": c["html_url"],
            "is_ent": c.get("is_ent", False),
            "is_upg": c.get("is_upg", False)
        })
        
    latest["history"] = history
    return latest

def extract_error_message(log_text: str, test_name: str) -> str:
    pos = log_text.find(test_name)
    if pos == -1:
        return ""
    chunk = log_text[pos:pos+2500]
    lines = chunk.splitlines()
    
    IGNORE_PATTERNS = (
        "adding readonly volume", "pointing to", "docker", "runbot",
        "database:", "using config file", "postgresql", "container",
        "starting server", "command:", "host:", "port:", "volume",
        "starting test"
    )
    
    for line in lines[1:35]:
        line_strip = line.strip()
        if not line_strip:
            continue
        if len(line_strip) > 3 and all(char in "-=_* " for char in line_strip):
            continue
        if any(pat in line_strip.lower() for pat in IGNORE_PATTERNS):
            continue
            
        clean_line = line_strip
        if any(level in line_strip for level in (" ERROR ", " _ERROR ", " INFO ", " WARNING ")):
            if ": " in line_strip:
                parts = line_strip.split(": ", 1)
                if len(parts) > 1:
                    clean_line = parts[1]
                
        clean_strip = clean_line.strip()
        if test_name in clean_strip and (clean_strip.startswith("ERROR:") or clean_strip.startswith("FAIL:") or clean_strip == test_name or "ERROR: " + test_name in line_strip or "FAIL: " + test_name in line_strip):
            continue
            
        clean_lower = clean_strip.lower()
        if any(x in clean_lower for x in ("assertionerror:", "error:", "exception:", "fail:", "stopiteration", "typeerror:", "valueerror:", "keyerror:", "attributeerror:")) or "raised" in clean_lower:
            return clean_strip[:120]
            
    for line in lines[1:15]:
        line_strip = line.strip()
        if not line_strip:
            continue
        if len(line_strip) > 3 and all(char in "-=_* " for char in line_strip):
            continue
        if any(pat in line_strip.lower() for pat in IGNORE_PATTERNS):
            continue
            
        clean_line = line_strip
        if any(level in line_strip for level in (" ERROR ", " _ERROR ", " INFO ", " WARNING ")):
            if ": " in line_strip:
                parts = line_strip.split(": ", 1)
                if len(parts) > 1:
                    clean_line = parts[1]
                
        clean_strip = clean_line.strip()
        if test_name in clean_strip and (clean_strip.startswith("ERROR:") or clean_strip.startswith("FAIL:") or clean_strip == test_name or "ERROR: " + test_name in line_strip or "FAIL: " + test_name in line_strip):
            continue
            
        if clean_strip:
            return clean_strip[:120]
            
    return ""

def fetch_failing_tests_from_batch(batch_url: str, verbose_level: int = 0) -> list:
    """
    Downloads the Runbot batch page, identifies failed builds, scrapes their detailed build pages,
    and extracts failing unit tests or static check errors from the logs.
    """
    if not batch_url:
        return []
        
    debug_log(f"Starting live failing tests scraping from batch URL: {batch_url} (verbose_level: {verbose_level})...")
    req_batch = urllib.request.Request(
        batch_url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req_batch, timeout=5) as response:
            html_batch = response.read().decode('utf-8')
            
        # 1. Parse failed build links from the batch slots
        failed_build_links = []
        blocks = re.findall(r'<div[^>]*class="[^"]*slot_button_group[^"]*"[^>]*>.*?</div>', html_batch, re.DOTALL)
        for b in blocks:
            if "btn-danger" in b or "btn-warning" in b:
                m = re.search(r'href="(/runbot/batch/\d+/build/\d+|/runbot/build/\d+)"', b)
                if m:
                    failed_build_links.append("https://runbot.odoo.com" + m.group(1))
        debug_log(f"Parsed {len(failed_build_links)} failed/warning build links inside batch: {failed_build_links}")
                    
        # Limit to checking at most 2 failed builds to keep execution extremely fast and safe
        tests = []
        for build_url in failed_build_links[:2]:
            try:
                debug_log(f"Scraping build detailed page to find logs: {build_url}...")
                req_build = urllib.request.Request(
                    build_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                )
                with urllib.request.urlopen(req_build, timeout=5) as resp_build:
                    html_build = resp_build.read().decode('utf-8')
                    
                # Find all .txt log links on the build page and de-duplicate them
                log_links = re.findall(r'href="(http[s]?://[^"]+/logs/[^"]+\.txt)"', html_build)
                unique_log_links = []
                for link in log_links:
                    if link not in unique_log_links:
                        unique_log_links.append(link)
                debug_log(f"Extracted log links from build page: {log_links} (deduplicated down to {len(unique_log_links)} unique logs)")
                
                # Symmetrically parse the inline log messages table if no separate log text links are present on the page
                if not unique_log_links:
                    debug_log("No separate text log files found on build page. Symmetrically parsing inline build logs...")
                    build_name = "build"
                    m_title = re.search(r'batch-\d+\s*\(([^)]+)\)', html_build, re.IGNORECASE)
                    if m_title:
                        build_name = m_title.group(1).strip().replace(" ", "_").lower()
                    else:
                        m_config = re.search(r'config\s+<strong>([^<]+)</strong>|config\s+([A-Za-z0-9_]+)', html_build, re.IGNORECASE)
                        if m_config:
                            build_name = (m_config.group(1) or m_config.group(2)).strip().lower()
                            
                    inline_logs = re.findall(
                        r'<td[^>]*class="bg-(danger|warning)-subtle"><span>(.*?)</span>',
                        html_build,
                        re.DOTALL
                    )
                    # Backup check for legacy tables containing explicit BOLD level headings
                    if not inline_logs:
                        legacy_logs = re.findall(
                            r'<td[^>]*><b>(WARNING|ERROR)</b>\s*</td>\s*<td[^>]*class="bg-[^"]*subtle"><span>(.*?)</span>',
                            html_build,
                            re.DOTALL
                        )
                        inline_logs = [(level.lower(), msg) for level, msg in legacy_logs]
                        
                    for level, msg in inline_logs[:5]:
                        clean_msg = re.sub(r'<[^>]+>', '', msg).strip()
                        display_name = f"{build_name}  ➔  {clean_msg}"
                        if display_name not in tests:
                            tests.append(display_name)
                
                # Symmetrically prioritize important test-related logs and filter/deprioritize setup logs to never miss failures
                important_logs = []
                other_logs = []
                for link in unique_log_links:
                    link_lower = link.lower()
                    if "restore" in link_lower or "pre_run_config" in link_lower or "install_all" in link_lower or "install_base" in link_lower:
                        other_logs.append(link)
                    elif "test" in link_lower or "lint" in link_lower or "migration" in link_lower:
                        important_logs.append(link)
                    else:
                        other_logs.append(link)
                
                prioritized_log_links = important_logs + other_logs
                debug_log(f"Prioritized log links order: {prioritized_log_links}")
                
                # Check at most 5 log files per build to avoid network overhead while capturing all tests
                for log_url in prioritized_log_links[:5]:
                    try:
                        debug_log(f"Downloading build log content from URL: {log_url}...")
                        req_log = urllib.request.Request(
                            log_url,
                            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                        )
                        # Fetch the entire log file to ensure we never truncate failures at the bottom
                        with urllib.request.urlopen(req_log, timeout=5) as resp_log:
                            log_text = resp_log.read().decode('utf-8', errors='ignore')
                        debug_log(f"Successfully downloaded full log file. Length: {len(log_text)} characters")
                        
                        tests_in_this_log = []
                        def add_to_tests(item):
                            if item not in tests:
                                tests.append(item)
                            if item not in tests_in_this_log:
                                tests_in_this_log.append(item)
                            
                        # 0. Symmetrically parse Odoo's final ThreadedServer summary list (absolute 100% accuracy!)
                        summary_matches = re.findall(
                            r'\b(?:Error|Failed):\s+(?:odoo\.)?(?:addons\.)?([A-Za-z0-9_]+)\.tests\.[A-Za-z0-9_]+\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)(?:\s*\([^\)]*\))?\s*-\s*([^\n]+)',
                            log_text
                        )
                        for addon, test_class, test_method, err_msg in summary_matches:
                            display_name = f"{test_class}.{test_method}"
                            if verbose_level >= 2:
                                clean_err = err_msg.strip()
                                display_name = f"{display_name}  ➔  {clean_err}"
                            add_to_tests(display_name)
                                
                        # A. Search for actual unittest failures in the unittest summary (e.g. ERROR: test_method (path.TestClass) or FAIL: test_method (path.TestClass))
                        unittest_matches = re.findall(r'\b(?:ERROR|FAIL):\s+(test_[A-Za-z0-9_]+)\s+\((?:[A-Za-z0-9_]+\.)*(Test[A-Za-z0-9_]+)\)', log_text)
                        for test_method, test_class in unittest_matches:
                            display_name = f"{test_class}.{test_method}"
                            if display_name not in tests:
                                if verbose_level >= 2:
                                    err_msg = extract_error_message(log_text, test_method)
                                    if err_msg:
                                        display_name = f"{display_name}  ➔  {err_msg}"
                                add_to_tests(display_name)
                                
                        # B. Search for direct ERROR/FAIL listings (e.g. ERROR: TestClass.test_method) or Tour/JS failures
                        direct_matches = re.findall(r'\b(?:ERROR|FAIL):\s+(Test[A-Za-z0-9_]+\.test_[A-Za-z0-9_]+)\b', log_text)
                        for m in direct_matches:
                            display_name = m
                            if display_name not in tests:
                                if verbose_level >= 2:
                                    err_msg = extract_error_message(log_text, m)
                                    if err_msg:
                                        display_name = f"{m}  ➔  {err_msg}"
                                add_to_tests(display_name)
                                    
                        tour_matches = re.findall(r'\b(?:tour|Tour)\s+([A-Za-z0-9_]+)\s+failed\b', log_text)
                        for m in tour_matches:
                            display_name = f"Tour.{m}"
                            if display_name not in tests:
                                if verbose_level >= 2:
                                    err_msg = extract_error_message(log_text, m) or "Tour failed"
                                    display_name = f"{display_name}  ➔  {err_msg}"
                                add_to_tests(display_name)
                                    
                        # C. If it is a static check / linter error, parse the log file name itself!
                        if "check_" in log_url or "lint" in log_url:
                            log_name = log_url.split("/")[-1].replace(".txt", "")
                            # Symmetrically guard linter fallback additions: only add if actual failures exist in this specific log text
                            log_text_lower = log_text.lower()
                            is_ruff = "ruff" in log_url.lower()
                            has_log_failures = (
                                is_ruff or
                                any(x in log_text_lower for x in ("fail:", "error:", "exception:", "style violation", "exit code")) or
                                ("failed" in log_text_lower and "0 failed" not in log_text_lower)
                            )
                            if not any(t in log_text for t in tests) and has_log_failures:
                                if log_name not in tests:
                                    if verbose_level >= 2:
                                        has_json = False
                                        if "ruff" in log_url.lower():
                                            # Symmetrically fetch the actual Ruff JSON report for high-fidelity errors!
                                            try:
                                                json_url = log_url.replace(".txt", "-ruff-output.json")
                                                debug_log(f"Ruff log detected, resolving its JSON style report URL: {json_url}...")
                                                req_json = urllib.request.Request(
                                                    json_url,
                                                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                                                )
                                                with urllib.request.urlopen(req_json, timeout=5) as resp_json:
                                                    raw_json = json.loads(resp_json.read().decode('utf-8'))
                                                    if isinstance(raw_json, list) and raw_json:
                                                        debug_log(f"Successfully downloaded Ruff JSON report, parsed {len(raw_json)} style violations.")
                                                        for item in raw_json[:3]:  # Show first 3 violations separately
                                                            code = item.get("code", "")
                                                            msg = item.get("message", "")
                                                            filename = item.get("filename", "")
                                                            rel_path = filename.replace("/data/build/", "")
                                                            row = item.get("location", {}).get("row", 0)
                                                            col = item.get("location", {}).get("column", 0)
                                                            display_name = f"{log_name}  ➔  {rel_path}:{row}:{col}  ➔  [{code}] {msg}"
                                                            add_to_tests(display_name)
                                                        has_json = True
                                            except Exception as e:
                                                debug_log(f"Failed to fetch/parse Ruff JSON report ({e}), falling back to text log parsing.")
                                                has_json = False
                                        else:
                                            has_json = False
                                                
                                        if not has_json or not any(log_name in t for t in tests):
                                            err_msg = extract_error_message(log_text, log_name) or extract_error_message(log_text, "failed")
                                            if err_msg:
                                                display_name = f"{log_name}  ➔  {err_msg}"
                                                add_to_tests(display_name)
                                    else:
                                        add_to_tests(log_name)
                                        
                        # E. Fallback: If this log is from a failed build, but we found no unittests or tours,
                        # scan for uncaught Python traceback exceptions!
                        if not tests_in_this_log and "restore" not in log_url.lower() and "install_all" not in log_url.lower() and "install_base" not in log_url.lower():
                            log_name = log_url.split("/")[-1].replace(".txt", "")
                            traceback_exceptions = []
                            for match in re.finditer(r"Traceback \(most recent call last\):", log_text):
                                pos = match.start()
                                chunk = log_text[pos:pos+2500]
                                lines = chunk.splitlines()
                                exception_line = ""
                                for line in lines[1:]:
                                    line_strip = line.strip()
                                    if not line_strip:
                                        continue
                                    if line.startswith("  ") or line.startswith("    "):
                                        continue
                                    if ":" in line_strip and not line_strip.startswith("File "):
                                        exception_line = line_strip
                                        break
                                if exception_line and exception_line not in traceback_exceptions:
                                    traceback_exceptions.append(exception_line)
                                    
                            for exc in traceback_exceptions[:3]:
                                display_name = f"{log_name}  ➔  {exc[:120]}"
                                add_to_tests(display_name)
                    except Exception:
                        continue
            except Exception:
                continue
                
        return tests
    except Exception:
        return []

def check_branch_status_and_comments(branch_name: str, skip_comments: bool = False, verbose_level: int = 0) -> Optional[dict]:
    """
    Unified high-speed worker function to fetch runbot status and comments sequentially in a single worker thread.
    """
    try:
        res = query_branch_status(branch_name)
        if not res:
            return None
            
        # Safely unpack supporting both 8-element and 9-element tuple formats
        batch_url = res[0]
        ts_str = res[1]
        success = res[2]
        failed = res[3]
        warning = res[4]
        running = res[5]
        odoo_pr = res[6] if len(res) > 6 else None
        enterprise_pr = res[7] if len(res) > 7 else None
        upgrade_pr = res[8] if len(res) > 8 else None
        
        comment_data = None
        if not skip_comments:
            try:
                comment_data = get_latest_pr_comment(odoo_pr, enterprise_pr, upgrade_pr)
            except Exception:
                pass
                
        failing_tests = []
        if failed > 0 or warning > 0:
            try:
                failing_tests = fetch_failing_tests_from_batch(batch_url, verbose_level)
            except Exception:
                pass
                
        return {
            "batch_url": batch_url,
            "ts_str": ts_str,
            "success": success,
            "failed": failed,
            "warning": warning,
            "running": running,
            "odoo_pr": odoo_pr,
            "enterprise_pr": enterprise_pr,
            "upgrade_pr": upgrade_pr,
            "comment_data": comment_data,
            "failing_tests": failing_tests
        }
    except Exception:
        return None
