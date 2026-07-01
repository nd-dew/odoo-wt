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
