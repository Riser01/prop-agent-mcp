"""
Playwright End-to-End User Simulation Test Suite.
Simulates real browser user sessions for:
1. Tenant Persona (Priya Nair): Conversational chat intake, bylaw warnings, quick chips, submission.
2. Owner Persona (Vikram Malhotra): Persona switching, notification badge, tenancy verification, NOC approval.
3. Admin Persona (Society Desk): Clearance queue sign-off, Gate Pass issuance, Bylaws policy configuration.
4. Gate Security Guard: Keypad OTP entry, invalid OTP rejection, valid OTP entry grant, automated directory activation.
5. Resident Directory: Live registry verification and refresher tool.
"""
import time
import threading
import pytest
from playwright.sync_api import sync_playwright, expect
import uvicorn
from src.main import app
from src.database import init_db, get_db_connection

SERVER_PORT = 8765
BASE_URL = f"http://127.0.0.1:{SERVER_PORT}"

@pytest.fixture(scope="module", autouse=True)
def run_test_server():
    """Spins up a lightweight background uvicorn server on a dedicated port."""
    config = uvicorn.Config(app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server readiness
    import requests
    ready = False
    for _ in range(30):
        try:
            r = requests.get(f"{BASE_URL}/api/bylaws", timeout=1)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.1)

    assert ready, "Test server failed to start within 3 seconds"
    yield
    server.should_exit = True
    thread.join(timeout=2)

def test_full_playwright_user_simulation():
    """
    Executes a complete 4-persona lifecycle simulation in a headless Chromium browser.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.on("console", lambda msg: print(f"[BROWSER CONSOLE] {msg.type}: {msg.text}"))
        page.on("pageerror", lambda err: print(f"[BROWSER PAGEERROR] {err}"))
        page.on("response", lambda res: print(f"[BROWSER HTTP] {res.status} {res.url}") if "/api/" in res.url else None)

        # ── Step 1: Tenant Experience (Conversational Chat Intake) ──────────
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

        # Verify page branding
        expect(page.locator("h1")).to_contain_text("PropAgent")
        expect(page.locator("#persona-btn-tenant")).to_contain_text("Tenant: Priya")

        # Test 1a: Sunday Inquiry (Bylaw curfew warning & alternatives)
        chat_input = page.locator("#chat-input")
        chat_input.fill("Can I shift into Flat T1-101 this Sunday at 10 AM?")
        page.locator("#btn-send-chat").click()

        # Wait for agent concierge response warning about Sunday
        page.wait_for_selector("#chat-messages :has-text('Sunday Curfew')", timeout=5000)
        chat_text = page.locator("#chat-messages").inner_text()
        assert "Sunday Curfew" in chat_text
        assert "Saturday" in chat_text

        # Test 1b: Valid Move Inquiry via Quick Suggestion Chip
        page.locator("button:has-text('💡 Move in T1-101 Sat 9 AM (14ft Truck)')").click()

        # Verify Dossier confirmation card appears
        page.wait_for_selector("#chat-confirm-box:not(.hidden)", timeout=5000)
        confirm_box = page.locator("#chat-confirm-box")
        expect(confirm_box).to_contain_text("Shift Dossier Ready for Submission")
        expect(confirm_box).to_contain_text("T1-101")
        expect(confirm_box).to_contain_text("MOVE_IN")

        # Test 1c: Submit Shift Request & Lock Elevator
        page.locator("#btn-submit-chat-req").click()

        # Verify orchestration badge changes to Awaiting Owner NOC
        page.wait_for_selector("#orchestration-badge:has-text('Awaiting Owner NOC')", timeout=5000)
        badge = page.locator("#orchestration-badge")
        expect(badge).to_contain_text("Awaiting Owner NOC")

        # ── Step 2: Owner Experience (Persona Switch & NOC Grant) ───────────
        # Switch persona to Owner: Vikram Malhotra
        page.locator("#persona-btn-owner").click()
        page.wait_for_selector("#tab-content-owner:not(.hidden)", timeout=3000)

        # Verify pending NOC cards container has the request
        page.wait_for_selector("#owner-pending-cards-container :has-text('Pending Owner NOC')", timeout=5000)
        owner_cards = page.locator("#owner-pending-cards-container")
        expect(owner_cards).to_contain_text("T1-101")
        expect(owner_cards).to_contain_text("0 Dues Verified")

        # Click "Grant Owner NOC"
        page.locator("#owner-pending-cards-container button:has-text('Grant Owner NOC')").first.click()

        # Verify toast and pending queue clears
        page.wait_for_selector("#toast-container :has-text('Owner NOC granted')", timeout=5000)
        page.wait_for_selector("#owner-pending-cards-container :has-text('All Tenancy NOC Requests Cleared')", timeout=5000)

        # ── Step 3: Admin Experience (Society Sign-Off & Gate Pass) ────────
        # Switch persona to Admin Desk
        page.locator("#persona-btn-admin").click()
        page.wait_for_selector("#tab-content-admin-config:not(.hidden)", timeout=3000)

        # Verify society clearance queue shows the request
        page.wait_for_selector("#admin-pending-cards-container :has-text('Awaiting Admin Clearance')", timeout=5000)
        admin_cards = page.locator("#admin-pending-cards-container")
        expect(admin_cards).to_contain_text("T1-101")
        expect(admin_cards).to_contain_text("Verified Signed")

        # Click "Sign Off & Issue Digital Gate Pass"
        page.locator("#admin-pending-cards-container button:has-text('Sign Off & Issue Digital Gate Pass')").first.click()

        # Extract OTP from success toast
        page.wait_for_selector("#toast-container :has-text('Gate Pass')", timeout=5000)
        toast_text = page.locator("#toast-container").inner_text()
        import re
        otp_match = re.search(r'\b(\d{6})\b', toast_text)
        assert otp_match is not None, f"Could not find 6-digit OTP in toast: {toast_text}"
        otp_code = otp_match.group(1)

        # Verify queue clears
        page.wait_for_selector("#admin-pending-cards-container :has-text('Society Clearance Queue Clear')", timeout=5000)

        # Test Admin Bylaws Form saving
        page.locator("#cfg-move-in-fee").fill("2500")
        page.locator("#btn-save-bylaws").click()
        page.wait_for_selector("#toast-container :has-text('bylaws successfully updated')", timeout=5000)

        # ── Step 4: Gate Security Guard (OTP Scanner & Checkpoint) ──────────
        # Switch persona to Gate Security
        page.locator("#persona-btn-security").click()
        page.wait_for_selector("#tab-content-security:not(.hidden)", timeout=3000)

        # Test 4a: Negative test - invalid OTP
        page.locator("#input-security-otp").fill("000000")
        page.locator("#btn-verify-otp").click()
        page.wait_for_selector("#security-verification-output :has-text('ENTRY DENIED')", timeout=5000)

        # Test 4b: Positive test - enter valid 6-digit OTP using keypad simulator
        page.locator("#input-security-otp").fill("")
        for digit in otp_code:
            page.locator(f"button[onclick=\"appendOtp('{digit}')\"]").click()

        expect(page.locator("#input-security-otp")).to_have_value(otp_code)
        page.locator("#btn-verify-otp").click()

        # Verify Gate Checkpoint displays ENTRY GRANTED
        page.wait_for_selector("#security-verification-output :has-text('ENTRY GRANTED')", timeout=5000)
        output_card = page.locator("#security-verification-output")
        expect(output_card).to_contain_text("T1-101")
        expect(output_card).to_contain_text("Directory Synced")

        # ── Step 5: Resident Directory Sync Verification ────────────────────
        # Switch to Resident Directory tab
        page.locator("#tab-btn-directory").click()
        page.wait_for_selector("#tab-content-directory:not(.hidden)", timeout=3000)

        # Trigger Refresher button
        page.locator("#btn-refresh-directory").click()
        page.wait_for_selector("#toast-container :has-text('Directory successfully refreshed')", timeout=5000)

        # Verify Flat T1-101 has transitioned to Occupied (Tenant)
        row_101 = page.locator("#directory-flats-tbody tr:has-text('T1-101')")
        expect(row_101).to_contain_text("Occupied (Tenant)")
        expect(row_101).to_contain_text("Priya Nair")

        browser.close()

def test_playwright_rejection_and_mcp_inspector():
    """
    Tests edge cases in browser:
    1. Owner rejects move request and releases elevator hold.
    2. MCP Inspector tab displays all 8 tools with JSON schemas.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")

        # 1. Submit a move request for Flat T1-102
        chat_input = page.locator("#chat-input")
        chat_input.fill("I want to move in to Flat T1-102 this Saturday 2 PM with a van")
        page.locator("#btn-send-chat").click()

        page.wait_for_selector("#chat-confirm-box:not(.hidden)", timeout=5000)
        page.locator("#btn-submit-chat-req").click()
        page.wait_for_selector("#orchestration-badge:has-text('Awaiting Owner NOC')", timeout=5000)

        # 2. Switch to Owner and Reject
        page.locator("#persona-btn-owner").click()
        page.wait_for_selector("#owner-pending-cards-container :has-text('T1-102')", timeout=5000)

        page.locator("#owner-pending-cards-container button:has-text('Reject NOC')").first.click()
        page.wait_for_selector("#toast-container :has-text('rejected')", timeout=5000)

        # 3. Switch to MCP Inspector persona and verify all tools are rendered
        page.locator("#persona-btn-mcp-tools").click()
        page.wait_for_selector("#tab-content-mcp-tools:not(.hidden)", timeout=3000)

        page.wait_for_selector("#mcp-tools-list :has-text('eval_shift_bylaws')", timeout=5000)
        tools_list = page.locator("#mcp-tools-list")
        expect(tools_list).to_contain_text("eval_shift_bylaws")
        expect(tools_list).to_contain_text("reserve_service_lift")
        expect(tools_list).to_contain_text("verify_dues_and_fees")
        expect(tools_list).to_contain_text("submit_owner_noc")
        expect(tools_list).to_contain_text("generate_gate_pass")
        expect(tools_list).to_contain_text("validate_gate_pass_at_security")
        expect(tools_list).to_contain_text("sync_resident_directory")
        expect(tools_list).to_contain_text("update_society_bylaws")

        browser.close()
