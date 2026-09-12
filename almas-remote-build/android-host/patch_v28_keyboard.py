from pathlib import Path
import re

# Apply after V2.3 root/video + V2.4 permission + V2.7 HQ patches.

# ---- Accessibility: editable focus detection + Unicode text editing ----
p = Path('app/src/main/java/kz/almas/remote/RemoteAccessibilityService.java')
s = p.read_text(encoding='utf-8')

s = s.replace('import android.os.Handler;\n', 'import android.os.Handler;\nimport android.os.Bundle;\n')
s = s.replace('import android.view.accessibility.AccessibilityEvent;\n',
              'import android.view.accessibility.AccessibilityEvent;\nimport android.view.accessibility.AccessibilityNodeInfo;\n')

anchor = '''    public static boolean globalRecents() {\n        RemoteAccessibilityService s = instance;\n        return s != null && s.performGlobalAction(GLOBAL_ACTION_RECENTS);\n    }\n\n'''
if anchor not in s:
    raise SystemExit('globalRecents anchor not found')

keyboard_methods = r'''    public static boolean isTextInputFocused() {
        RemoteAccessibilityService s = instance;
        if (s == null) return false;
        try {
            AccessibilityNodeInfo root = s.getRootInActiveWindow();
            if (root == null) return false;
            AccessibilityNodeInfo focus = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
            return focus != null && focus.isEditable();
        } catch (Throwable ignored) {
            return false;
        }
    }

    public static void insertText(String text) {
        RemoteAccessibilityService s = instance;
        if (s == null || s.main == null || text == null || text.isEmpty()) return;
        s.main.post(() -> s.replaceSelectionNow(text));
    }

    public static void backspaceText() {
        RemoteAccessibilityService s = instance;
        if (s == null || s.main == null) return;
        s.main.post(s::backspaceNow);
    }

    public static void enterText() {
        RemoteAccessibilityService s = instance;
        if (s == null || s.main == null) return;
        s.main.post(() -> {
            AccessibilityNodeInfo node = s.focusedEditableNode();
            if (node == null) return;
            boolean handled = false;
            try {
                if (android.os.Build.VERSION.SDK_INT >= 30) {
                    handled = node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId());
                }
            } catch (Throwable ignored) {}
            if (!handled) s.replaceSelectionNow("\n");
        });
    }

    private AccessibilityNodeInfo focusedEditableNode() {
        try {
            AccessibilityNodeInfo root = getRootInActiveWindow();
            if (root == null) return null;
            AccessibilityNodeInfo focus = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
            return focus != null && focus.isEditable() ? focus : null;
        } catch (Throwable ignored) {
            return null;
        }
    }

    private void replaceSelectionNow(String insert) {
        AccessibilityNodeInfo node = focusedEditableNode();
        if (node == null) return;
        try {
            CharSequence cs = node.getText();
            String current = cs == null ? "" : cs.toString();
            int start = node.getTextSelectionStart();
            int end = node.getTextSelectionEnd();
            if (start < 0 || start > current.length()) start = current.length();
            if (end < 0 || end > current.length()) end = start;
            if (end < start) { int t = start; start = end; end = t; }

            String next = current.substring(0, start) + insert + current.substring(end);
            int cursor = start + insert.length();

            Bundle args = new Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, next);
            if (node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                Bundle sel = new Bundle();
                sel.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, cursor);
                sel.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, cursor);
                node.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, sel);
            }
        } catch (Throwable ignored) {}
    }

    private void backspaceNow() {
        AccessibilityNodeInfo node = focusedEditableNode();
        if (node == null) return;
        try {
            CharSequence cs = node.getText();
            String current = cs == null ? "" : cs.toString();
            int start = node.getTextSelectionStart();
            int end = node.getTextSelectionEnd();
            if (start < 0 || start > current.length()) start = current.length();
            if (end < 0 || end > current.length()) end = start;
            if (end < start) { int t = start; start = end; end = t; }

            int deleteFrom = start;
            if (start == end && start > 0) {
                try { deleteFrom = current.offsetByCodePoints(start, -1); }
                catch (Throwable ignored) { deleteFrom = start - 1; }
            }
            if (deleteFrom == end) return;

            String next = current.substring(0, deleteFrom) + current.substring(end);
            Bundle args = new Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, next);
            if (node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                Bundle sel = new Bundle();
                sel.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, deleteFrom);
                sel.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, deleteFrom);
                node.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, sel);
            }
        } catch (Throwable ignored) {}
    }

'''
s = s.replace(anchor, anchor + keyboard_methods, 1)
p.write_text(s, encoding='utf-8')

# ---- Accessibility config: allow reading/editing focused window content ----
p = Path('app/src/main/res/xml/accessibility_service_config.xml')
s = p.read_text(encoding='utf-8')
if 'android:canRetrieveWindowContent=' not in s:
    s = s.replace('android:canPerformGestures="true"',
                  'android:canPerformGestures="true"\n    android:canRetrieveWindowContent="true"')
p.write_text(s, encoding='utf-8')

# ---- RemoteService protocol: TEXTFOCUS, TEXT64, KEY BACKSPACE/ENTER ----
p = Path('app/src/main/java/kz/almas/remote/RemoteService.java')
s = p.read_text(encoding='utf-8')

old_state = '''                        String lastPkg = null;\n                        String lastReady = null;\n                        while (running && !s.isClosed()) {\n                            try {\n                                String pkg = RemoteAccessibilityService.getForegroundPackage();\n                                String ready = RemoteAccessibilityService.isReady() ? "1" : "0";\n'''
new_state = '''                        String lastPkg = null;\n                        String lastReady = null;\n                        String lastTextFocus = null;\n                        while (running && !s.isClosed()) {\n                            try {\n                                String pkg = RemoteAccessibilityService.getForegroundPackage();\n                                String ready = RemoteAccessibilityService.isReady() ? "1" : "0";\n                                String textFocus = RemoteAccessibilityService.isTextInputFocused() ? "1" : "0";\n'''
if old_state not in s:
    raise SystemExit('app state header not found')
s = s.replace(old_state, new_state, 1)

old_ready = '''                                    if (!ready.equals(lastReady)) {\n                                        out.println("ACCESS " + ready);\n                                        lastReady = ready;\n                                    }\n                                    if (out.checkError()) break;\n'''
new_ready = '''                                    if (!ready.equals(lastReady)) {\n                                        out.println("ACCESS " + ready);\n                                        lastReady = ready;\n                                    }\n                                    if (!textFocus.equals(lastTextFocus)) {\n                                        out.println("TEXTFOCUS " + textFocus);\n                                        lastTextFocus = textFocus;\n                                    }\n                                    if (out.checkError()) break;\n'''
if old_ready not in s:
    raise SystemExit('app state ready block not found')
s = s.replace(old_ready, new_ready, 1)

cmd_anchor = '''            String[] p = line.split("\\\\s+");\n'''
if cmd_anchor not in s:
    raise SystemExit('handleCommand split not found')
cmd_insert = r'''            if (p.length == 2 && p[0].equals("TEXT64")) {
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
s = s.replace(cmd_anchor, cmd_anchor + cmd_insert, 1)

s = s.replace('Almas Remote Host V2.7 HQ', 'Almas Remote Host V2.8 HQ Keyboard')
s = s.replace('"AlmasRemoteV27HQ"', '"AlmasRemoteV28HQ"')
s = s.replace('"video-server-v27-hq"', '"video-server-v28-hq"')
s = s.replace('"control-server-v27-hq"', '"control-server-v28-hq"')
s = s.replace('"app-state-v27-hq"', '"app-state-v28-hq"')
p.write_text(s, encoding='utf-8')

# ---- UI/version ----
p = Path('app/src/main/java/kz/almas/remote/MainActivity.java')
s = p.read_text(encoding='utf-8').replace('ALMAS REMOTE HOST V2.7 HQ', 'ALMAS REMOTE HOST V2.8 HQ KEYBOARD')
p.write_text(s, encoding='utf-8')

p = Path('app/build.gradle')
s = p.read_text(encoding='utf-8')
s = re.sub(r'versionCode\s+\d+', 'versionCode 8', s, count=1)
s = re.sub(r"versionName\s+'[^']+'", "versionName '2.8'", s, count=1)
p.write_text(s, encoding='utf-8')

print('V2.8 Android Unicode keyboard patch applied')
