"""Development-only host smoke test on an existing isolated X11 display.
Requires python-xlib and the XTEST extension. Never interacts with a game.
"""
import hashlib,json,os,pathlib,subprocess,sys,tempfile,time
from Xlib import X,XK,display,protocol
from Xlib.ext import xtest

def snapshot(w):
    data=w.get_image(0,0,1080,700,X.ZPixmap,0xffffffff).data
    return hashlib.sha256(data).hexdigest()
def key(d,s):
    k=d.keysym_to_keycode(XK.string_to_keysym(s)); xtest.fake_input(d,X.KeyPress,k);xtest.fake_input(d,X.KeyRelease,k);d.sync();time.sleep(.25)
def click(d,x,y):
    xtest.fake_input(d,X.MotionNotify,x=x,y=y);xtest.fake_input(d,X.ButtonPress,1);xtest.fake_input(d,X.ButtonRelease,1);d.sync();time.sleep(.25)
def close(d,w):
    ev=protocol.event.ClientMessage(window=w,client_type=d.intern_atom('WM_PROTOCOLS'),data=(32,[d.intern_atom('WM_DELETE_WINDOW'),X.CurrentTime,0,0,0]));w.send_event(ev,event_mask=0);d.flush()
def launch(d,exe,path):
    p=subprocess.Popen([exe,'--settings',str(path)],env=os.environ.copy());root=d.screen().root
    for _ in range(100):
        for w in root.query_tree().children:
            if w.get_wm_name() and 'Development Host (not a game plugin)' in w.get_wm_name():
                w.set_input_focus(X.RevertToParent,X.CurrentTime);d.sync();time.sleep(.5);return p,w
        if p.poll() is not None:raise RuntimeError('host exited')
        time.sleep(.05)
    p.terminate();raise RuntimeError('window not found')
if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='nori-x11-gui-') as td:
        path=pathlib.Path(td)/'settings.json'; d=display.Display();p,w=launch(d,sys.argv[1],path)
        try:
            before=snapshot(w);key(d,'Insert');closed=snapshot(w);assert before!=closed,'Insert did not close';key(d,'Insert');assert snapshot(w)==before,'Insert did not reopen'
            click(d,50,463);assert snapshot(w)!=before,'settings navigation failed';click(d,400,177)
            saved=json.loads(path.read_text());assert saved['hotkey']=='F8',saved
            close(d,w);assert p.wait(timeout=5)==0
            p,w=launch(d,sys.argv[1],path);assert json.loads(path.read_text())['hotkey']=='F8'
            before=snapshot(w);key(d,'F8');assert snapshot(w)!=before,'restored hotkey failed';close(d,w);assert p.wait(timeout=5)==0
            print('PASS: X11 actual Insert close/open, navigation, settings click, process restart and F8 persistence')
        finally:
            if p.poll() is None:p.terminate();p.wait(timeout=5)
            d.close()
