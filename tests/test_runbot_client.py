import pytest
import json
import os
import sys
import re
import urllib.request
from pathlib import Path
from odoo_wt.main_tui import OdooWtApp
from odoo_wt.setup_wizard import WizardApp
from odoo_wt.app_config import config_mgr
from odoo_wt.system_discovery import parse_branch_name, shorten_path, expand_path
from textual.widgets import TabbedContent, Select

@pytest.fixture(autouse=True)
def mock_config_path(tmp_path, monkeypatch):
    config_dir = tmp_path / ".config"
    config_dir.mkdir()
    config_file = config_dir / "odoo-wt.json"
    log_file = config_dir / "odoo-wt-logs.jsonl"
    
    import odoo_wt.app_config as ac
    monkeypatch.setattr(ac, "DEFAULT_CONFIG_FILE", config_file)
    monkeypatch.setattr(ac, "DEFAULT_LOG_FILE", log_file)
    monkeypatch.setattr(config_mgr, "config_file", config_file)
    monkeypatch.setattr(config_mgr, "log_file", log_file)
    
    # SAFETY SHIELD: Disable all disk writes during tests
    monkeypatch.setattr(config_mgr, "is_test_mode", True)
    
    # Pre-populate with valid defaults to avoid validation errors
    config_mgr.config = config_mgr._get_defaults()
    config_mgr.config["config_path"] = str(config_file)
    config_mgr.config["log_path"] = str(log_file)

    return config_file

def test_runbot_client(monkeypatch):
    from odoo_wt.runbot_client import find_runbot_batch_url, check_batch_details
    
    class MockResponse:
        def __init__(self, data):
            self.data = data
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
            
    def mock_urlopen_search(req, *args, **kwargs):
        return MockResponse(b'<html><body><a href="/runbot/batch/2588843" title="2026-06-17 06:14:59">Batch</a></body></html>')
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_search)
    res = find_runbot_batch_url("17.0-fix-pian")
    assert res == ("https://runbot.odoo.com/runbot/batch/2588843", "2026-06-17 06:14:59")
    
    def mock_urlopen_batch(req, *args, **kwargs):
        return MockResponse(
            b'<div class="slot_button_group"><span class="btn btn-success disabled" title="matched"></span><span class="slot_name"></span></div>'
            b'<div class="slot_button_group"><span class="btn btn-success disabled" title="matched"></span><span class="slot_name"></span></div>'
            b'<div class="slot_button_group"><span class="btn btn-success disabled" title="matched"></span><span class="slot_name"></span></div>'
            b'<div class="slot_button_group"><span class="btn btn-danger disabled" title="failed"></span><span class="slot_name"></span></div>'
            b'class="fa-spinner" fa-spinner'
        )
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_batch)
    success, failed, warning, running = check_batch_details("https://runbot.odoo.com/runbot/batch/2588843")
    assert success == 3
    assert failed == 1
    assert warning == 0
    assert running == 2

def test_query_branch_status(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    
    class MockResponse:
        def __init__(self, data):
            self.data = data
        def read(self):
            return self.data
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
            
    def mock_urlopen_search(req, *args, **kwargs):
        return MockResponse(
            b'<html><body><a href="/runbot/batch/2588843" title="2026-06-17 06:14:59">Batch</a>'
            b'<div class="slot_button_group"><span class="btn btn-success disabled" title="matched"></span><span class="slot_name"></span></div>'
            b'<div class="slot_button_group"><span class="btn btn-danger disabled" title="failed"></span><span class="slot_name"></span></div>'
            b'class="fa-spinner"'
            b'<a class="dropdown-item" href="https://github.com/odoo-dev/odoo/pull/5161" title="View PR">'
            b'<a class="fa-sign-in btn btn-info" href="https://github.com/odoo-dev/enterprise/pull/1356" title="View PR">'
            b'</body></html>'
        )
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_search)
    res = query_branch_status("17.0-fix-pian")
    assert res == (
        "https://runbot.odoo.com/runbot/batch/2588843", 
        "2026-06-17 06:14:59", 
        1, 1, 0, 1,
        "https://github.com/odoo-dev/odoo/pull/5161",
        "https://github.com/odoo-dev/enterprise/pull/1356",
        None
    )

def test_get_latest_pr_comment(monkeypatch):
    from odoo_wt.runbot_client import get_latest_pr_comment
    
    # Mock authentication status
    monkeypatch.setattr("odoo_wt.runbot_client.is_gh_authenticated", lambda: True)
    
    # Mock fetch_repo_comments to return custom fake comments
    def mock_fetch_repo_comments(repo_name, pr_number):
        if repo_name == "odoo/odoo":
            return [
                {"user": "robodoo", "created_at": "2026-06-18T10:00:00Z", "html_url": "link1", "is_ent": False},
                {"user": "Matthieu", "created_at": "2026-06-18T08:00:00Z", "html_url": "link2", "is_ent": False}
            ]
        elif repo_name == "odoo/enterprise":
            return [
                {
                    "user": "xavierbol", 
                    "created_at": "2026-06-18T09:00:00Z", 
                    "html_url": "link3", 
                    "is_ent": True,
                    "body": "This is an extremely long code review comment written by xavierbol to test the 50-char ellipses truncation guard inside odoo-wt!"
                }
            ]
        return []
        
    monkeypatch.setattr("odoo_wt.runbot_client.fetch_repo_comments", mock_fetch_repo_comments)
    
    # Call comment resolver with simulated Community and Enterprise links
    latest = get_latest_pr_comment(
        "https://github.com/odoo/odoo/pull/12345",
        "https://github.com/odoo/enterprise/pull/5678"
    )
    
    assert latest is not None
    # xavierbol (09:00:00) is newer than Matthieu (08:00:00) and robodoo (10:00:00) is filtered as a bot!
    assert latest["user"] == "xavierbol"
    assert latest["html_url"] == "link3"
    assert latest["is_ent"] is True
    # Full untruncated body
    assert latest["body_clean"] == "This is an extremely long code review comment written by xavierbol to test the 50-char ellipses truncation guard inside odoo-wt!"

def test_fetch_failing_tests_from_batch(monkeypatch):
    from odoo_wt.runbot_client import fetch_failing_tests_from_batch
    
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch" in url and "build" not in url:
            return MockResponse(
                '<div class="btn-group slot_button_group">\n'
                '  <span class="btn btn-danger"></span>\n'
                '  <a href="/runbot/batch/123/build/456">Build</a>\n'
                '</div>'
            )
        elif "build" in url:
            return MockResponse('href="http://runbot.odoo.com/logs/job_20_test.txt"')
        else:
            return MockResponse(
                'Some test logs...\n'
                'ERROR: test_mail_sending (odoo.TestMail)\n'
                'FAIL: TestDiscuss.test_channel_creation\n'
                'test_options is not a real test.'
            )
            
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    tests = fetch_failing_tests_from_batch("https://runbot.odoo.com/batch/123")
    assert "TestMail.test_mail_sending" in tests
    assert "TestDiscuss.test_channel_creation" in tests
    assert "test_options" not in tests

def test_fetch_failing_tests_from_batch_with_vv(monkeypatch):
    from odoo_wt.runbot_client import fetch_failing_tests_from_batch
    
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch" in url and "build" not in url:
            return MockResponse(
                '<div class="btn-group slot_button_group">\n'
                '  <span class="btn btn-danger"></span>\n'
                '  <a href="/runbot/batch/123/build/456">Build</a>\n'
                '</div>'
            )
        elif "build" in url:
            return MockResponse('href="http://runbot.odoo.com/logs/job_20_test.txt"')
        else:
            return MockResponse(
                'ERROR: test_mail_sending (odoo.TestMail)\n'
                'AssertionError: expected False but got True\n'
                'FAIL: TestDiscuss.test_channel_creation\n'
                'ValueError: cannot create channel'
            )
            
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    tests = fetch_failing_tests_from_batch("https://runbot.odoo.com/batch/123", verbose_level=2)
    assert any("TestMail.test_mail_sending" in t and "AssertionError" in t for t in tests)
    assert any("TestDiscuss.test_channel_creation" in t and "ValueError" in t for t in tests)

def test_fetch_failing_tests_prioritization(monkeypatch):
    from odoo_wt.runbot_client import fetch_failing_tests_from_batch
    
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch" in url and "build" not in url:
            # Symmetrically return batch with a slot button group that has btn-danger status (failed!)
            return MockResponse(
                '<div class="btn-group slot_button_group">\n'
                '  <span class="btn btn-danger disabled" title="failed"></span>\n'
                '  <a href="/runbot/batch/123/build/456" class="slot_name">Build</a>\n'
                '</div>'
            )
        elif "build/456" in url:
            # Symmetrically return build page with many logs, including install_all.txt, restore.txt, and finally start_post_install_tests.txt
            return MockResponse(
                'href="http://runbot.odoo.com/logs/install_all.txt"\n'
                'href="http://runbot.odoo.com/logs/restore.txt"\n'
                'href="http://runbot.odoo.com/logs/start_post_install_tests.txt"\n'
            )
        elif "start_post_install_tests.txt" in url:
            # Symmetrically return mock traceback for the failing test
            return MockResponse(
                'ERROR: test_update_preview_x2m_commands (odoo.TestAiToolUpdateRecords)\n'
                'AssertionError: Expected 2 blank lines, found 1'
            )
        else:
            # For other non-prioritized setup logs (like install_all or restore), return no failures
            return MockResponse("Successfully set up container with no errors")
            
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    tests = fetch_failing_tests_from_batch("https://runbot.odoo.com/batch/123")
    assert "TestAiToolUpdateRecords.test_update_preview_x2m_commands" in tests

def test_query_branch_status_empty_batch_is_running(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    # Mock search response returning an active preparing batch with NO completed builds yet
    def mock_urlopen(request, *args, **kwargs):
        html_content = (
            'href="/runbot/batch/2598492" title="2026-06-20 18:00:00"\n'
            '  <div>preparing</div>'
        )
        return MockResponse(html_content)
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    res = query_branch_status("master-timeline_media_synchronization-pian")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, ent_pr, upg_pr = res
    assert batch_url == "https://runbot.odoo.com/runbot/batch/2598492"
    assert ts_str == "2026-06-20 18:00:00"
    assert success == 0
    assert failed == 0
    assert warning == 0
    # Symmetrically asserted to fall back to 1 (Running) instead of 0 (Passed)!
    assert running == 1

def test_fetch_repo_comments_with_inline_reviews(monkeypatch):
    from odoo_wt.runbot_client import fetch_repo_comments
    
    class MockResponse:
        def __init__(self, stdout):
            self.stdout = stdout
            self.stderr = ""
            
    def mock_run(cmd, **kwargs):
        if "view" in cmd:
            # Return empty reviews/comments list to isolate inline parsing
            return MockResponse('{"comments": [], "reviews": []}')
        elif "api" in cmd:
            # Return mocked inline comments list
            return MockResponse(
                '[\n'
                '  {\n'
                '    "user": {"login": "Brieuc-brd"},\n'
                '    "created_at": "2026-06-22T10:00:00Z",\n'
                '    "html_url": "https://github.com/comment/123",\n'
                '    "body": "I don\'t think this is necessary."\n'
                '  }\n'
                ']'
            )
        return MockResponse("")
        
    monkeypatch.setattr("subprocess.run", mock_run)
    
    comments = fetch_repo_comments("odoo/enterprise", "121346")
    assert len(comments) == 1
    c = comments[0]
    assert c["user"] == "Brieuc-brd"
    assert c["body"] == "I don't think this is necessary."
    assert c["html_url"] == "https://github.com/comment/123"

def test_real_runbot_batch_2614468(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    import os
    
    path = "tests/fixtures/batch_2614468_completed.html"
    if not os.path.exists(path):
        path = "/tmp/batch_2614468_completed.html"
        
    with open(path, "r", encoding="utf-8") as f:
        real_html = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch" in url:
            return MockResponse(real_html)
        else:
            # Symmetrically return an index page containing the batch link pointing to our detailed HTML
            mock_index = (
                '<div class="row bundle_row">\n'
                '  <a href="https://github.com/odoo/odoo/pull/123">PR 123</a>\n'
                '  <a href="/runbot/batch/2614468" title="2026-06-30 10:41:44">Batch</a>\n'
                '</div>'
            )
            return MockResponse(mock_index)
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    res = query_branch_status("master")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    
    assert "2614468" in batch_url
    assert success == 14
    assert failed == 0
    assert warning == 0
    assert running == 0

def test_real_runbot_batch_2615841_running(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    import os
    
    path = "tests/fixtures/batch_2615841_running_with_checkstyle_error.html"
    if not os.path.exists(path):
        path = "/tmp/batch_2615841_running_with_checkstyle_error.html"
        
    with open(path, "r", encoding="utf-8") as f:
        real_html = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch" in url:
            return MockResponse(real_html)
        else:
            mock_index = (
                '<div class="row bundle_row">\n'
                '  <a href="https://github.com/odoo/odoo/pull/456">PR 456</a>\n'
                '  <a href="/runbot/batch/2615841" title="2026-06-30 15:10:00">Batch</a>\n'
                '</div>'
            )
            return MockResponse(mock_index)
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    res = query_branch_status("master")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    
    assert "2615841" in batch_url
    assert success == 5
    assert failed == 1
    assert warning == 1
    assert running == 3

def test_real_runbot_batch_2614551_completed_with_ci_failures(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    import os
    
    path = "tests/fixtures/batch_2614551_completed_with_ci_failures.html"
    if not os.path.exists(path):
        path = "/tmp/batch_2614551_completed_with_ci_failures.html"
        
    with open(path, "r", encoding="utf-8") as f:
        real_html = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch" in url:
            return MockResponse(real_html)
        else:
            mock_index = (
                '<div class="row bundle_row">\n'
                '  <a href="https://github.com/odoo/odoo/pull/789">PR 789</a>\n'
                '  <a href="/runbot/batch/2614551" title="2026-06-30 16:20:00">Batch</a>\n'
                '</div>'
            )
            return MockResponse(mock_index)
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    res = query_branch_status("master")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    
    assert "2614551" in batch_url
    assert success == 8
    assert failed == 2
    assert warning == 1
    assert running == 0

def test_real_runbot_batch_2615870_running_and_green(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    import os
    
    path = "tests/fixtures/batch_2615870_running_and_green.html"
    if not os.path.exists(path):
        path = "/tmp/batch_2615870_running_and_green.html"
        
    with open(path, "r", encoding="utf-8") as f:
        real_html = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch" in url:
            return MockResponse(real_html)
        else:
            mock_index = (
                '<div class="row bundle_row">\n'
                '  <a href="https://github.com/odoo/odoo/pull/999">PR 999</a>\n'
                '  <a href="/runbot/batch/2615870" title="2026-06-30 18:05:00">Batch</a>\n'
                '</div>'
            )
            return MockResponse(mock_index)
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    res = query_branch_status("master")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    
    assert "2615870" in batch_url
    assert ts_str == "2026-06-30 18:05:15"
    assert success == 12
    assert failed == 0
    assert warning == 0
    assert running == 2

def test_real_runbot_batch_2613019_completed_with_massive_failures(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    import os
    
    path = "tests/fixtures/batch_2613019_completed_with_massive_failures.html"
    if not os.path.exists(path):
        path = "/tmp/batch_2613019_completed_with_massive_failures.html"
        
    with open(path, "r", encoding="utf-8") as f:
        real_html = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch" in url:
            return MockResponse(real_html)
        else:
            mock_index = (
                '<div class="row bundle_row">\n'
                '  <a href="https://github.com/odoo/odoo/pull/111">PR 111</a>\n'
                '  <a href="/runbot/batch/2613019" title="2026-06-30 19:10:00">Batch</a>\n'
                '</div>'
            )
            return MockResponse(mock_index)
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    res = query_branch_status("master")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    
    assert "2613019" in batch_url
    assert success == 12
    assert failed == 24
    assert warning == 6
    assert running == 0

def test_real_runbot_batch_2615942_running_and_green(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    import os
    
    path = "tests/fixtures/batch_2615942_running_and_green.html"
    if not os.path.exists(path):
        path = "/tmp/batch_2615942_running_and_green.html"
        
    with open(path, "r", encoding="utf-8") as f:
        real_html = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch" in url:
            return MockResponse(real_html)
        else:
            mock_index = (
                '<div class="row bundle_row">\n'
                '  <a href="https://github.com/odoo/odoo/pull/222">PR 222</a>\n'
                '  <a href="/runbot/batch/2615942" title="2026-06-30 19:20:00">Batch</a>\n'
                '</div>'
            )
            return MockResponse(mock_index)
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    res = query_branch_status("master")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    
    assert "2615942" in batch_url
    assert success == 12
    assert failed == 0
    assert warning == 0
    assert running == 1

def test_real_runbot_batch_2616450_parallel_failures(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status, fetch_failing_tests_from_batch
    import os
    
    batch_path = "tests/fixtures/batch_2616450_failing_with_parallel_child_tests.html"
    build_path = "tests/fixtures/build_116110236_parent.html"
    ai_log_path = "tests/fixtures/log_116111351_start_post_install_tests.txt"
    lint_log_path = "tests/fixtures/log_116110245_start_test_lint.txt"
    
    with open(batch_path, "r", encoding="utf-8") as f:
        batch_html = f.read()
    with open(build_path, "r", encoding="utf-8") as f:
        build_html = f.read()
    with open(ai_log_path, "r", encoding="utf-8") as f:
        ai_log = f.read()
    with open(lint_log_path, "r", encoding="utf-8") as f:
        lint_log = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch/2616450/build" in url or "build/116110236" in url:
            return MockResponse(build_html)
        elif "batch" in url:
            return MockResponse(batch_html)
        elif "116111351" in url and "start_post_install_tests" in url:
            return MockResponse(ai_log)
        elif "116110245" in url and "start_test_lint" in url:
            return MockResponse(lint_log)
        else:
            # Symmetrically return an index page containing the batch link pointing to our detailed HTML
            mock_index = (
                '<div class="row bundle_row">\n'
                '  <a href="https://github.com/odoo/odoo/pull/456">PR 456</a>\n'
                '  <a href="/runbot/batch/2616450" title="2026-06-30 15:10:00">Batch</a>\n'
                '</div>'
            )
            return MockResponse(mock_index)
            
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    # 1. Test status parsing
    res = query_branch_status("master")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    assert "2616450" in batch_url
    assert success == 12
    assert failed == 1
    assert warning == 0
    assert running == 0
    
    # 2. Test failed tests extraction
    tests = fetch_failing_tests_from_batch("https://runbot.odoo.com/runbot/batch/2616450", verbose_level=2)
    
    # Verify that start_test_lint is NOT reported as failed because its log was successful
    assert "start_test_lint" not in tests
    
    # Verify that the actual failing AI tests are detected and reported with clean, high-signal traceback details
    assert "TestAISession.test_tool_confirmation_multi_confirmation  ➔  StopIteration" in tests
    assert "TestAISession.test_tool_confirmation_request_w_final_message  ➔  StopIteration" in tests
    assert "TestAiToolUpdateRecords.test_update_records_tool  ➔  StopIteration" in tests
    assert "TestAIMethods.test_ai_methods_call_without_error  ➔  TestAICommon._prepare_default_tools() takes [...]" in tests

def test_query_branch_status_with_raw_batch_id(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status
    import os
    
    path = "tests/fixtures/batch_2616450_failing_with_parallel_child_tests.html"
    with open(path, "r", encoding="utf-8") as f:
        real_html = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        assert "batch/2616450" in url
        return MockResponse(real_html)
        
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    res = query_branch_status("2616450")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    
    assert "2616450" in batch_url
    assert success == 12
    assert failed == 1
    assert warning == 0
    assert running == 0

def test_real_runbot_batch_2618484_traceback_fallback(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status, fetch_failing_tests_from_batch
    import os
    
    batch_path = "tests/fixtures/batch_2618484_failing_with_traceback_fallback.html"
    build_03_path = "tests/fixtures/build_116156703_parent.html"
    post_install_log_path = "tests/fixtures/log_116157795_start_post_install_tests.txt"
    ruff_log_path = "tests/fixtures/log_116156707_check_style_ruff.txt"
    ruff_json_path = "tests/fixtures/log_116156707_check_style_ruff-ruff-output.json"
    
    with open(batch_path, "r", encoding="utf-8") as f:
        batch_html = f.read()
    with open(build_03_path, "r", encoding="utf-8") as f:
        build_03_html = f.read()
    with open(post_install_log_path, "r", encoding="utf-8") as f:
        post_install_log = f.read()
    with open(ruff_log_path, "r", encoding="utf-8") as f:
        ruff_log = f.read()
    with open(ruff_json_path, "r", encoding="utf-8") as f:
        ruff_json = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch/2618484/build/116156703" in url:
            return MockResponse(build_03_html)
        elif "batch/2618484/build/116156707" in url:
            mock_07_parent = (
                '<a href="http://runbot321.odoo.com/runbot/static/build/116156707-master/logs/check_style_ruff.txt">Ruff Log</a>'
            )
            return MockResponse(mock_07_parent)
        elif "batch/2618484" in url:
            return MockResponse(batch_html)
        elif "116157795" in url and "start_post_install_tests" in url:
            return MockResponse(post_install_log)
        elif "116156707" in url and "check_style_ruff-ruff-output.json" in url:
            return MockResponse(ruff_json)
        elif "116156707" in url and "check_style_ruff" in url:
            return MockResponse(ruff_log)
        else:
            return MockResponse("Successfully completed with no errors")
            
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    def mock_urlopen_index(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "static/build" in url or "batch" in url:
            return mock_urlopen(request, *args, **kwargs)
        else:
            mock_index = (
                '<div class="row bundle_row">\n'
                '  <a href="https://github.com/odoo/odoo/pull/123">PR 123</a>\n'
                '  <a href="/runbot/batch/2618484" title="2026-07-01 16:10:00">Batch</a>\n'
                '</div>'
            )
            return MockResponse(mock_index)
            
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_index)
    
    res = query_branch_status("master")
    assert res is not None
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    assert "2618484" in batch_url
    assert success == 8
    assert failed == 2
    assert warning == 1
    assert running == 0
    
    # 2. Test failed tests extraction
    tests = fetch_failing_tests_from_batch("https://runbot.odoo.com/runbot/batch/2618484", verbose_level=2)
    print("PYTEST TESTS PARSED:", tests)
    
    # Verify that Ruff linter failure is detected
    assert any("check_style_ruff  ➔  enterprise/ai/models/ai_session.py:10:54  ➔  [F401] `odoo.exceptions.ValidationError` imported but unused" in t for t in tests)
    
    # Verify that the traceback exception fallback (Rule E) correctly captures the unhandled ValueError in post install tests
    assert any("start_post_install_tests  ➔  ValueError: Model 'uninstalled.purchase.order' is not found in the Odoo registry." in t for t in tests)

def test_runbot_client_verbosity_levels(monkeypatch):
    from odoo_wt.runbot_client import fetch_failing_tests_from_batch
    
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "/build/456" in url and "static" not in url:
            mock_build = (
                '<a href="http://runbot321.odoo.com/runbot/static/build/456-master/logs/start_post_install_tests.txt">Logs</a>'
            )
            return MockResponse(mock_build)
        elif "batch/123" in url:
            mock_batch = (
                '<div class="btn-group btn-group-ssm slot_button_group slot_link_created">\n'
                '  <span class="btn btn-danger disabled">Failed</span>\n'
                '  <a href="/runbot/batch/123/build/456" class="btn btn-default slot_name"><span>Build</span></a>\n'
                '</div>'
            )
            return MockResponse(mock_batch)
        else:
            mock_log = (
                '2026-07-01 12:00:00 ERROR: test_foo (odoo.TestFoo)\n'
                'AssertionError: Expected 1 but got 0\n'
                '2026-07-01 12:01:00 odoo.service.server.ThreadedServer: Error: odoo.addons.ai.tests.test_ai.TestFoo.test_foo - AssertionError: Expected 1 but got 0'
            )
            return MockResponse(mock_log)
            
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    # 1. Test verbose_level == 1 (-v) -> should return just flat test names, NO tracebacks
    tests_v1 = fetch_failing_tests_from_batch("https://runbot.odoo.com/runbot/batch/123", verbose_level=1)
    assert "TestFoo.test_foo" in tests_v1
    assert "TestFoo.test_foo  ➔  AssertionError: Expected 1 but got 0" not in tests_v1
    
    # 2. Test verbose_level == 2 (-vv) -> should return test names WITH tracebacks
    tests_v2 = fetch_failing_tests_from_batch("https://runbot.odoo.com/runbot/batch/123", verbose_level=2)
    assert "TestFoo.test_foo  ➔  AssertionError: Expected 1 but got 0" in tests_v2

def test_real_runbot_batch_2620761_inline_warning(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status, fetch_failing_tests_from_batch
    import os
    
    warning_build_path = "tests/fixtures/build_116293286_warning.html"
    with open(warning_build_path, "r", encoding="utf-8") as f:
        warning_build_html = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch/2620761/build/116293286" in url or "build/116293286" in url:
            return MockResponse(warning_build_html)
        elif "batch/2620761" in url:
            mock_batch = (
                '<div class="btn-group btn-group-ssm slot_button_group slot_link_created">\n'
                '  <span class="btn btn-warning disabled">Warning</span>\n'
                '  <a href="/runbot/batch/2620761/build/116293286" class="btn btn-default slot_name"><span>Code Owner</span></a>\n'
                '</div>'
            )
            return MockResponse(mock_batch)
        else:
            return MockResponse("Successfully completed with no errors")
            
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    # Test failed tests extraction directly on warning batch
    tests = fetch_failing_tests_from_batch("https://runbot.odoo.com/runbot/batch/2620761", verbose_level=2)
    
    # Verify that the inline log warning is parsed and formatted beautifully!
    assert "code_owner  ➔  Some pr are draft, skipping: 120984" in tests

def test_real_runbot_batch_2621224_level_less_inline_error(monkeypatch):
    from odoo_wt.runbot_client import query_branch_status, fetch_failing_tests_from_batch
    import os
    
    build_path = "tests/fixtures/build_116302920_parent.html"
    with open(build_path, "r", encoding="utf-8") as f:
        build_html = f.read()
        
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")
            
    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "batch/2621224/build/116302920" in url or "build/116302920" in url:
            return MockResponse(build_html)
        elif "batch/2621224" in url:
            mock_batch = (
                '<div class="btn-group btn-group-ssm slot_button_group slot_link_created">\n'
                '  <span class="btn btn-danger disabled">Failed</span>\n'
                '  <a href="/runbot/batch/2621224/build/116302920" class="btn btn-default slot_name"><span>Build</span></a>\n'
                '</div>'
            )
            return MockResponse(mock_batch)
        else:
            return MockResponse("Successfully completed with no errors")
            
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    
    # Test failed tests extraction directly on failed batch
    tests = fetch_failing_tests_from_batch("https://runbot.odoo.com/runbot/batch/2621224", verbose_level=2)
    
    # Verify that both level-less inline errors are parsed and HTML-tag stripped beautifully!
    assert "minimal_check  ➔  This bundle contains some pull requests but no corresponding pr was found for branch odoo-dev/odoo:master-browse_audit-pian. Did you forget to create it? If not, please delete the branch" in tests
    assert "minimal_check  ➔  Branch odoo-dev/odoo:master-browse_audit-pian has the same commit as the base and is not needed, please delete it." in tests

def test_pr_links_with_extra_bundle_row_classes(monkeypatch):
    """Runbot renders '<div class="row bundle_row border-bottom">' with the PR dropdown before the batch link."""
    from odoo_wt.runbot_client import query_branch_status

    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")

    index_html = (
        '<div class="row bundle_row border-bottom">\n'
        '  <a class="dropdown-item" href="https://github.com/odoo-dev/enterprise/tree/my-branch">tree</a>\n'
        '  <a class="dropdown-item" href="https://github.com/odoo/enterprise/pull/120248" title="View PR">PR</a>\n'
        + ' ' * 2000 +
        '  <a href="/runbot/batch/2860321" title="2026-11-02 15:46:26">Batch</a>\n'
        '</div>'
    )

    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        return MockResponse("" if "/batch/" in url else index_html)

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    res = query_branch_status("my-branch")
    assert res is not None
    assert res[0] == "https://runbot.odoo.com/runbot/batch/2860321"
    assert res[6] is None
    assert res[7] == "https://github.com/odoo/enterprise/pull/120248"


_TILE_SEARCH_HTML = '''
<div class="row bundle_row border-bottom">
  <a class="dropdown-item" href="https://github.com/odoo/enterprise/pull/120248">PR</a>
  <div class="batch_tile">
    <div class="card border-danger">
      <a class="card-header" href="/runbot/batch/2860419" title="2026-11-02 16:19:55">38 minutes ago</a>
      <div class="card-body"><div class="batch_slots">
        <div class="slot_container">
          <div class="input-group input-group-ssm slot_button_group slot_link_matched">
            <span class="input-group-text text-bg-success border-success"><i class="fa fa-check fa-fw"></i></span>
            <a href="/runbot/batch/2860419/build/131029638" class="btn btn-default slot_name"><span>Enterprise Run</span></a>
            <build-options-dropdown data-id="131029638" data-global_result="ok" data-global_state="running" data-host="runbot255.odoo.com" data-dest="131029638-master" data-log_list="[&#34;install_run&#34;, &#34;run&#34;]"></build-options-dropdown>
          </div>
        </div>
        <div class="slot_container">
          <div class="input-group input-group-ssm slot_button_group slot_link_created">
            <span class="input-group-text text-bg-danger border-danger"><i class="fa fa-times fa-fw"></i></span>
            <a href="/runbot/batch/2860419/build/131032320" class="btn btn-default slot_name"><span>Check Style</span></a>
            <build-options-dropdown data-id="131032320" data-global_result="ko" data-global_state="done" data-host="runbot354.odoo.com" data-dest="131032320-master" data-log_list="[&#34;check_style_ruff&#34;]"></build-options-dropdown>
          </div>
        </div>
        <div class="slot_container">
          <div class="input-group input-group-ssm slot_button_group slot_link_created">
            <a href="/runbot/batch/2860419/build/131032322" class="btn btn-default slot_name"><span>Code Owner</span></a>
            <build-options-dropdown data-id="131032322" data-global_result="warn" data-global_state="done" data-host="runbot293.odoo.com" data-dest="131032322-master" data-log_list="[]"></build-options-dropdown>
          </div>
        </div>
        <div class="slot_container">
          <div class="input-group input-group-ssm slot_button_group slot_link_created">
            <a href="/runbot/batch/2860419/build/131032399" class="btn btn-default slot_name"><span>Enterprise Tests</span></a>
            <build-options-dropdown data-id="131032399" data-global_result="ok" data-global_state="testing" data-host="runbot293.odoo.com" data-dest="131032399-master" data-log_list="[]"></build-options-dropdown>
          </div>
        </div>
      </div></div>
    </div>
  </div>
</div>
'''


def _mock_tile_urlopen(monkeypatch, requested):
    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self, *args):
            return self.content.encode("utf-8")

    def mock_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        requested.append(url)
        if "runbot?search=" in url:
            return MockResponse(_TILE_SEARCH_HTML)
        if url == "http://runbot354.odoo.com/runbot/static/build/131032320-master/logs/check_style_ruff.txt":
            return MockResponse("ruff check\nFound 1 error.\nexit code 1\n")
        if url.endswith("check_style_ruff-ruff-output.json"):
            return MockResponse('[{"code": "W291", "message": "Trailing whitespace", '
                                '"filename": "/data/build/enterprise/ai/models/ai_tool.py", '
                                '"location": {"row": 320, "column": 26}}]')
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    import urllib.error
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)


def test_query_branch_status_from_search_tile(monkeypatch):
    """Batch pages are behind a bot challenge (403): counts must come from the search page tile."""
    from odoo_wt.runbot_client import query_branch_status
    requested = []
    _mock_tile_urlopen(monkeypatch, requested)

    res = query_branch_status("master-browse_audit-pian")
    batch_url, ts_str, success, failed, warning, running, odoo_pr, enterprise_pr, upgrade_pr = res
    assert batch_url == "https://runbot.odoo.com/runbot/batch/2860419"
    assert ts_str == "2026-11-02 16:19:55"
    # "running" state on an ok build is a live instance (done), "testing" is still in progress
    assert (success, failed, warning, running) == (1, 1, 1, 1)
    assert enterprise_pr == "https://github.com/odoo/enterprise/pull/120248"
    assert not any("/runbot/batch/" in u for u in requested)


def test_failing_tests_from_search_tile_logs(monkeypatch):
    from odoo_wt.runbot_client import check_branch_status_and_comments
    requested = []
    _mock_tile_urlopen(monkeypatch, requested)

    res = check_branch_status_and_comments("master-browse_audit-pian", skip_comments=True, verbose_level=0)
    assert res["failing_tests"] == [
        "check_style_ruff",
        "Code Owner  ➔  warning (details on the batch page)",
    ]

    res = check_branch_status_and_comments("master-browse_audit-pian", skip_comments=True, verbose_level=2)
    assert res["failing_tests"][0] == (
        "check_style_ruff  ➔  enterprise/ai/models/ai_tool.py:320:26  ➔  [W291] Trailing whitespace"
    )
