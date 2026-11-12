from playwright.sync_api import sync_playwright
import json


def small_targets(page):
    return page.evaluate("""
      () => [...document.querySelectorAll('button, input, a[href]')]
        .filter(el => {
          const r = el.getBoundingClientRect();
          return r.width > 0 && r.height > 0 && (r.width < 44 || r.height < 44);
        })
        .map(el => {
          const r = el.getBoundingClientRect();
          return {tag: el.tagName, action: el.dataset.action || '', text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 60), width: Math.round(r.width), height: Math.round(r.height)};
        })
    """)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    page = browser.new_page(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
    page.goto("http://127.0.0.1:4174/?variant=D")
    page.wait_for_load_state("networkidle")
    result = {"initialSmallTargets": small_targets(page)}
    page.locator('[data-action="enter"]').click()
    page.get_by_role("dialog").wait_for()
    result["dialogInitialFocus"] = page.evaluate("document.activeElement?.dataset?.action || document.activeElement?.getAttribute('aria-label')")
    result["dialogSmallTargets"] = small_targets(page)
    page.keyboard.press("Escape")
    result["dialogClosedByEscape"] = page.get_by_role("dialog").count() == 0
    result["focusAfterEscape"] = page.evaluate("document.activeElement?.dataset?.action || document.activeElement?.getAttribute('aria-label')")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    browser.close()
