from pathlib import Path
import re

# Apply after V2.8 / V2.8.1 keyboard patches.
root = Path('app/src/main')
java_dir = root / 'java/kz/almas/remote'
xml_dir = root / 'res/xml'
xml_dir.mkdir(parents=True, exist_ok=True)

# ---- Real Android IME backend ----
(java_dir / 'RemoteImeService.java').write_text(r'''package kz.almas.remote;

import android.inputmethodservice.InputMethodService;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;

/**
 * Real Android IME backend for laptop keyboard forwarding.
 * Text is committed through InputConnection, exactly like a normal Android keyboard.
 */
public class RemoteImeService extends InputMethodService {
    private static final String COMPONENT = "kz.almas.remote/.RemoteImeService";
    private static volatile RemoteImeService instance;
    private static String previousIme = "";
    private static boolean switchedByUs;

    private final Handler main = new Handler(Looper.getMainLooper());

    @Override
    public void onCreate() {
        super.onCreate();
        instance = this;
    }

    @Override
    public void onDestroy() {
        if (instance == this) instance = null;
        super.onDestroy();
    }

    @Override
    public boolean onEvaluateInputViewShown() {
        // No phone-side soft keyboard panel is needed while the laptop types.
        return false;
    }

    public static boolean isReady() {
        return instance != null;
    }

    public static boolean commitRemoteText(String text) {
        RemoteImeService s = instance;
        if (s == null || text == null || text.isEmpty()) return false;
        s.main.post(() -> {
            try {
                InputConnection ic = s.getCurrentInputConnection();
                if (ic != null) ic.commitText(text, 1);
            } catch (Throwable ignored) {}
        });
        return true;
    }

    public static boolean remoteBackspace() {
        RemoteImeService s = instance;
        if (s == null) return false;
        s.main.post(() -> {
            try {
                InputConnection ic = s.getCurrentInputConnection();
                if (ic == null) return;
                boolean ok = ic.deleteSurroundingTextInCodePoints(1, 0);
                if (!ok) {
                    ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_DEL));
                    ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_DEL));
                }
            } catch (Throwable ignored) {}
        });
        return true;
    }

    public static boolean remoteEnter() {
        RemoteImeService s = instance;
        if (s == null) return false;
        s.main.post(() -> {
            try {
                InputConnection ic = s.getCurrentInputConnection();
                if (ic == null) return;
                EditorInfo info = s.getCurrentInputEditorInfo();
                int action = info == null ? EditorInfo.IME_ACTION_UNSPECIFIED
                        : (info.imeOptions & EditorInfo.IME_MASK_ACTION);
                boolean handled = false;
                if (action != EditorInfo.IME_ACTION_NONE && action != EditorInfo.IME_ACTION_UNSPECIFIED) {
                    handled = ic.performEditorAction(action);
                }
                if (!handled) {
                    ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_ENTER));
                    ic.sendKeyEvent(new KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_ENTER));
                }
            } catch (Throwable ignored) {}
        });
        return true;
    }

    /** Select Almas Remote Keyboard only for an authenticated remote-control session. */
    public static synchronized boolean activateWithRoot() {
        try {
            String current = RootBridge.shellFast("settings get secure default_input_method").trim();
            if (!current.isEmpty() && !current.equals(COMPONENT) && previousIme.isEmpty()) {
                previousIme = current;
            }
            RootBridge.shellFast("ime enable " + COMPONENT + "; ime set " + COMPONENT);
            String now = RootBridge.shellFast("settings get secure default_input_method").trim();
            switchedByUs = COMPONENT.equals(now);
            return switchedByUs;
        } catch (Throwable ignored) {
            return false;
        }
    }

    /** Restore the user's normal phone keyboard when the laptop disconnects. */
    public static synchronized void restorePreviousImeWithRoot() {
        if (!switchedByUs) return;
        String prev = previousIme;
        switchedByUs = false;
        previousIme = "";
        if (prev == null || prev.isEmpty() || prev.equals(COMPONENT)) return;
        try {
            RootBridge.shellFast("ime enable " + prev + "; ime set " + prev);
        } catch (Throwable ignored) {}
    }
}
''', encoding='utf-8')

(xml_dir / 'remote_ime_method.xml').write_text(r'''<?xml version="1.0" encoding="utf-8"?>
<input-method xmlns:android="http://schemas.android.com/apk/res/android"
    android:supportsSwitchingToNextInputMethod="true" />
''', encoding='utf-8')

# ---- Manifest: register the keyboard with Android's IME framework ----
p = root / 'AndroidManifest.xml'
s = p.read_text(encoding='utf-8')
ime_service = r'''
        <service
            android:name=".RemoteImeService"
            android:label="Almas Remote Keyboard"
            android:permission="android.permission.BIND_INPUT_METHOD"
            android:exported="true">
            <intent-filter>
                <action android:name="android.view.InputMethod" />
            </intent-filter>
            <meta-data
                android:name="android.view.im"
                android:resource="@xml/remote_ime_method" />
        </service>
'''
if '.RemoteImeService' not in s:
    if '</application>' not in s:
        raise SystemExit('manifest application end not found')
    s = s.replace('    </application>', ime_service + '    </application>', 1)
p.write_text(s, encoding='utf-8')

# ---- RemoteService: activate IME for authenticated client, route text through IME ----
p = java_dir / 'RemoteService.java'
s = p.read_text(encoding='utf-8')

auth_anchor = '''                    BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream()));\n                    if (!authorized(in.readLine())) continue;\n                    PrintWriter out = new PrintWriter(s.getOutputStream(), true);\n'''
auth_new = '''                    BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream()));\n                    if (!authorized(in.readLine())) continue;\n                    boolean imeSelected = RemoteImeService.activateWithRoot();\n                    PrintWriter out = new PrintWriter(s.getOutputStream(), true);\n                    out.println("IME " + (imeSelected ? "1" : "0"));\n'''
if auth_anchor not in s:
    raise SystemExit('control auth anchor not found')
s = s.replace(auth_anchor, auth_new, 1)

old_text = r'''            if (p.length == 2 && p[0].equals("TEXT64")) {
                try {
                    byte[] raw = android.util.Base64.decode(p[1], android.util.Base64.NO_WRAP);
                    String text = new String(raw, java.nio.charset.StandardCharsets.UTF_8);
                    RemoteAccessibilityService.insertText(text);
                } catch (Throwable ignored) {}
                return;
            }
            if (p.length == 2 && p[0].equals("KEY")) {
                if (p[1].equals("BACKSPACE")) RemoteAccessibilityService.backspaceText();
                else if (p[1].equals("ENTER")) RemoteAccessibilityService.enterText();
                return;
            }
'''
new_text = r'''            if (p.length == 2 && p[0].equals("TEXT64")) {
                try {
                    byte[] raw = android.util.Base64.decode(p[1], android.util.Base64.NO_WRAP);
                    String text = new String(raw, java.nio.charset.StandardCharsets.UTF_8);
                    if (!RemoteImeService.commitRemoteText(text)) {
                        RemoteAccessibilityService.insertText(text);
                    }
                } catch (Throwable ignored) {}
                return;
            }
            if (p.length == 2 && p[0].equals("KEY")) {
                if (p[1].equals("BACKSPACE")) {
                    if (!RemoteImeService.remoteBackspace()) RemoteAccessibilityService.backspaceText();
                } else if (p[1].equals("ENTER")) {
                    if (!RemoteImeService.remoteEnter()) RemoteAccessibilityService.enterText();
                }
                return;
            }
'''
if old_text not in s:
    raise SystemExit('V2.8 text command block not found')
s = s.replace(old_text, new_text, 1)

# Restore user's old keyboard on every control disconnect path and service shutdown.
s = s.replace('''                    RootInputBackend.cancelAll();\n                    RemoteAccessibilityService.cancelAll();\n                    restoreOrientationIfNeeded();\n''',
              '''                    RemoteImeService.restorePreviousImeWithRoot();\n                    RootInputBackend.cancelAll();\n                    RemoteAccessibilityService.cancelAll();\n                    restoreOrientationIfNeeded();\n''')
s = s.replace('''                } catch (Exception ignored) {\n                    RootInputBackend.cancelAll();\n                    RemoteAccessibilityService.cancelAll();\n                    restoreOrientationIfNeeded();\n''',
              '''                } catch (Exception ignored) {\n                    RemoteImeService.restorePreviousImeWithRoot();\n                    RootInputBackend.cancelAll();\n                    RemoteAccessibilityService.cancelAll();\n                    restoreOrientationIfNeeded();\n''')

# Ensure shutdown restores keyboard too.
s = s.replace('''        RootInputBackend.cancelAll();\n        RootInputBackend.stop();\n        RemoteAccessibilityService.cancelAll();\n''',
              '''        RemoteImeService.restorePreviousImeWithRoot();\n        RootInputBackend.cancelAll();\n        RootInputBackend.stop();\n        RemoteAccessibilityService.cancelAll();\n''', 1)

s = s.replace('Almas Remote Host V2.8 HQ Keyboard', 'Almas Remote Host V2.9 IME Keyboard')
s = s.replace('"AlmasRemoteV28HQ"', '"AlmasRemoteV29IME"')
s = s.replace('"video-server-v28-hq"', '"video-server-v29-ime"')
s = s.replace('"control-server-v28-hq"', '"control-server-v29-ime"')
s = s.replace('"app-state-v28-hq"', '"app-state-v29-ime"')
p.write_text(s, encoding='utf-8')

# ---- UI/version ----
p = java_dir / 'MainActivity.java'
s = p.read_text(encoding='utf-8')
s = s.replace('ALMAS REMOTE HOST V2.8.1 KEYBOARD FIX', 'ALMAS REMOTE HOST V2.9 IME KEYBOARD')
s = s.replace('ALMAS REMOTE HOST V2.8 HQ KEYBOARD', 'ALMAS REMOTE HOST V2.9 IME KEYBOARD')
p.write_text(s, encoding='utf-8')

p = Path('app/build.gradle')
s = p.read_text(encoding='utf-8')
s = re.sub(r'versionCode\s+\d+', 'versionCode 10', s, count=1)
s = re.sub(r"versionName\s+'[^']+'", "versionName '2.9'", s, count=1)
p.write_text(s, encoding='utf-8')

print('V2.9 real IME keyboard backend applied')
