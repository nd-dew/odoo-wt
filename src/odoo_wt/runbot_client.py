import urllib.request
import re
from typing import Optional, Tuple

def find_runbot_batch_url(branch_name: str) -> Optional[Tuple[str, str]]:
    """
    Queries Runbot search for the given branch and returns a tuple (batch_url, timestamp_str)
    of the most recent batch, or None.
    """
    if not branch_name:
        return None
        
    search_url = f"https://runbot.odoo.com/runbot?search={branch_name}"
    req = urllib.request.Request(
        search_url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
        
        # Odoo Runbot links batches inside href="/runbot/batch/<id>" with title="YYYY-MM-DD HH:MM:SS"
        match = re.search(r'href="/runbot/batch/(\d+)" title="([^"]+)"', html)
        if match:
            batch_id = match.group(1)
            timestamp_str = match.group(2)
            return f"https://runbot.odoo.com/runbot/batch/{batch_id}", timestamp_str
            
        # Fallback to match just batch ID if title is not present
        match_id = re.search(r'href="/runbot/batch/(\d+)"', html)
        if match_id:
            batch_id = match_id.group(1)
            return f"https://runbot.odoo.com/runbot/batch/{batch_id}", ""
    except Exception:
        pass
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
        
        success = html.count("btn-success")
        failed = html.count("btn-danger")
        warning = html.count("btn-warning")
        running = html.count("fa-spinner")
        
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
        
    search_url = f"https://runbot.odoo.com/runbot?search={branch_name}"
    req = urllib.request.Request(
        search_url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode('utf-8')
            
        # Parse Batch ID and Timestamp
        match = re.search(r'href="/runbot/batch/(\d+)" title="([^"]+)"', html)
        if match:
            batch_id = match.group(1)
            ts_str = match.group(2)
            batch_url = f"https://runbot.odoo.com/runbot/batch/{batch_id}"
            
            # Slice the HTML block strictly to just this batch tile to count its classes safely
            tile_start = html.find(f'href="/runbot/batch/{batch_id}"')
            block = html[tile_start:tile_start+4000] if tile_start != -1 else html
            
            success = block.count("btn-success")
            failed = block.count("btn-danger")
            warning = block.count("btn-warning")
            running = block.count("fa-spinner")
            
            # If the batch exists but has no completed or spinning builds yet, it is preparing/pending
            if success == 0 and failed == 0 and warning == 0 and running == 0:
                running = 1
            
            # Parse linked Pull Requests from the entire HTML
            odoo_pr = None
            enterprise_pr = None
            upgrade_pr = None
            pr_links = re.findall(r'href="(https://github.com/odoo(?:-dev)?/([^/]+)/pull/\d+)"', html)
            for url, repo in pr_links:
                if repo == "odoo" and not odoo_pr:
                    odoo_pr = url
                elif repo == "enterprise" and not enterprise_pr:
                    enterprise_pr = url
                elif repo == "upgrade" and not upgrade_pr:
                    upgrade_pr = url
            
            return batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr
            
        # Fallback if title is not present
        match_id = re.search(r'href="/runbot/batch/(\d+)"', html)
        if match_id:
            batch_id = match_id.group(1)
            batch_url = f"https://runbot.odoo.com/runbot/batch/{batch_id}"
            
            tile_start = html.find(f'href="/runbot/batch/{batch_id}"')
            block = html[tile_start:tile_start+4000] if tile_start != -1 else html
            
            success = block.count("btn-success")
            failed = block.count("btn-danger")
            warning = block.count("btn-warning")
            running = block.count("fa-spinner")
            
            # If the batch exists but has no completed or spinning builds yet, it is preparing/pending
            if success == 0 and failed == 0 and warning == 0 and running == 0:
                running = 1
            
            # Parse linked Pull Requests from the entire HTML
            odoo_pr = None
            enterprise_pr = None
            upgrade_pr = None
            pr_links = re.findall(r'href="(https://github.com/odoo(?:-dev)?/([^/]+)/pull/\d+)"', html)
            for url, repo in pr_links:
                if repo == "odoo" and not odoo_pr:
                    odoo_pr = url
                elif repo == "enterprise" and not enterprise_pr:
                    enterprise_pr = url
                elif repo == "upgrade" and not upgrade_pr:
                    upgrade_pr = url
            
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
        subprocess.run(["gh", "auth", "status"], capture_output=True, check=True)
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
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
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
                                    comments.append({
                                        "user": login,
                                        "created_at": item.get("createdAt", ""),
                                        "html_url": item.get("url", ""),
                                        "body": item.get("body", ""),
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
                                    comments.append({
                                        "user": login,
                                        "created_at": item.get("submittedAt", ""),
                                        "html_url": f"https://github.com/{repo_name}/pull/{pr_number}",
                                        "body": item.get("body", ""),
                                        "is_ent": "enterprise" in repo_name,
                                        "is_upg": "upgrade" in repo_name
                                    })
    except Exception:
        pass
    return comments

def get_latest_pr_comment(odoo_pr_url: Optional[str], enterprise_pr_url: Optional[str], upgrade_pr_url: Optional[str] = None) -> Optional[dict]:
    """
    Fetches the absolute latest human PR comment from Odoo Community, Enterprise, or Upgrade PRs.
    """
    if not is_gh_authenticated():
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
        return None
        
    import concurrent.futures
    all_comments = []
    
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

def fetch_failing_tests_from_batch(batch_url: str) -> list:
    """
    Downloads the Runbot batch page, identifies failed builds, scrapes their detailed build pages,
    and extracts failing unit tests or static check errors from the logs.
    """
    if not batch_url:
        return []
        
    req_batch = urllib.request.Request(
        batch_url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    try:
        with urllib.request.urlopen(req_batch, timeout=5) as response:
            html_batch = response.read().decode('utf-8')
            
        # 1. Parse failed build links from the batch slots
        failed_build_links = []
        blocks = re.findall(r'<div class="btn-group[^"]*slot_button_group">.*?</div>', html_batch, re.DOTALL)
        for b in blocks:
            if "btn-danger" in b or "btn-warning" in b:
                m = re.search(r'href="(/runbot/batch/\d+/build/\d+|/runbot/build/\d+)"', b)
                if m:
                    failed_build_links.append("https://runbot.odoo.com" + m.group(1))
                    
        # Limit to checking at most 2 failed builds to keep execution extremely fast and safe
        tests = []
        for build_url in failed_build_links[:2]:
            try:
                req_build = urllib.request.Request(
                    build_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                )
                with urllib.request.urlopen(req_build, timeout=5) as resp_build:
                    html_build = resp_build.read().decode('utf-8')
                    
                # Find all .txt log links on the build page
                log_links = re.findall(r'href="(http[s]?://[^"]+/logs/[^"]+\.txt)"', html_build)
                
                # Check at most 3 log files per build to avoid network overhead
                for log_url in log_links[:3]:
                    try:
                        req_log = urllib.request.Request(
                            log_url,
                            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                        )
                        # Fetch first 100KB of the log file
                        with urllib.request.urlopen(req_log, timeout=5) as resp_log:
                            log_text = resp_log.read(100000).decode('utf-8', errors='ignore')
                            
                        # A. Search for full TestClass.test_method formats (highest signal!)
                        matches_class = re.findall(r'\b(Test[A-Za-z0-9_]+\.test_[A-Za-z0-9_]+)\b', log_text)
                        for m in matches_class:
                            if m not in tests:
                                tests.append(m)
                                
                        # B. Search for standalone test_xxxx names
                        matches_raw = re.findall(r'\b(test_[A-Za-z0-9_]{6,})\b', log_text)
                        for m in matches_raw:
                            if m not in tests and not any(m in existing for existing in tests):
                                if not any(fw in m.lower() for fw in ("test_option", "test_config", "test_success", "test_param")):
                                    tests.append(m)
                                    
                        # C. If it is a static check / linter error, parse the log file name itself!
                        if "check_" in log_url or "lint" in log_url:
                            log_name = log_url.split("/")[-1].replace(".txt", "")
                            if not any(t in log_text for t in tests):
                                if log_name not in tests:
                                    tests.append(log_name)
                    except Exception:
                        continue
            except Exception:
                continue
                
        return tests
    except Exception:
        return []

def check_branch_status_and_comments(branch_name: str, skip_comments: bool = False) -> Optional[dict]:
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
        if failed > 0:
            try:
                failing_tests = fetch_failing_tests_from_batch(batch_url)
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
