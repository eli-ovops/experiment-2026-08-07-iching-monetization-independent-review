import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4174/?variant=D&style=bronze"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
results = {}

def check(name, value, detail=None):
    results[name] = {"ok": bool(value), "detail": detail}

def overflow(page):
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")

def min_targets(page):
    return page.evaluate("""[...document.querySelectorAll('button, [role=button], input')].filter(e => {
      const r=e.getBoundingClientRect(); return r.width>0 && r.height>0 && (r.width<44 || r.height<44)
    }).map(e => ({text:(e.innerText||e.getAttribute('aria-label')||e.id).slice(0,40),w:e.getBoundingClientRect().width,h:e.getBoundingClientRect().height}))""")

def cast_manual(page, question):
    page.locator('#question').fill(question)
    page.locator('[data-action="enter"]').click()
    page.locator('[data-action="set-casting-mode"][data-value="manual"]').click()
    for _ in range(6):
        for i in range(3):
            page.locator(f'[data-action="toggle-coin"][data-index="{i}"]').click()
        page.locator('[data-action="record-line"]').click()
    page.locator('[data-action="finish-casting"]').click()
    page.wait_for_timeout(150)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=CHROME)
    context = browser.new_context(viewport={"width":390,"height":844}, reduced_motion="reduce", accept_downloads=True)
    page = context.new_page()
    console_errors=[]; page_errors=[]; requests=[]
    page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: page_errors.append(str(e)))
    page.on('request', lambda r: requests.append(r.url))
    page.goto(BASE); page.wait_for_load_state('networkidle')
    check('bronze_style', page.locator('body').get_attribute('data-style') == 'bronze')
    check('opening_no_overflow_390', overflow(page) <= 0, overflow(page))
    check('no_profile_ui', page.locator('text=个人底色').count() == 0 and page.locator('text=Personal profile').count() == 0)
    check('no_vendor_request', not any('/vendor/' in u for u in requests), [u for u in requests if '/vendor/' in u])
    vendor_status=page.evaluate("fetch('/vendor/lunar.js').then(r=>r.status)")
    check('server_vendor_rejected', vendor_status == 404, vendor_status)
    duration=page.evaluate("getComputedStyle(document.querySelector('.opening')).animationDuration")
    check('reduced_motion', duration in ('0.01ms','0s','1e-05s'), duration)
    check('targets_opening_44', len(min_targets(page)) == 0, min_targets(page)[:10])

    # 64 map -> detail -> back
    page.locator('[data-action="open-stage"][data-value="learning"]').click()
    page.locator('[data-action="open-learning-entry"]').first.wait_for()
    check('map_64', page.locator('[data-action="open-learning-entry"]').count() == 64, page.locator('[data-action="open-learning-entry"]').count())
    check('targets_map_44', len(min_targets(page)) == 0, min_targets(page)[:10])
    page.locator('[data-action="open-learning-entry"][data-value="64"]').click()
    check('map_detail_64', '64 / 64' in page.locator('main, #app').inner_text())
    page.locator('[data-action="close-learning-entry"]').click()
    check('map_return_64', page.locator('[data-action="open-learning-entry"]').count() == 64)
    check('map_no_overflow_390', overflow(page) <= 0, overflow(page))

    # Complete casting and history persistence/revisit/search/export/delete.
    page.locator('[data-action="open-stage"][data-value="opening"]').click()
    page.locator('[data-action="enter"]').click()
    check('targets_casting_44', len(min_targets(page)) == 0, min_targets(page)[:10])
    page.locator('[data-action="cancel-casting"]').click()
    cast_manual(page, '复验问题 ABC')
    check('six_round_to_reading', page.locator('.reading-layers').count() == 1)
    page.reload(); page.wait_for_load_state('networkidle')
    page.locator('[data-action="open-stage"][data-value="history"]').click()
    check('history_persist_reload', page.locator('.history-card').count() >= 1, page.locator('.history-card').count())
    check('targets_history_44', len(min_targets(page)) == 0, min_targets(page)[:10])
    page.locator('.history-card').first.click()
    page.locator('#history-tags').fill('复验标签, tagX')
    page.locator('#review-note').fill('复验备注 safe')
    page.locator('[data-action="save-review"]').click()
    page.locator('[data-action="close-history-entry"]').click()
    page.locator('#history-search').fill('tagX')
    check('history_search_tag', page.locator('.history-card').count() == 1)
    page.locator('[data-action="export-history"][data-value="json"]').click()
    page.wait_for_timeout(100)
    check('export_plaintext_warning', '未加密明文' in page.locator('[role="alertdialog"]').inner_text())
    check('export_focus_cancel', page.evaluate("document.activeElement?.dataset.action") == 'cancel-export', page.evaluate("document.activeElement?.dataset.action"))
    page.keyboard.press('Escape')
    check('export_escape_closes', page.locator('[role="alertdialog"]').count() == 0, 'dialog remains' if page.locator('[role="alertdialog"]').count() else 'closed')
    # Cancel explicitly if Escape did not close.
    if page.locator('[role="alertdialog"]').count(): page.locator('[data-action="cancel-export"]').click()
    page.locator('[data-action="export-history"][data-value="json"]').click()
    with page.expect_download() as di:
        page.locator('[data-action="confirm-export"]').click()
    dl=di.value
    exported=json.loads(Path(dl.path()).read_text())
    check('export_v2_plain_json', exported.get('schemaVersion') == 2 and exported['records'][0]['question'] == '复验问题 ABC')

    # Invalid version, malicious HTML, oversized and semantically polluted records.
    def upload(obj, name='bad.json'):
        page.locator('#history-import').set_input_files([])
        page.locator('#history-import').set_input_files({"name":name,"mimeType":"application/json","buffer":json.dumps(obj).encode()})
        page.wait_for_timeout(250)
        return page.locator('#app').inner_text()
    badver=dict(exported); badver['schemaVersion']=999
    badver_text=upload(badver, 'bad-version.json')
    check('import_bad_version_rejected', '导入失败' in badver_text and '不支持的数据版本' in badver_text, badver_text[-180:])
    malicious=json.loads(json.dumps(exported)); malicious['records'][0]['id']='malicious'; malicious['records'][0]['question']='<img src=x onerror=alert(1)>'
    malicious_text=upload(malicious, 'malicious.json')
    check('import_html_rejected', '导入失败' in malicious_text and 'HTML' in malicious_text, malicious_text[-180:])
    page.locator('#history-import').set_input_files({"name":"huge.json","mimeType":"application/json","buffer":b'{' + b' '*(5*1024*1024+1) + b'}'})
    page.wait_for_timeout(100)
    check('import_oversize_rejected', '5 MB' in page.locator('#app').inner_text())
    inconsistent=json.loads(json.dumps(exported)); inconsistent['records'][0]['id']='inconsistent'; inconsistent['records'][0]['movingLines']=[99]; inconsistent['records'][0]['primary']['number']=64
    text=upload(inconsistent, 'inconsistent.json')
    check('import_semantic_pollution_rejected', '无效' in text or 'invalid' in text.lower(), text[-200:])

    # Delete original record.
    page.locator('#history-search').fill('')
    before_delete=page.locator('.history-card').count()
    page.locator('.history-card').first.click()
    page.locator('[data-action="request-delete-history"]').click(); page.locator('[data-action="confirm-delete-history"]').click()
    check('history_delete', page.locator('.history-card').count() == before_delete-1, [before_delete,page.locator('.history-card').count()])

    # English full flow and Chinese leakage outside explicitly language-tagged source text.
    page.locator('[data-action="open-stage"][data-value="opening"]').click()
    page.locator('[data-action="set-language"][data-value="en"]').click()
    cast_manual(page, 'English review question')
    leaked=page.evaluate("""[...document.querySelectorAll('#app *')].filter(e=>e.children.length===0 && /[\u3400-\u9fff]/.test(e.textContent||'') && !e.closest('[lang^=zh]')).map(e=>e.textContent.trim()).filter(Boolean)""")
    check('english_flow_no_unmarked_chinese', len(leaked) == 0, leaked[:20])
    check('english_no_overflow_390', overflow(page) <= 0, overflow(page))

    # Crypto fail closed: opening -> random mode, remove secure source, verify no line recorded and error shown.
    page.locator('[data-action="leave"]').first.click()
    page.locator('[data-action="enter"]').click()
    page.locator('[data-action="set-casting-mode"][data-value="random"]').click()
    page.evaluate("Object.defineProperty(window.crypto, 'getRandomValues', {value: undefined, configurable: true})")
    page.locator('[data-action="random-line"]').click(); page.wait_for_timeout(150)
    check('rng_fail_closed_ui', page.locator('.cast-line').count() == 0 and ('secure' in page.locator('#app').inner_text().lower() or '安全' in page.locator('#app').inner_text()), page.locator('#app').inner_text()[-300:])

    unexpected_console=[e for e in console_errors if '404 (Not Found)' not in e]
    check('console_no_errors', len(unexpected_console)==0, unexpected_console)
    check('page_no_errors', len(page_errors)==0, page_errors)
    context.close()

    # Small screen + synthetic 200% zoom layout stress.
    c2=browser.new_context(viewport={"width":320,"height":568}, reduced_motion="reduce")
    p2=c2.new_page(); p2.goto(BASE); p2.wait_for_load_state('networkidle')
    check('small_320_no_overflow', overflow(p2)<=0, overflow(p2))
    p2.locator('[data-action="open-stage"][data-value="learning"]').click()
    check('small_map_no_overflow', overflow(p2)<=0, overflow(p2))
    p2.evaluate("document.documentElement.style.zoom='2'")
    check('synthetic_200pct_no_overflow', overflow(p2)<=0, overflow(p2))
    c2.close()
    browser.close()

print(json.dumps(results, ensure_ascii=False, indent=2))
if not all(v['ok'] for v in results.values()):
    raise SystemExit(2)
