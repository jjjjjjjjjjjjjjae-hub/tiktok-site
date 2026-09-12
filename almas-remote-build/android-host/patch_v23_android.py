from pathlib import Path

# ---- MainActivity: make ROOT button start the real uinput backend ----
p = Path('app/src/main/java/kz/almas/remote/MainActivity.java')
s = p.read_text(encoding='utf-8')
s = s.replace('ALMAS REMOTE HOST V2.2', 'ALMAS REMOTE HOST V2.3')
old = '''                if (s.root) {
                    rootStatus.setText(s.uinput ? "ROOT: ON ✅   /dev/uinput: BAR ✅" : "ROOT: ON ✅   /dev/uinput: ЖОҚ");
                    status.setText(s.uinput
                            ? "Root дайын. uinput табылды — kernel-level input backend жасауға болады."
                            : "Root дайын. Touchpad fallback жұмыс істейді; uinput жоқ болса Accessibility backend қолданылады.");
                } else {
'''
new = '''                if (s.root) {
                    boolean engine = s.uinput && RootInputBackend.start(getApplicationContext());
                    if (engine) {
                        rootStatus.setText("ROOT INPUT: ON ✅   /dev/uinput: BAR ✅");
                        status.setText("Root touchscreen engine іске қосылды. Input енді uinput арқылы жіберіледі.");
                    } else {
                        rootStatus.setText(s.uinput ? "ROOT: ON ✅   uinput engine іске қосылмады" : "ROOT: ON ✅   /dev/uinput: ЖОҚ");
                        status.setText("Root бар, бірақ uinput engine дайын емес — Accessibility fallback қолданылады.");
                    }
                } else {
'''
if old not in s:
    raise SystemExit('MainActivity root block not found')
s = s.replace(old, new, 1)
s = s.replace('ROOT тек сен Magisk-та Grant басқанда беріледі. /dev/uinput табылса, келесі input backend соны пайдалана алады.',
              'ROOT тек сен Magisk-та Grant басқанда беріледі. /dev/uinput табылса, V2.3 нақты виртуалды touchscreen іске қосады.')
p.write_text(s, encoding='utf-8')

# ---- RemoteService: root input first, Accessibility fallback; ACK-gated video ----
p = Path('app/src/main/java/kz/almas/remote/RemoteService.java')
s = p.read_text(encoding='utf-8')
s = s.replace('Almas Remote Host V2.1', 'Almas Remote Host V2.3')
s = s.replace('"AlmasRemoteV21"', '"AlmasRemoteV23"')
s = s.replace('"video-server-v21"', '"video-server-v23"')
s = s.replace('"control-server-v21"', '"control-server-v23"')
s = s.replace('"app-state-v21"', '"app-state-v23"')
s = s.replace('out.println("READY 21 " + (RemoteAccessibilityService.isReady() ? "1" : "0"));',
              'out.println("READY 23 " + (RemoteAccessibilityService.isReady() ? "1" : "0") + " " + (RootInputBackend.isReady() ? "1" : "0"));')

# Start backend if the user already granted root in this app process.
s = s.replace('''        startCapture();
        startServers();
''', '''        startCapture();
        if (RootBridge.isRootGranted() && RootBridge.isUinputAvailable()) {
            new Thread(() -> RootInputBackend.start(getApplicationContext()), "root-input-start").start();
        }
        startServers();
''', 1)

# Replace continuous video push with one-frame-in-flight ACK protocol.
start = s.index('    private void videoLoop() {')
end = s.index('    private void controlLoop() {', start)
new_video = '''    private void videoLoop() {
        try (ServerSocket server = new ServerSocket(5050)) {
            server.setReuseAddress(true);
            while (running) {
                try (Socket s = server.accept()) {
                    s.setTcpNoDelay(true);
                    s.setKeepAlive(true);
                    s.setSendBufferSize(256 * 1024);
                    BufferedReader auth = new BufferedReader(new InputStreamReader(s.getInputStream()));
                    String line = auth.readLine();
                    if (!authorized(line)) continue;
                    DataOutputStream out = new DataOutputStream(s.getOutputStream());
                    java.io.InputStream ackIn = s.getInputStream();
                    byte[] last = null;
                    long nextSend = 0L;
                    while (running && !s.isClosed()) {
                        byte[] frame = latestFrame.get();
                        if (frame == null || frame == last) {
                            Thread.sleep(4);
                            continue;
                        }
                        long now = android.os.SystemClock.uptimeMillis();
                        if (now < nextSend) {
                            Thread.sleep(Math.min(4, nextSend - now));
                            continue;
                        }
                        out.writeInt(frame.length);
                        out.write(frame);
                        out.flush();
                        last = frame;
                        nextSend = now + 40; // cap near 25 FPS; always send newest frame

                        // Never queue seconds of stale JPEGs in TCP. Only one frame may be in flight.
                        int ack = ackIn.read();
                        if (ack < 0) break;
                    }
                } catch (Exception ignored) {}
            }
        } catch (Exception ignored) {}
    }

'''
s = s[:start] + new_video + s[end:]

repls = {
'''            if (p.length == 3 && p[0].equals("TAP")) {
                RemoteAccessibilityService.tap(f(p[1]), f(p[2]));
                return;
            }
''': '''            if (p.length == 3 && p[0].equals("TAP")) {
                float x = f(p[1]), y = f(p[2]);
                if (!RootInputBackend.tap(x, y)) RemoteAccessibilityService.tap(x, y);
                return;
            }
''',
'''            if (p.length == 6 && p[0].equals("SWIPE")) {
                RemoteAccessibilityService.swipe(f(p[1]), f(p[2]), f(p[3]), f(p[4]), l(p[5]));
                return;
            }
''': '''            if (p.length == 6 && p[0].equals("SWIPE")) {
                float x1 = f(p[1]), y1 = f(p[2]), x2 = f(p[3]), y2 = f(p[4]);
                long d = l(p[5]);
                if (!RootInputBackend.swipe(x1, y1, x2, y2, d)) RemoteAccessibilityService.swipe(x1, y1, x2, y2, d);
                return;
            }
''',
'''                if (p[1].equals("DOWN") && p.length == 6) {
                    RemoteAccessibilityService.joystickDown(f(p[2]), f(p[3]), f(p[4]), f(p[5]));
                } else if (p[1].equals("MOVE") && p.length == 4) {
                    RemoteAccessibilityService.joystickMove(f(p[2]), f(p[3]));
                } else if (p[1].equals("UP")) {
                    RemoteAccessibilityService.joystickUp();
                }
''': '''                if (p[1].equals("DOWN") && p.length == 6) {
                    float cx = f(p[2]), cy = f(p[3]), tx = f(p[4]), ty = f(p[5]);
                    if (RootInputBackend.isReady()) {
                        RootInputBackend.pointerDown("joystick", cx, cy);
                        RootInputBackend.pointerMove("joystick", tx, ty);
                    } else RemoteAccessibilityService.joystickDown(cx, cy, tx, ty);
                } else if (p[1].equals("MOVE") && p.length == 4) {
                    float x = f(p[2]), y = f(p[3]);
                    if (!RootInputBackend.pointerMove("joystick", x, y)) RemoteAccessibilityService.joystickMove(x, y);
                } else if (p[1].equals("UP")) {
                    if (!RootInputBackend.pointerUp("joystick")) RemoteAccessibilityService.joystickUp();
                }
''',
'''                if (p[1].equals("DOWN") && p.length == 4) {
                    RemoteAccessibilityService.directDown(f(p[2]), f(p[3]));
                } else if (p[1].equals("MOVE") && p.length == 4) {
                    RemoteAccessibilityService.directMove(f(p[2]), f(p[3]));
                } else if (p[1].equals("UP")) {
                    RemoteAccessibilityService.directUp();
                }
''': '''                if (p[1].equals("DOWN") && p.length == 4) {
                    float x = f(p[2]), y = f(p[3]);
                    if (!RootInputBackend.pointerDown("direct", x, y)) RemoteAccessibilityService.directDown(x, y);
                } else if (p[1].equals("MOVE") && p.length == 4) {
                    float x = f(p[2]), y = f(p[3]);
                    if (!RootInputBackend.pointerMove("direct", x, y)) RemoteAccessibilityService.directMove(x, y);
                } else if (p[1].equals("UP")) {
                    if (!RootInputBackend.pointerUp("direct")) RemoteAccessibilityService.directUp();
                }
''',
'''                if (p[2].equals("DOWN") && p.length == 5) {
                    RemoteAccessibilityService.holdDown(id, f(p[3]), f(p[4]));
                } else if (p[2].equals("UP")) {
                    RemoteAccessibilityService.holdUp(id);
                }
''': '''                if (p[2].equals("DOWN") && p.length == 5) {
                    float x = f(p[3]), y = f(p[4]);
                    if (!RootInputBackend.pointerDown("hold:" + id, x, y)) RemoteAccessibilityService.holdDown(id, x, y);
                } else if (p[2].equals("UP")) {
                    if (!RootInputBackend.pointerUp("hold:" + id)) RemoteAccessibilityService.holdUp(id);
                }
''',
'''            if (p.length == 5 && p[0].equals("CAM")) {
                RemoteAccessibilityService.cameraDelta(f(p[1]), f(p[2]), f(p[3]), f(p[4]));
                return;
            }
''': '''            if (p.length == 5 && p[0].equals("CAM")) {
                float x = f(p[1]), y = f(p[2]), dx = f(p[3]), dy = f(p[4]);
                if (!RootInputBackend.camera(x, y, dx, dy)) RemoteAccessibilityService.cameraDelta(x, y, dx, dy);
                return;
            }
''',
'''            if (p.length == 1 && p[0].equals("CANCEL")) {
                RemoteAccessibilityService.cancelAll();
            }
''': '''            if (p.length == 1 && p[0].equals("CANCEL")) {
                RootInputBackend.cancelAll();
                RemoteAccessibilityService.cancelAll();
            }
'''
}
for old, new in repls.items():
    if old not in s:
        raise SystemExit('RemoteService block not found: ' + old.splitlines()[0])
    s = s.replace(old, new, 1)

# Cancel root pointers wherever the old backend is cancelled on disconnect.
s = s.replace('''                    RemoteAccessibilityService.cancelAll();
                    restoreOrientationIfNeeded();
''', '''                    RootInputBackend.cancelAll();
                    RemoteAccessibilityService.cancelAll();
                    restoreOrientationIfNeeded();
''')
s = s.replace('''                } catch (Exception ignored) {
                    RemoteAccessibilityService.cancelAll();
                    restoreOrientationIfNeeded();
''', '''                } catch (Exception ignored) {
                    RootInputBackend.cancelAll();
                    RemoteAccessibilityService.cancelAll();
                    restoreOrientationIfNeeded();
''')
s = s.replace('''        RemoteAccessibilityService.cancelAll();
        restoreOrientationIfNeeded();
''', '''        RootInputBackend.cancelAll();
        RootInputBackend.stop();
        RemoteAccessibilityService.cancelAll();
        restoreOrientationIfNeeded();
''', 1)
p.write_text(s, encoding='utf-8')
print('V2.3 Android patch applied')
