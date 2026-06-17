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
            
            # Parse linked Pull Requests from the entire HTML
            odoo_pr = None
            enterprise_pr = None
            pr_links = re.findall(r'href="(https://github.com/odoo(?:-dev)?/([^/]+)/pull/\d+)"', html)
            for url, repo in pr_links:
                if repo == "odoo" and not odoo_pr:
                    odoo_pr = url
                elif repo == "enterprise" and not enterprise_pr:
                    enterprise_pr = url
            
            return batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr
            
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
            
            # Parse linked Pull Requests from the entire HTML
            odoo_pr = None
            enterprise_pr = None
            pr_links = re.findall(r'href="(https://github.com/odoo(?:-dev)?/([^/]+)/pull/\d+)"', html)
            for url, repo in pr_links:
                if repo == "odoo" and not odoo_pr:
                    odoo_pr = url
                elif repo == "enterprise" and not enterprise_pr:
                    enterprise_pr = url
            
            return batch_url, "", success, failed, warning, running, odoo_pr, enterprise_pr
    except Exception:
        pass
    return None
