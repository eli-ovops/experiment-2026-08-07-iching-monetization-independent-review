import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:4174/?variant=D&style=bronze'
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
OUT = {}

def mark(name, ok, detail=None):
    OUT[name] = {'ok': bool(ok), 'detail': detail}

def overflow(page):
    return page.evaluate("document.documentElement.scrollWidth-document.documentElement.clientWidth")

def small_targets(page):
    return page.evaluate("""() => [...document.querySelectorAll('button,a[href],input,select,textarea')]
      .filter(e => { const r=e.getBoundingClientRect(), s=getComputedStyle(e); return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none' && !e.matches('.visually-hidden') })
      .map(e => { const r=e.getBoundingClientRect(); return {label:(e.getAttribute('aria-label')||e.innerText||e.id).trim().slice(0,60),w:+r.width.toFixed(1),h:+r.height.toFixed(1)} })
      .filter(x => x.w < 44 || x.h < 44)""")

def english_leaks(page):
    return page.evaluate("""() => { const out=[]; const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT); let n;
      while(n=w.nextNode()){ const v=n.nodeValue.trim(), p=n.parentElement; if(!v||!/[\u3400-\u9fff]/.test(v)||!p||!p.getClientRects().length) continue;
        if(p.closest('[lang^=zh]') || p.closest('[data-action=set-language][data-value=zh]')) continue; out.push(v) }
      return [...new Set(out)] }""")

def visible_stage(page):
    return page.locator('body').get_attribute('data-stage')

def open_settings(page):
    page.locator('[data-action="open-settings"]').click()
    page.locator('.settings-sheet').wait_for()

def cast_random(page, question):
    page.locator('#question').fill(question)
    page.locator('[data-action="enter"]').click()
    for count in range(1,7):
        page.locator('[data-action="random-line"]').click()
        page.wait_for_function('(n)=>document.querySelectorAll(".casting-line.is-filled").length===n', arg=count)
    page.locator('[data-action="finish-casting"]').click()
    page.locator('.complete-reading').wait_for()

def scan_layout(page, prefix):
    mark(prefix+'_overflow', overflow(page) <= 0, overflow(page))
    bad=small_targets(page); mark(prefix+'_44pt', not bad, bad[:12])

def prepare_history_fixture(page):
    archive=json.loads(page.evaluate("localStorage.getItem('iching-reflection-history-v2')"))
    base=archive['records'][0]
    now=datetime.now(timezone.utc)
    specs=[
      ('r3-old','旧问题 alpha',40,'旧标签','none'),
      ('r3-ten','十日问题 beta',10,'十日标签','scheduled'),
      ('r3-yesterday','昨日问题 gamma',1,'昨日标签','revisited'),
    ]
    for rid,q,days,tag,status in specs:
      rec=json.loads(json.dumps(base)); rec['id']=rid; rec['question']=q; rec['tags']=[tag]
      stamp=(now-timedelta(days=days)).isoformat().replace('+00:00','Z'); rec['createdAt']=stamp; rec['updatedAt']=stamp
      rec['review']={'status':status,'scheduledFor': (now.date().isoformat() if status!='none' else None), 'note':('fixture note' if status!='none' else ''), 'updatedAt':(stamp if status!='none' else None)}
      archive['records'].append(rec)
    page.evaluate("v=>localStorage.setItem('iching-reflection-history-v2',v)",json.dumps(archive,ensure_ascii=False))

def run_main(browser, language):
    context=browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce', locale='zh-CN')
    page=context.new_page(); page.set_default_timeout(12000)
    console=[]; pageerrors=[]
    page.on('console',lambda m: console.append(m.text) if m.type=='error' else None)
    page.on('pageerror',lambda e: pageerrors.append(str(e)))
    page.goto(BASE); page.wait_for_load_state('networkidle')
    prefix=language

    # Navigation and data-retention boundaries.
    mark(prefix+'_nav_three', page.locator('.foundation-nav button').count()==3, page.locator('.foundation-nav').inner_text())
    withdrawn = page.locator('[data-value="learning"],[data-value="themes"]').count()==0 and page.get_by_text('学习与主题',exact=True).count()==0
    mark(prefix+'_no_learning_theme_entry', withdrawn)
    mark(prefix+'_data_64_retained', page.evaluate("fetch('/content/iching/hexagrams.json').then(r=>r.json()).then(x=>x.hexagrams?.length||x.length)")==64)
    manifest=page.evaluate("fetch('/content/classics/library/manifest.json').then(r=>r.json())")
    mark(prefix+'_classics_retained', len(manifest.get('entries',[]))==18, len(manifest.get('entries',[])))
    mark(prefix+'_settings_only_closed', page.locator('[data-action="set-language"],[data-action="toggle-sound"],.language-switcher,.sound-toggle').count()==0)
    scan_layout(page,prefix+'_opening')
    duration=page.evaluate("getComputedStyle(document.querySelector('.opening')).animationDuration")
    mark(prefix+'_reduce_motion',duration in ('0s','0.01ms','1e-05s'),duration)

    # Settings semantics, focus loop, instant change, active-cast preservation.
    gear=page.locator('[data-action="open-settings"]')
    mark(prefix+'_gear_label',gear.get_attribute('aria-label') in ('设置','Settings'),gear.get_attribute('aria-label'))
    open_settings(page)
    mark(prefix+'_settings_first_focus',page.evaluate('document.activeElement?.dataset.action')=='close-settings',page.evaluate('document.activeElement?.dataset.action'))
    mark(prefix+'_settings_only_open',page.locator('[data-action="set-language"]').count()==2 and page.locator('[data-action="toggle-sound"]').count()==1)
    scan_layout(page,prefix+'_settings')
    page.keyboard.press('Shift+Tab')
    mark(prefix+'_settings_focus_trap',page.evaluate('document.activeElement?.dataset.action')=='toggle-sound',page.evaluate('document.activeElement?.dataset.action'))
    page.keyboard.press('Escape')
    page.wait_for_timeout(100)
    mark(prefix+'_settings_escape_focus_restore',page.locator('.settings-sheet').count()==0 and page.evaluate('document.activeElement?.dataset.action')=='open-settings',page.evaluate('document.activeElement?.dataset.action'))

    # Enter casting, record two lines, then change language without losing state.
    page.locator('#question').fill('第三轮状态保留')
    page.locator('[data-action="enter"]').click()
    for count in (1,2):
      page.locator('[data-action="random-line"]').click(); page.wait_for_function('(n)=>document.querySelectorAll(".casting-line.is-filled").length===n',arg=count)
    open_settings(page)
    page.locator(f'[data-action="set-language"][data-value="{language}"]').click()
    mark(prefix+'_language_instant',page.locator('html').get_attribute('lang')==('en' if language=='en' else 'zh-CN'),page.locator('html').get_attribute('lang'))
    mark(prefix+'_settings_does_not_reset_cast',visible_stage(page)=='casting' and page.locator('.casting-line.is-filled').count()==2,[visible_stage(page),page.locator('.casting-line.is-filled').count()])
    if language=='en': mark(prefix+'_casting_no_chinese_leak',not english_leaks(page),english_leaks(page)[:12])
    page.locator('.settings-close').click()
    # Finish remaining lines from the same casting.
    for count in range(3,7):
      page.locator('[data-action="random-line"]').click(); page.wait_for_function('(n)=>document.querySelectorAll(".casting-line.is-filled").length===n',arg=count)
    page.locator('[data-action="finish-casting"]').click(); page.locator('.complete-reading').wait_for()

    # One main vertical reading, complete by default.
    sections=page.locator('.complete-reading > .reading-section')
    mark(prefix+'_reading_sections',sections.count()>=6,sections.count())
    mark(prefix+'_no_progressive_controls',page.locator('.complete-reading [data-action="continue"],.complete-reading [data-action="previous-reading"]').count()==0)
    nested=page.evaluate("""() => [...document.querySelectorAll('.complete-reading *')].filter(e=>{const s=getComputedStyle(e);return ['auto','scroll'].includes(s.overflowY)&&e.scrollHeight>e.clientHeight+2}).map(e=>e.className||e.tagName)""")
    mark(prefix+'_no_nested_vertical_scroll',not nested,nested)
    ids=['reading-structure','reading-source','reading-moving','reading-relating','reading-prompts']
    mark(prefix+'_reading_required_sections',all(page.locator('#'+x).count()==1 for x in ids),[x for x in ids if page.locator('#'+x).count()!=1])
    mark(prefix+'_source_classics_entry',page.locator('[data-action="open-classic"][data-path*="周易.txt"]').count()==1)
    if language=='en': mark(prefix+'_reading_no_chinese_leak',not english_leaks(page),english_leaks(page)[:16])
    scan_layout(page,prefix+'_reading')
    page.locator('[data-action="open-classic"][data-path*="周易.txt"]').click(); page.wait_for_timeout(250)
    reader_ok=visible_stage(page)=='classics' and page.locator('.classic-reader').count()==1
    mark(prefix+'_classics_from_reading',reader_ok,page.locator('#app').inner_text()[-240:])
    if page.locator('[data-action="leave-classics"]').count():
      page.locator('[data-action="leave-classics"]').click()
    elif page.locator('[data-action="close-classic"]').count():
      page.locator('[data-action="close-classic"]').click(); page.locator('[data-action="leave-classics"]').click()
    mark(prefix+'_classics_returns_reading',visible_stage(page)=='reading',visible_stage(page))

    # Prepare multiple dates/tags; exercise search dimensions and preservation.
    prepare_history_fixture(page)
    page.locator('[data-action="open-stage"][data-value="history"]').click()
    page.evaluate("window.__ichingSetEntitlementLevel('lifetime')")
    page.locator('#history-search').wait_for()
    records=json.loads(page.evaluate("localStorage.getItem('iching-reflection-history-v2')"))['records']
    current=records[0]
    checks=[('question',current['question']),('name',current['primary']['name']),('number',str(current['primary']['number']))]
    for label,term in checks:
      page.locator('#history-search').fill(term); mark(prefix+'_search_'+label,page.locator('.history-card').count()>=1,[term,page.locator('.history-card').count()])
    page.locator('#history-search').fill('')
    # Add a tag/revisit to current via actual detail UI.
    page.locator('.history-card').first.click(); page.locator('#history-tags').fill('返工标签, 可逆'); page.locator('#review-note').fill('第三轮可选回看'); page.locator('[data-action="save-review"]').click(); page.locator('[data-action="close-history-entry"]').click()
    page.locator('#history-search').fill('返工标签'); mark(prefix+'_search_tag',page.locator('.history-card').count()==1,page.locator('.history-card').count())
    page.locator('[data-action="clear-history-filters"]').click()
    all_count=page.locator('.history-card').count(); group_count=page.locator('.history-group').count()
    mark(prefix+'_history_grouped',all_count==4 and group_count>=3,[all_count,group_count])
    page.locator('[data-action="set-history-period"][data-value="7d"]').click(); seven=page.locator('.history-card').count()
    page.locator('[data-action="set-history-period"][data-value="30d"]').click(); thirty=page.locator('.history-card').count()
    mark(prefix+'_time_filters',seven < thirty < all_count,[seven,thirty,all_count])
    page.locator('[data-action="clear-history-filters"]').click()
    tag_select=page.locator('#history-tag-filter'); tag_select.select_option(label='返工标签'); mark(prefix+'_tag_filter',page.locator('.history-card').count()==1,page.locator('.history-card').count())
    mark(prefix+'_result_summary',page.locator('.history-result-summary').count()==1,page.locator('.history-result-summary').inner_text())
    # Back must retain search/filter and restore prior list scroll.
    page.locator('#history-search').fill(str(current['primary']['number']))
    page.evaluate('window.scrollTo(0, document.body.scrollHeight)'); saved_scroll=page.evaluate('window.scrollY')
    page.locator('.history-card').first.click(); page.locator('[data-action="request-delete-history"]').click()
    mark(prefix+'_delete_confirmation',page.locator('[data-action="confirm-delete-history"]').count()==1)
    page.locator('[data-action="cancel-delete-history"]').click(); mark(prefix+'_delete_cancel_restore',page.locator('[data-action="request-delete-history"]').count()==1)
    page.locator('[data-action="close-history-entry"]').click(); page.wait_for_timeout(120)
    mark(prefix+'_history_query_preserved',page.locator('#history-search').input_value()==str(current['primary']['number']) and tag_select.input_value()=='返工标签',[page.locator('#history-search').input_value(),tag_select.input_value()])
    mark(prefix+'_history_scroll_restored',abs(page.evaluate('window.scrollY')-saved_scroll)<5,[saved_scroll,page.evaluate('window.scrollY')])
    scan_layout(page,prefix+'_history')
    if language=='en': mark(prefix+'_history_no_chinese_leak',not english_leaks(page),english_leaks(page)[:16])

    # Preferences must survive reload; casting was not expected to survive reload.
    open_settings(page)
    sound=page.locator('[data-action="toggle-sound"]'); sound.click(); page.wait_for_timeout(80)
    sound_state=sound.get_attribute('aria-pressed')
    page.locator('.settings-close').click(); page.reload(); page.wait_for_load_state('networkidle'); open_settings(page)
    mark(prefix+'_language_persisted',page.locator('html').get_attribute('lang')==('en' if language=='en' else 'zh-CN'))
    mark(prefix+'_sound_persisted',page.locator('[data-action="toggle-sound"]').get_attribute('aria-pressed')==sound_state,[sound_state,page.locator('[data-action="toggle-sound"]').get_attribute('aria-pressed')])
    page.locator('.settings-close').click()
    mark(prefix+'_console_clean',not console,console)
    mark(prefix+'_pageerrors_clean',not pageerrors,pageerrors)
    context.close()

def run_small(browser):
    c=browser.new_context(viewport={'width':320,'height':568},reduced_motion='reduce'); p=c.new_page(); p.goto(BASE); p.wait_for_load_state('networkidle')
    scan_layout(p,'small_opening'); open_settings(p); scan_layout(p,'small_settings'); p.locator('.settings-close').click(); cast_random(p,'小屏完整六轮'); scan_layout(p,'small_reading')
    p.locator('[data-action="open-stage"][data-value="history"]').click(); scan_layout(p,'small_history')
    mark('small_no_horizontal',overflow(p)<=0,overflow(p)); c.close()

def run_deep_routes(browser):
    for route in ('learning','themes'):
      c=browser.new_context(viewport={'width':390,'height':844}); p=c.new_page(); p.goto(BASE+'&view='+route); p.wait_for_load_state('networkidle')
      mark('deep_'+route+'_withdrawn',visible_stage(p)=='opening' and p.locator('[data-value="'+route+'"]').count()==0,visible_stage(p)); c.close()
    c=browser.new_context(viewport={'width':390,'height':844}); p=c.new_page(); p.goto(BASE+'&view=reading&step=0'); p.wait_for_load_state('networkidle')
    mark('deep_reading_single_page',p.locator('.complete-reading').count()==1 and p.locator('[data-action="continue"]').count()==0,[p.locator('.complete-reading').count(),p.locator('[data-action="continue"]').count()]); c.close()

with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path=CHROME)
    run_main(browser,'zh'); run_main(browser,'en'); run_small(browser); run_deep_routes(browser)
    browser.close()

print(json.dumps(OUT,ensure_ascii=False,indent=2))
if not all(v['ok'] for v in OUT.values()): raise SystemExit(2)
