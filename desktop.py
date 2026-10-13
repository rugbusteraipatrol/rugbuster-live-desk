"""RugBuster Live Desk: native WebView2 window and Windows notification icon."""
import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import shutil
import sys
import threading
import json

APP_DIR = Path(os.environ['LOCALAPPDATA']) / 'RugBuster' / 'Live Desk'
APP_DIR.mkdir(parents=True, exist_ok=True)
os.environ['RUGBUSTER_DESK_DATA'] = str(APP_DIR)
logging.basicConfig(filename=str(APP_DIR/'desktop.log'),level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')

def notify_error(message):
    logging.error(message)
    ctypes.windll.user32.MessageBoxW(None,message,'RugBuster Live Desk',0x10)

class TrayController:
    def __init__(self,window,stopping):
        self.window=window
        self.stopping=stopping
        self.tray=None

    def show(self,*_):
        if not self.stopping.is_set():
            self.window.show()
            self.window.restore()

    def hide(self,*_):
        self.window.hide()

    def closing(self):
        if self.stopping.is_set():
            return True
        self.hide()
        return False

    def quit(self,*_):
        if not self.stopping.is_set():
            self.stopping.set()
            self.tray.stop()
            self.window.destroy()

def run():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CreateEventW.argtypes = [ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None,False,'Local\\RugBusterLiveDeskApp')
    existing = ctypes.get_last_error() == 183
    show_event = kernel.CreateEventW(None,False,False,'Local\\RugBusterLiveDeskShow')
    if not mutex or not show_event:
        raise OSError('Could not initialize the Windows app session.')
    if existing:
        kernel.SetEvent(show_event)
        kernel.CloseHandle(show_event)
        kernel.CloseHandle(mutex)
        return

    import pystray
    import webview
    from PIL import Image
    from http.server import ThreadingHTTPServer
    import server

    # Preserve the prototype list once; all future releases use LocalAppData.
    previous = Path(__file__).resolve().parent/'desk.sqlite3'
    if not server.DB.exists() and previous.exists() and previous != server.DB:
        shutil.copy2(previous,server.DB)
    server.init()
    try:
        httpd = ThreadingHTTPServer(('127.0.0.1',server.PORT),server.Handler)
    except OSError:
        notify_error('Port 8767 is already in use. Close the earlier Live Desk preview, then open this program again.')
        kernel.CloseHandle(show_event);kernel.CloseHandle(mutex)
        return
    threading.Thread(target=httpd.serve_forever,daemon=True).start()
    threading.Thread(target=server.price_loop,daemon=True).start()
    threading.Thread(target=server.patrol_loop,daemon=True).start()
    stopping = threading.Event()
    window = webview.create_window('RugBuster Live Desk',f'http://127.0.0.1:{server.PORT}',
                                   width=1400,height=940,min_size=(850,650),background_color='#06050c')

    controls=TrayController(window,stopping)

    def show_data(*_):
        os.startfile(str(APP_DIR))

    tray = pystray.Icon('RugBusterLiveDesk',Image.open(server.ROOT/'assets'/'shield.ico'),
                       'RugBuster Live Desk · click to open',
                       menu=pystray.Menu(
                           pystray.MenuItem('Open Live Desk',controls.show,default=True),
                           pystray.MenuItem('Hide window',controls.hide),
                           pystray.Menu.SEPARATOR,
                           pystray.MenuItem('Open data folder',show_data),
                           pystray.MenuItem('Quit RugBuster',controls.quit)))
    controls.tray=tray
    window.events.closing += controls.closing
    window.events.loaded += lambda: logging.info('Live Desk page loaded in native window')

    def show_listener():
        while not stopping.is_set():
            if kernel.WaitForSingleObject(show_event,1000) == 0:
                controls.show()

    def started():
        def tray_ready(icon):
            icon.visible=True
            logging.info('Shield tray icon registered with Windows')
        threading.Thread(target=lambda: tray.run(setup=tray_ready),daemon=True).start()
        threading.Thread(target=show_listener,daemon=True).start()
        def alert_listener():
            with server.connect() as db:
                last_id=db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
            while not stopping.wait(5):
                try:
                    with server.connect() as db:
                        rows=db.execute('SELECT id,mint,data FROM events WHERE id>? ORDER BY id',(last_id,)).fetchall()
                    if rows:
                        last_id=rows[-1][0]
                        entry=json.loads(rows[-1][2])
                        tray.notify(f"{entry['title']}: {entry['before']} → {entry['after']}\nAPI finding changed. Open Live Desk for evidence.", 'RugBuster · '+rows[-1][1][:8]+'…')
                except Exception:
                    logging.exception('Could not show patrol notification')
        threading.Thread(target=alert_listener,daemon=True).start()
        logging.info('Window and tray started')

    try:
        webview.start(started,gui='edgechromium',storage_path=str(APP_DIR/'webview'),
                      private_mode=False,debug=False,icon=str(server.ROOT/'assets'/'shield.ico'))
    finally:
        stopping.set()
        tray.stop()
        httpd.shutdown()
        kernel.CloseHandle(show_event);kernel.CloseHandle(mutex)
        logging.info('App exited')

if __name__=='__main__':
    try:
        run()
    except Exception:
        logging.exception('Desktop startup failed')
        notify_error('Live Desk could not start. Details are in '+str(APP_DIR/'desktop.log')+
                     '. The app needs Microsoft Edge WebView2 Runtime.')
