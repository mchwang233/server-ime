"""Real xfce4-terminal / gedit / Firefox, with XTest and application-side observations."""
import ctypes
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from x11 import pump, wait_for, screenshot
from xinput import X
from gi.repository import Gtk, Gdk, Gio, GLib
from server_ime.ui_client import StateClient
from server_ime_product.rpc import Client

ROOT = Path(__file__).resolve().parents[2]
E = Path(os.environ['SERVER_IME_EVIDENCE'])
R = Path(os.environ['SERVER_IME_CHECK_RUNTIME'])
COMMAND = json.loads(os.environ['SERVER_IME_CHECK_COMMAND'])
results, procs, logs = [], [], []
MIXED_SUFFIX = ' v2.0 AbC123 User+Tag@Example.org https://Example.org/A?v=2 你好API2世界 nihao@example.org https://example.org/a?v=2'


def record(app, name, status='PASS', **data):
    results.append(dict(application=app, check=name, result=status, **data))
    (E/'applications.json').write_text(json.dumps(dict(employee_id='platform', session='isolated-X11-Xvnc',
        injection='XTest', observations=results), ensure_ascii=False, indent=2)+'\n')
    print(app, name, status, flush=True)


def start(argv, name, env=None):
    f = (E/(name+'.log')).open('w');logs.append(f)
    p = subprocess.Popen(COMMAND + ['exec', '--'] + argv, env=env, stdout=f, stderr=subprocess.STDOUT,
                         start_new_session=True)
    procs.append(p)
    return p


def windows():
    output=subprocess.run(['xwininfo','-root','-tree'],capture_output=True,text=True,check=True).stdout
    return [(int(w,16),name) for w,name in re.findall(r'(0x[0-9a-f]+) "([^\"]*)"',output)]


def find_window(needle, timeout=20):
    found=wait_for(lambda: next((w for w,n in windows() if needle in n),None),timeout)
    if not found: raise RuntimeError('Window unavailable: '+needle)
    return found


def main():
    assert os.environ['SERVER_IME_ISOLATED']=='1'
    x=X()
    x.x11.XRaiseWindow.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
    states=StateClient();rpc=Client()
    trace=[]
    states.subscribe(lambda state:trace.append(state))
    def focus(wid):
        x.x11.XRaiseWindow(x.display,wid)
        x.x11.XSetInputFocus(x.display,wid,2,0)
        x.x11.XSync(x.display,False);pump(.4)
    def ctrl(key):
        x.press(0xffe3,True);x.key(key);x.press(0xffe3,False);pump(.15)
    def snapshot():
        snapshots=[states.get_state(cid) for cid in states.list_contexts()]
        return next((s for s in snapshots if s['focused'] and s['enabled']),None)
    def chinese():
        snap=wait_for(snapshot,4)
        assert snap,'No focused IBus engine'
        if snap['mode']!='zh':ctrl('space')
    def candidates(app, raw='nihao'):
        chinese();x.type_text(raw)
        snap=wait_for(lambda: (s if (s:=snapshot()) and s['candidate_visible'] else None),4)
        assert snap, 'No candidates: ' + json.dumps([states.get_state(cid) for cid in states.list_contexts()],ensure_ascii=False)
        assert not snap['deterministic']
        reply=rpc.connection.call_sync('org.freedesktop.IBus.ServerIME.Panel',
            '/org/freedesktop/IBus/ServerIME/Panel','org.superpartner.ServerIME.Panel1','Geometry',
            None,None,Gio.DBusCallFlags.NONE,3000,None)
        geom=json.loads(reply.unpack()[0]);rect=snap['cursor_rect'];panel=geom['panel']
        assert geom['anchored'] and rect and panel,geom
        assert panel['x']>=0 and panel['y']>=0 and panel['x']+panel['w']<=1280 and panel['y']+panel['h']<=960,geom
        assert abs(panel['x']-rect['x'])<=panel['w'],geom
        assert abs(panel['y']-(rect['y']+rect['height']))<=panel['h']+rect['height']+8,geom
        screenshot(E/(app+'-candidates.png'))
        record(app,'preedit-candidates-position',preedit=snap['preedit'],cursor_rect=rect,geometry=geom,
               first_candidates=[c['text'] for c in snap['candidates'][:5]])
        return snap,geom
    def choose(text):
        snap=snapshot()
        index=next(i for i,c in enumerate(snap['candidates']) if c['text']==text)
        assert index < snap['page_size'], (text,index)
        x.key(str(index+1))
    def select_text(text):
        snap=snapshot()
        index=next(i for i,c in enumerate(snap['candidates']) if c['text']==text)
        # Actual key navigation can select a literal even when digits insert.
        for _ in range(index-snap['selected_index']):x.key('Down')
        x.key('space')
    def mixed(app):
        assert snapshot()['mode']=='zh'
        begin=len(trace);tokens=[]
        for raw,expected in [('v2.0','v2.0'),('AbC123','AbC123'),
                             ('User+Tag@Example.org','User+Tag@Example.org'),
                             ('https://Example.org/A?v=2','https://Example.org/A?v=2'),
                             ('nihaoAPI2shijie','你好API2世界'),
                             ('nihao@example.org','nihao@example.org'),
                             ('https://example.org/a?v=2','https://example.org/a?v=2')]:
            x.key('space');x.type_text(raw);snap=snapshot()
            assert snap['mode']=='zh' and not snap['error'],snap
            assert snap['candidates'][0]['text']==expected,snap
            tokens.append(dict(raw=raw,preedit=snap['preedit'],literal_digits=snap['literal_digits'],
                               chosen=snap['candidates'][0]))
            x.key('space')
        assert all(s['mode']=='zh' for s in trace[begin:])
        record(app,'mixed-fragment-key-states',tokens=tokens,mode='zh',mode_switches=0)
    def sentence_punctuation(app):
        """Type pinyin then punctuation directly; caller reads actual app text."""
        chinese();original=rpc.call('get')['settings'];expected=[];cases=[]
        try:
            for enabled,marks in [(True,'，。？！'),(False,',.?!')]:
                settings=rpc.call('get')['settings'];settings['punctuation']['chinese']=enabled
                rpc.call('apply',settings=settings)
                for key,mapped in zip(',.?!',marks):
                    x.type_text('nihao'+key)  # No Space/digit selection before the symbol.
                    snap=snapshot()
                    assert not snap['preedit']['visible'] and not snap['candidates'],snap
                    expected.append('你好'+mapped)
                    cases.append(dict(typed='nihao'+key,chinese_punctuation=enabled,
                                      expected='你好'+mapped,selection_keys_before_symbol=[]))
                x.key('space');expected.append(' ')
            settings=rpc.call('get')['settings'];settings['punctuation']['chinese']=True
            rpc.call('apply',settings=settings)
            for raw,highlight,symbol,output in [('nihaoma','你号码','.','你号码。'),
                                              ('nihao','尼',',','尼号，'),
                                              ('nihaov','你','?','你号v？')]:
                x.type_text(raw);snap=snapshot()
                index=next(i for i,c in enumerate(snap['candidates']) if c['text']==highlight)
                for _ in range(index):x.key('Down')
                x.key(symbol)
                assert not snapshot()['preedit']['visible'],snapshot()
                expected.append(output)
                cases.append(dict(typed=raw+symbol,highlight=highlight,expected=output,
                                  selection_keys_before_symbol=['Down']*index))
            x.type_text("xi'an!");expected.append('西安！')
            assert not snapshot()['preedit']['visible'],snapshot()
            x.key('space');expected.append(' ')
            x.type_text('ni');x.key('Num_Lock');x.key('KP_Decimal');x.key('Num_Lock')
            x.type_text('hao@example.org');x.key('Return')
            expected.append('ni.hao@example.org')
            assert not snapshot()['preedit']['visible'],snapshot()
            cases.extend([dict(typed="xi'an!",expected='西安！',selection_keys_before_symbol=[]),
                          dict(typed='ni + KP_Decimal + hao@example.org + Return',
                               expected='ni.hao@example.org',literal_escape=True)])
            record(app,'direct-pinyin-punctuation-key-states',cases=cases,
                   mode='zh',mode_switches=0,expected=''.join(expected))
            return ''.join(expected)
        finally:
            rpc.call('apply',settings=original)
    def edited_and_segmented(app):
        """Append an editing/selection exercise, using keys and actual app readback."""
        x.type_text('nihaoAPI2shijix');old=snapshot()
        x.key('BackSpace')
        assert wait_for(lambda:snapshot()['preedit']['text']=='nihaoAPI2shiji',4),snapshot()
        x.key('e')
        x.key('Home');x.key('Delete');x.key('n')
        x.key('End');x.key('Left');x.key('Right')
        assert wait_for(lambda:snapshot()['candidates'] and snapshot()['candidates'][0]['text']=='你好API2世界',4),snapshot()
        assert not states.select_candidate(old,old['candidates'][0]['id'])
        x.key('space');x.key('space')
        x.type_text('abc');x.key('Num_Lock');x.key('KP_1');x.key('Num_Lock');x.type_text('23')
        snap=snapshot()
        assert snap['preedit']['text']=='abc123',snap
        select_text('abc123');x.key('space')
        x.type_text('nihaoLinux6.1shijie');stages=[]
        for text in ['你好','Linux6.1','世界']:
            select_text(text);stages.append(snapshot()['preedit'])
        assert stages[0]['text']=='Linux6.1shijie' and stages[1]['text']=='shijie' and not stages[2]['visible'],stages
        x.key('space');x.type_text('nihaohello');select_text('你好hello')
        assert snapshot()['mode']=='zh'
        record(app,'editing-keypad-partial-and-ambiguous-selection',
               edited='nihaoAPI2shijie',stale_selection_rejected=True,
               keypad_literal='abc123',partial_stages=stages,ambiguous_choice='你好hello',mode='zh')
        return '你好API2世界 abc123 你好Linux6.1世界 你好hello'
    app_windows={}
    browser_events=[]
    httpd=None
    browser_tmp=None
    selected=set(os.environ.get('SERVER_IME_CHECK_APPS','terminal,editor,browser').split(','))
    try:
        if 'terminal' in selected and shutil.which('xfce4-terminal'):
            capture=R/'terminal-capture.py'
            capture.write_text("import sys,json\nfrom pathlib import Path\np=Path(sys.argv[1])\nprint('IME terminal input:',flush=True)\nrows=[]\nfor line in sys.stdin:\n rows.append(line.rstrip('\\n'));p.write_text(json.dumps(rows,ensure_ascii=False));print('received',flush=True)\n")
            output=R/'terminal-text.json'
            start(['xfce4-terminal','--disable-server','--hide-menubar','--title=IME-terminal',
                   '--geometry=80x20+80+120','--execute',sys.executable,str(capture),str(output)],'terminal')
            wid=find_window('IME-terminal');app_windows['terminal']=wid;focus(wid);x.click(200,150);pump(.5)
            snap,geom=candidates('terminal')
            # Real mouse selection in the product candidate window.
            row=geom['rows'][0];x.click(row['x']+row['w']//2,row['y']+row['h']//2)
            record('terminal','mouse-action-state', state=snapshot())
            mixed('terminal');x.key('Return')
            assert wait_for(lambda:output.exists(),5)
            rows=json.loads(output.read_text());assert rows[-1]=='你好'+MIXED_SUFFIX,rows
            record('terminal','mouse-selection-and-mixed-commit',received=rows,transport='terminal PTY stdin')
            expected=edited_and_segmented('terminal');x.key('Return');pump(.2)
            assert json.loads(output.read_text())[-1]==expected,json.loads(output.read_text())
            record('terminal','edited-and-segmented-actual-text',received=expected,transport='terminal PTY stdin')
            expected=sentence_punctuation('terminal');x.key('Return');pump(.2)
            actual=json.loads(output.read_text())[-1];assert actual==expected,repr(actual)
            record('terminal','direct-pinyin-punctuation-actual-text',received=actual,transport='terminal PTY stdin')
            candidates('terminal','ni')
            before=snapshot();x.key('Page_Down');after=snapshot()
            assert after['page_start']>before['page_start']
            expected=after['candidates'][after['page_start']+1]['text']
            x.key('2');x.key('Return');pump(.2)
            rows=json.loads(output.read_text());assert rows[-1]==expected,rows
            record('terminal','page-and-digit-selection',received=rows[-1],page_start=after['page_start'])
            x.type_text('ni');x.key('Escape');x.type_text('hao');choose('好');x.key('Return')
            pump(.2);assert json.loads(output.read_text())[-1]=='好'
            record('terminal','escape-cancels-without-submit')
            x.type_text('hello');x.key('Return');x.key('Return');pump(.2)
            assert json.loads(output.read_text())[-1]=='hello'
            ctrl('space');x.type_text('erase');ctrl('u');x.type_text('ok');x.key('Return');ctrl('space');pump(.2)
            assert json.loads(output.read_text())[-1]=='ok'
            record('terminal','raw-return-and-shell-ctrl-u',received=['hello','ok'])
        elif 'terminal' in selected:record('terminal','application','UNVERIFIED',reason='xfce4-terminal not installed')
        if 'editor' in selected and shutil.which('gedit'):
            document=R/'IME-editor.txt';document.write_text('')
            start(['gedit','--standalone','--new-window',str(document)],'editor')
            wid=find_window('IME-editor.txt');app_windows['editor']=wid;focus(wid)
            candidates('editor');x.key(',');mixed('editor');ctrl('s');pump(.4)
            text=document.read_text();assert text=='你好，'+MIXED_SUFFIX+'\n',repr(text)
            record('editor','direct-pinyin-punctuation-mixed-save',received=text,transport='gedit Ctrl+S file')
            x.key('Return');expected=edited_and_segmented('editor');ctrl('s');pump(.3)
            actual=document.read_text();assert actual==text+expected+'\n',repr(actual)
            text=actual
            record('editor','edited-and-segmented-actual-text',received=text,transport='gedit Ctrl+S file')
            x.key('Return');expected=sentence_punctuation('editor');ctrl('s');pump(.4)
            actual=document.read_text();assert actual==text+expected+'\n',repr(actual)
            text=actual
            (E/'editor-actual.txt').write_text(text)
            record('editor','direct-pinyin-punctuation-actual-text',received=text,transport='gedit Ctrl+S file')
            ctrl('a');ctrl('c')
            clipboard=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
            assert clipboard==text.removesuffix('\n'),repr(clipboard)
            record('editor','application-shortcuts-ctrl-a-c-s',clipboard=clipboard)
            # Clear the selection without changing its text.
            x.press(0xff57,True);x.press(0xff57,False)
            candidates('editor','ni');old=snapshot()
            focus(app_windows['terminal']);pump(.3)
            snap=snapshot();assert snap and not snap['preedit']['visible'],snap
            assert not states.select_candidate(old,old['candidates'][0]['id'])
            focus(wid);ctrl('s');pump(.2);assert document.read_text()==text
            record('editor','cross-application-focus-no-leak-stale-rejected')
            screenshot(E/'editor-final.png')
        elif 'editor' in selected:record('editor','application','UNVERIFIED',reason='gedit not installed')
        chrome=ROOT/'integration/browser-runtime/chrome-linux64/chrome'
        browser=os.environ.get('SERVER_IME_CHECK_BROWSER','chrome' if chrome.is_file() else 'firefox')
        binary=str(chrome) if browser=='chrome' else shutil.which('firefox')
        if 'browser' in selected and binary:
            page=b'''<!doctype html><meta charset="utf-8"><title>IME-browser-check</title>
<style>body{margin:70px;font:20px sans-serif}textarea,input{display:block;width:780px;font:24px sans-serif;margin:24px 0}</style>
<h1>Server IME browser input</h1><textarea id="a" rows="4" autofocus></textarea><input id="b"><input id="p" type="password">
<script>let seq=0;for(let e of document.querySelectorAll('input,textarea')){for(let type of ['keydown','keyup','beforeinput','input','compositionstart','compositionupdate','compositionend','focus','blur'])e.addEventListener(type,ev=>fetch('/event',{method:'POST',body:JSON.stringify({seq:++seq,time:performance.now(),type,id:e.id,value:e.value,data:ev.data||'',key:ev.key||'',isTrusted:ev.isTrusted,isComposing:ev.isComposing||false,inputType:ev.inputType||'',selectionStart:e.selectionStart,screen:{x:window.screenX,y:window.screenY,outerWidth:outerWidth,outerHeight:outerHeight,innerWidth:innerWidth,innerHeight:innerHeight,devicePixelRatio:devicePixelRatio},rect:(()=>{let r=e.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height}})()})}));}</script>'''
            (E/'browser-page.html').write_bytes(page)
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_GET(self):
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(page)
                def do_POST(self):
                    raw=self.rfile.read(int(self.headers['Content-Length']))
                    browser_events.append(json.loads(raw));self.send_response(204);self.end_headers()
            httpd=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            threading.Thread(target=httpd.serve_forever,daemon=True).start()
            profile=R/('profile-'+browser);profile.mkdir()
            env=os.environ.copy()
            if browser=='firefox':
                (profile/'user.js').write_text('\n'.join([
                'user_pref("browser.shell.checkDefaultBrowser", false);',
                'user_pref("browser.startup.homepage_override.mstone", "ignore");',
                'user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);',
                'user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);',
                'user_pref("browser.tabs.warnOnClose", false);']))
                env.update(MOZ_CRASHREPORTER_DISABLE='1',MOZ_ENABLE_WAYLAND='0',MOZ_DISABLE_LANGPACKS='1')
                argv=[binary,'--no-remote','--profile',str(profile),'--new-instance']
            else:
                # Chromium adds ~46 bytes for SingletonSocket. The normal
                # workspace runtime path exceeds AF_UNIX's 107-byte limit.
                # Allocate an exclusive short directory under integration/;
                # this changes neither permissions nor browser security.
                for _ in range(256):
                    candidate=ROOT/'integration'/('t'+secrets.token_hex(1))
                    try: candidate.mkdir(mode=0o700)
                    except FileExistsError: continue
                    browser_tmp=candidate
                    break
                if browser_tmp is None: raise RuntimeError('No short private browser TMPDIR available')
                env['TMPDIR']=str(browser_tmp)
                argv=[binary,'--user-data-dir='+str(profile),'--no-first-run','--no-default-browser-check',
                      '--ozone-platform=x11','--window-size=1100,850','--window-position=30,40']
            argv.append('http://127.0.0.1:'+str(httpd.server_port))
            version=subprocess.run([binary,'--version'],capture_output=True,text=True,env=env).stdout.strip()
            record('browser','launch',browser=browser,version=version,command=COMMAND+['exec','--']+argv,
                   binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
                   profile_policy='Workspace only; HOME unchanged; no sandbox disabling flags')
            browser_process=start(argv,'browser',env)
            try:
                wid=find_window('IME-browser-check',20)
            except RuntimeError:
                screenshot(E/'browser-startup-blocked.png')
                record('browser','startup','UNVERIFIED',
                    reason='Browser did not open the requested local page with the explicit workspace profile; inspect browser-startup-blocked.png and browser.log',
                    windows=windows(), profile_exists=profile.is_dir(),profile_writable=os.access(profile,os.W_OK),
                    command=argv,process_exit_code=browser_process.poll(),
                    profile_policy='Original HOME unchanged; no access to user profile')
                record('all','available-applications-completed',windows=app_windows,unverified=['browser'])
                return 0
            app_windows['browser']=wid;focus(wid);pump(1)
            # autofocus on our actual page, never directly modify a DOM value.
            assert wait_for(lambda:any(e['id']=='a' and e['type']=='focus' for e in browser_events),5)
            def value(id):
                return next((e['value'] for e in sorted(browser_events,key=lambda e:e['seq'],reverse=True)
                             if e['id']==id and e['type']=='input'),'')
            def browser_position(state, field):
                event=next(e for e in sorted(browser_events,key=lambda e:e['seq'],reverse=True) if e['id']==field)
                box,screen=event['rect'],event['screen']
                left=screen['x']+box['x']
                top=screen['y']+screen['outerHeight']-screen['innerHeight']+box['y']
                rect=state['cursor_rect']
                assert left-4<=rect['x']<=left+box['width']+4,(rect,box,screen)
                assert top-4<=rect['y']<=top+box['height']+4,(rect,box,screen)
                record('browser','caret-inside-dom-field',field=field,cursor_rect=rect,
                       dom_rect=box,browser_screen=screen,calculated_field_origin=dict(x=left,y=top))
            # Enable learning through the same product RPC used by settings. It
            # must learn an ordinary browser commit and suppress password input.
            settings=rpc.call('get')['settings']
            settings['input']['learning']=True
            applied=rpc.call('apply',settings=settings)
            assert applied['engine_config']['learning']
            learned=Path(applied['data_dir'])/'learning/words.jsonl'
            before_learning=learned.read_bytes() if learned.exists() else b''
            snap,geom=candidates('browser')
            browser_position(snap,'a')
            row=geom['rows'][0];x.click(row['x']+row['w']//2,row['y']+row['h']//2)
            assert wait_for(lambda:value('a')=='你好',4),browser_events[-5:]
            record('browser','mouse-candidate-commit',received=value('a'))
            assert wait_for(lambda:learned.exists() and learned.read_bytes()!=before_learning,4)
            record('browser','ordinary-commit-learned',learning_enabled=True,
                   words_sha256=hashlib.sha256(learned.read_bytes()).hexdigest())
            mixed('browser');pump(.3)
            assert wait_for(lambda:value('a')=='你好'+MIXED_SUFFIX,4),browser_events[-5:]
            record('browser','chinese-and-mixed-dom-input',received=value('a'),transport='DOM input events via loopback HTTP')
            x.key('Return');expected=edited_and_segmented('browser')
            expected_a='你好'+MIXED_SUFFIX+'\n'+expected
            assert wait_for(lambda:value('a')==expected_a,4),browser_events[-5:]
            record('browser','edited-and-segmented-actual-text',received=value('a'),transport='DOM input events via loopback HTTP')
            x.key('Return');expected=sentence_punctuation('browser');expected_a+='\n'+expected
            assert wait_for(lambda:value('a')==expected_a,4),browser_events[-5:]
            (E/'browser-actual.txt').write_text(value('a'))
            record('browser','direct-pinyin-punctuation-actual-text',received=value('a'),transport='DOM input events via loopback HTTP')
            old,_=candidates('browser','ni');x.key('Tab');pump(.3)
            assert wait_for(lambda:any(e['id']=='b' and e['type']=='focus' for e in browser_events),4)
            assert not states.select_candidate(old,old['candidates'][0]['id'])
            x.type_text('hao');choose('好');pump(.3)
            assert value('b')=='好' and value('a')==expected_a,browser_events[-6:]
            record('browser','tab-focus-no-preedit-leak',a=value('a'),b=value('b'),stale_selection_rejected=True)
            ctrl('a');ctrl('c');clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text()
            assert clip=='好',repr(clip)
            record('browser','application-shortcut-selection-copy',clipboard=clip)
            # Check page selection and cancellation inside a second web field.
            ctrl('a');x.key('BackSpace');pump(.1)
            before,_=candidates('browser-page','ni');browser_position(before,'b')
            x.key('Page_Down');after=snapshot()
            assert after['page_start']>before['page_start']
            expected=after['candidates'][after['page_start']+1]['text']
            x.key('2');assert wait_for(lambda:value('b')==expected,4),browser_events[-5:]
            record('browser','page-and-digit-selection',received=value('b'),page_start=after['page_start'])
            x.type_text('ni');x.key('Escape');pump(.1)
            assert value('b')==expected and not snapshot()['candidate_visible']
            x.type_text('raw');x.key('Return');pump(.2)
            assert value('b')==expected+'raw'
            record('browser','escape-and-raw-return',received=value('b'))
            # Transfer an active composition into the password field too.
            x.type_text('ni');assert snapshot()['candidate_visible']
            x.key('Tab');pump(.3)
            assert wait_for(lambda:any(e['id']=='p' and e['type']=='focus' for e in browser_events),4)
            password_trace_start=len(trace)
            password_dom_start=max(e['seq'] for e in browser_events)
            before_password=learned.read_bytes()
            x.type_text('AbC123@Example.org');pump(.2)
            assert value('p')=='AbC123@Example.org',browser_events[-8:]
            snap=snapshot()
            # Chrome suppresses IME handling in password controls while its
            # last IBus context may retain purpose=FREE_FORM. Check actual
            # events/data, without requiring a password notification it never
            # sent or claiming that the platform detected the password field.
            assert not snap or (not snap['candidates'] and not snap['preedit']['visible']),snap
            assert not any(s['candidate_visible'] or s['preedit']['visible'] for s in trace[password_trace_start:])
            assert not any(e['type'].startswith('composition') for e in browser_events if e['seq']>password_dom_start)
            assert before_password==learned.read_bytes()
            record('browser','password-direct-input-no-learning',focused_state=snap,synthetic_value=value('p'),
                   learning_enabled=True,words_unchanged=True,composition_events=0,
                   words_sha256_before=hashlib.sha256(before_password).hexdigest(),
                   words_sha256_after=hashlib.sha256(learned.read_bytes()).hexdigest(),
                   handling='Observed browser direct entry; IBus password purpose not assumed',
                   status_hint_may_remain_at_previous_field=True)
            screenshot(E/'browser-final.png')
            # Chromium reports compositionend.isTrusted=false on this build,
            # although the native key/input events are trusted. Preserve that
            # observation; do not rewrite the event or infer DOM injection.
            native_events=[e for e in browser_events if e['type']!='compositionend']
            assert all(e['isTrusted'] for e in native_events), 'Untrusted key/input/focus events'
            assert any(e['type']=='compositionend' and e['data']=='你好' for e in browser_events), browser_events
            record('browser','dom-input-and-composition',events=len(browser_events),
                   key_input_focus_events_trusted=True,
                   composition_end=[dict(data=e['data'],isTrusted=e['isTrusted']) for e in browser_events if e['type']=='compositionend'])
            (E/'browser-events.json').write_text(json.dumps(sorted(browser_events,key=lambda e:e['seq']),ensure_ascii=False,indent=2))
        elif 'browser' in selected:record('browser','application','UNVERIFIED',reason='Browser not installed')
        record('all','completed',windows=app_windows)
        return 0
    except Exception as exc:
        record('active','failure','FAIL',error=str(exc),traceback=traceback.format_exc())
        screenshot(E/'application-failure.png')
        (E/'browser-events.json').write_text(json.dumps(browser_events,ensure_ascii=False,indent=2))
        raise
    finally:
        if httpd:httpd.shutdown();httpd.server_close()
        for p in reversed(procs):
            if p.poll() is None:
                os.killpg(p.pid,signal.SIGTERM)
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=3)
        for f in logs:f.close()
        if browser_tmp:shutil.rmtree(browser_tmp)
        (E/'application-state-events.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2))
        states.close();x.close()

if __name__=='__main__':
    raise SystemExit(main())
