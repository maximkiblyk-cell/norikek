"""Linux development host smoke: Xvfb, real X11 input, actual rendered pixels; no game or credential fixture."""
import ctypes, os, pathlib, subprocess, sys, tempfile, time
from PIL import Image, ImageChops
host, xvfb, libs, out = sys.argv[1:]
env={**os.environ,'DISPLAY':':93'}
xenv={**env,'LD_LIBRARY_PATH':libs}
server=subprocess.Popen([xvfb,':93','-screen','0','1200x800x24','-ac','-nolisten','tcp'],env=xenv,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
proc=None
try:
 time.sleep(1)
 if server.poll() is not None:raise RuntimeError('Xvfb failed; display may already be in use')
 with tempfile.TemporaryDirectory() as t:
  proc=subprocess.Popen([host,'--settings',t+'/settings.json','--backend','https://localhost:44444'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  time.sleep(1)
  if proc.poll() is not None:raise RuntimeError('host failed')
  x=ctypes.CDLL('libX11.so.6');xt=ctypes.CDLL('libXtst.so.6')
  x.XOpenDisplay.restype=ctypes.c_void_p;x.XOpenDisplay.argtypes=[ctypes.c_char_p];d=x.XOpenDisplay(b':93');assert d
  x.XDefaultRootWindow.argtypes=[ctypes.c_void_p];x.XDefaultRootWindow.restype=ctypes.c_ulong;root=x.XDefaultRootWindow(d)
  x.XQueryTree.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),ctypes.POINTER(ctypes.c_uint)]
  r=ctypes.c_ulong();parent=ctypes.c_ulong();children=ctypes.POINTER(ctypes.c_ulong)();n=ctypes.c_uint();assert x.XQueryTree(d,root,ctypes.byref(r),ctypes.byref(parent),ctypes.byref(children),ctypes.byref(n)) and n.value
  x.XFetchName.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_char_p)]
  w=None
  for i in range(n.value):
   name=ctypes.c_char_p()
   if x.XFetchName(d,children[i],ctypes.byref(name)) and name.value and name.value.startswith(b'NORI'):
    w=children[i];break
  assert w,'host window not found'
  x.XSetInputFocus.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];x.XSetInputFocus(d,w,1,0)
  x.XFlush.argtypes=[ctypes.c_void_p];xt.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong];xt.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong];xt.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong];x.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong];x.XKeysymToKeycode.restype=ctypes.c_ubyte
  def capture(name):
   p=pathlib.Path(out)/name;subprocess.run(['import','-window','root',str(p)],env=env,check=True);return Image.open(p).convert('RGB')
  pathlib.Path(out).mkdir(parents=True,exist_ok=True);before=capture('dashboard.png')
  xt.XTestFakeMotionEvent(d,-1,60,10+108+6*48+20,0);xt.XTestFakeButtonEvent(d,1,1,0);xt.XTestFakeButtonEvent(d,1,0,0);x.XFlush(d);time.sleep(.7);license=capture('license.png');assert ImageChops.difference(before,license).getbbox(),'navigation did not change pixels'
  x.XSetInputFocus(d,w,1,0);x.XFlush(d);time.sleep(.2);x.XGetInputFocus.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.c_int)];focus=ctypes.c_ulong();revert=ctypes.c_int();x.XGetInputFocus(d,ctypes.byref(focus),ctypes.byref(revert));assert focus.value==w,'host did not receive focus';x.XKeycodeToKeysym.argtypes=[ctypes.c_void_p,ctypes.c_ubyte,ctypes.c_int];x.XKeycodeToKeysym.restype=ctypes.c_ulong;key=next((i for i in range(8,255) if x.XKeycodeToKeysym(d,i,0)==0xff63),0);assert key;xt.XTestFakeKeyEvent(d,key,1,0);x.XFlush(d);time.sleep(.2);xt.XTestFakeKeyEvent(d,key,0,0);x.XFlush(d);time.sleep(.5);closed=capture('closed.png');assert ImageChops.difference(license,closed).getbbox(),'Insert did not change pixels'
  xt.XTestFakeKeyEvent(d,key,1,0);xt.XTestFakeKeyEvent(d,key,0,0);x.XFlush(d);time.sleep(.5);opened=capture('reopened.png');assert ImageChops.difference(closed,opened).getbbox(),'Insert did not reopen'
  print('X11 host: License navigation and Insert close/reopen changed rendered pixels; Linux secure vault intentionally unavailable; no game/Telegram tested.')
finally:
 if proc:proc.terminate();proc.wait(timeout=5)
 server.terminate();server.wait(timeout=5)
