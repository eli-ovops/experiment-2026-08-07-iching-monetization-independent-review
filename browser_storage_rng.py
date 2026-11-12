import json
from playwright.sync_api import sync_playwright

URL='http://127.0.0.1:4174/?variant=D&style=bronze'
CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
out={}
def mark(k,v,d=None): out[k]={'ok':bool(v),'detail':d}

with sync_playwright() as p:
  b=p.chromium.launch(headless=True,executable_path=CHROME)
  c=b.new_context(viewport={'width':390,'height':844},reduced_motion='reduce')
  page=c.new_page(); page.goto(URL); page.wait_for_load_state('networkidle')
  page.locator('#question').fill('secure random six rounds')
  page.locator('[data-action="enter"]').click()
  for i in range(6):
    page.locator('[data-action="random-line"]').click()
    page.locator('[data-action="random-line"]').wait_for(state='visible')
    page.wait_for_function("document.querySelectorAll('.casting-line.is-filled').length === %d" % (i+1), timeout=5000)
  page.locator('[data-action="finish-casting"]').click()
  archive=json.loads(page.evaluate("localStorage.getItem('iching-reflection-history-v2')"))
  rec=archive['records'][0]
  mark('secure_random_six_round_saved',len(rec['lineValues'])==6 and rec['castingMethod']=='secure-random',rec['lineValues'])

  # Force legacy v1-only state and verify live migration to v2 on reload.
  legacy=json.loads(json.dumps(archive)); legacy['schemaVersion']=1; legacy.pop('kind',None); legacy['records'][0]['castingMethod']='random'
  page.evaluate("([v])=>{localStorage.clear();localStorage.setItem('iching-reflection-history-v1',v)}",[json.dumps(legacy)])
  page.reload(); page.wait_for_load_state('networkidle')
  page.locator('[data-action="open-stage"][data-value="history"]').click()
  migrated=page.evaluate("localStorage.getItem('iching-reflection-history-v2')")
  mark('v1_live_migrated',bool(migrated) and json.loads(migrated)['records'][0]['castingMethod']=='secure-random')

  # Corrupt current state; repository must isolate it and show no record.
  page.evaluate("localStorage.setItem('iching-reflection-history-v2','{broken-json')")
  page.reload(); page.wait_for_load_state('networkidle')
  page.locator('[data-action="open-stage"][data-value="history"]').click()
  q=page.evaluate("localStorage.getItem('iching-reflection-history-quarantine-v1')")
  mark('bad_data_quarantined',bool(q) and page.locator('.history-card').count()==0, q[:160] if q else None)
  c.close(); b.close()
print(json.dumps(out,ensure_ascii=False,indent=2))
if not all(x['ok'] for x in out.values()): raise SystemExit(2)
