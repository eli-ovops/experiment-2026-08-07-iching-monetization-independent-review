from playwright.sync_api import sync_playwright
import json


BASE = "http://127.0.0.1:4174/?variant=D"


def snapshot(page, label):
    return {
        "label": label,
        "url": page.url,
        "lang": page.locator("html").get_attribute("lang"),
        "title": page.title(),
        "overflow": page.evaluate("document.documentElement.scrollWidth > window.innerWidth"),
        "scrollWidth": page.evaluate("document.documentElement.scrollWidth"),
        "innerWidth": page.evaluate("window.innerWidth"),
        "buttons": page.get_by_role("button").count(),
        "text": page.locator("body").inner_text()[:700],
    }


with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )
    results = []
    for width, height, language, reduced in [
        (390, 844, "zh", "no-preference"),
        (390, 844, "en", "reduce"),
        (320, 568, "zh", "reduce"),
    ]:
        context = browser.new_context(
            viewport={"width": width, "height": height},
            reduced_motion=reduced,
        )
        page = context.new_page()
        console_errors = []
        page_errors = []
        requests = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))
        page.on("request", lambda req: requests.append(req.url))
        page.goto(BASE)
        page.wait_for_load_state("networkidle")
        if language == "en":
            page.locator('[data-action="set-language"][data-value="en"]').click()
        initial = snapshot(page, f"{width}x{height}-{language}-{reduced}")

        flow = None
        if width == 390:
            page.locator('[data-action="enter"]').click()
            page.get_by_role("dialog").wait_for()
            page.locator('[data-action="set-casting-mode"][data-value="manual"]').click()
            for _ in range(6):
                for coin in page.locator('[data-action="toggle-coin"]').all():
                    coin.click()
                page.locator('[data-action="record-line"]').click()
            page.locator('[data-action="finish-casting"]').click()
            page.wait_for_timeout(250)
            flow = snapshot(page, "completed-six-line-reading")
            flow["historyControls"] = page.locator('[data-action*="history"], [data-action*="export"], [data-action*="import"]').count()
            flow["hanOutsideDeclaredChinese"] = page.evaluate("""
                () => [...document.querySelectorAll('body *')]
                  .filter(el => el.children.length === 0 && !el.closest('[lang^="zh"]') && /[\\u3400-\\u9fff]/.test(el.textContent || ''))
                  .map(el => (el.textContent || '').trim()).filter(Boolean).slice(0, 20)
            """)
            page.reload()
            page.wait_for_load_state("networkidle")
            flow["afterReloadText"] = page.locator("body").inner_text()[:400]

        results.append({
            "initial": initial,
            "flow": flow,
            "consoleErrors": console_errors,
            "pageErrors": page_errors,
            "vendorRequests": [u for u in requests if "/vendor/" in u],
        })
        context.close()
    browser.close()
    print(json.dumps(results, ensure_ascii=False, indent=2))
