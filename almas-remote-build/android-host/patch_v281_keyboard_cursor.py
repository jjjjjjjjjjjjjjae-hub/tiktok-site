from pathlib import Path
import re

# Apply after patch_v28_keyboard.py.
p = Path('app/src/main/java/kz/almas/remote/RemoteAccessibilityService.java')
s = p.read_text(encoding='utf-8')

old_fields = '''    private Handler main;\n    private InputEngine engine;\n'''
new_fields = '''    private Handler main;\n    private InputEngine engine;\n\n    // Some Android apps reset Accessibility text selection to 0 after ACTION_SET_TEXT.\n    // Keep a remote-side selection shadow so consecutive laptop keystrokes never prepend/reverse.\n    private String remoteTextShadow = null;\n    private int remoteSelStart = -1;\n    private int remoteSelEnd = -1;\n'''
if old_fields not in s:
    raise SystemExit('service fields anchor not found')
s = s.replace(old_fields, new_fields, 1)

old_event = '''    @Override\n    public void onAccessibilityEvent(AccessibilityEvent event) {\n        if (event == null) return;\n        CharSequence pkg = event.getPackageName();\n        if (pkg != null) foregroundPackage = pkg.toString();\n    }\n'''
new_event = '''    @Override\n    public void onAccessibilityEvent(AccessibilityEvent event) {\n        if (event == null) return;\n        CharSequence pkg = event.getPackageName();\n        if (pkg != null) foregroundPackage = pkg.toString();\n\n        int type = event.getEventType();\n        if (type == AccessibilityEvent.TYPE_VIEW_FOCUSED ||\n                type == AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED) {\n            try {\n                AccessibilityNodeInfo src = event.getSource();\n                if (src != null && src.isEditable()) {\n                    CharSequence cs = src.getText();\n                    remoteTextShadow = cs == null ? "" : cs.toString();\n                    int a = src.getTextSelectionStart();\n                    int b = src.getTextSelectionEnd();\n                    int len = remoteTextShadow.length();\n                    if (a < 0 || a > len) a = len;\n                    if (b < 0 || b > len) b = a;\n                    remoteSelStart = a;\n                    remoteSelEnd = b;\n                } else if (type == AccessibilityEvent.TYPE_VIEW_FOCUSED) {\n                    remoteTextShadow = null;\n                    remoteSelStart = remoteSelEnd = -1;\n                }\n            } catch (Throwable ignored) {}\n        }\n    }\n'''
if old_event not in s:
    raise SystemExit('onAccessibilityEvent block not found')
s = s.replace(old_event, new_event, 1)

start = s.index('    private void replaceSelectionNow(String insert) {')
end = s.index('    private void backspaceNow() {', start)
new_replace = r'''    private void replaceSelectionNow(String insert) {
        AccessibilityNodeInfo node = focusedEditableNode();
        if (node == null) return;
        try {
            CharSequence cs = node.getText();
            String current = cs == null ? "" : cs.toString();
            int start;
            int end;

            // Prefer our shadow only while the field content still matches what we last wrote/read.
            // This avoids the common ACTION_SET_TEXT bug where Android reports selection 0,0
            // after every character and would otherwise produce "olleh" from "hello".
            if (remoteTextShadow != null && current.equals(remoteTextShadow) &&
                    remoteSelStart >= 0 && remoteSelEnd >= 0 &&
                    remoteSelStart <= current.length() && remoteSelEnd <= current.length()) {
                start = remoteSelStart;
                end = remoteSelEnd;
            } else {
                start = node.getTextSelectionStart();
                end = node.getTextSelectionEnd();
                if (start < 0 || start > current.length()) start = current.length();
                if (end < 0 || end > current.length()) end = start;
            }
            if (end < start) { int t = start; start = end; end = t; }

            String next = current.substring(0, start) + insert + current.substring(end);
            int cursor = start + insert.length();

            Bundle args = new Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, next);
            if (node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) {
                // Update shadow immediately; the next network character can arrive before Android
                // has propagated a real selection-changed event.
                remoteTextShadow = next;
                remoteSelStart = remoteSelEnd = cursor;
                setSelectionOnFocusedNode(cursor, cursor);
            }
        } catch (Throwable ignored) {}
    }

    private void setSelectionOnFocusedNode(int start, int end) {
        try {
            AccessibilityNodeInfo fresh = focusedEditableNode();
            if (fresh == null) return;
            Bundle sel = new Bundle();
            sel.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, start);
            sel.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, end);
            fresh.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, sel);
        } catch (Throwable ignored) {}
    }

'''
s = s[:start] + new_replace + s[end:]

start = s.index('    private void backspaceNow() {')
end = s.index('    private static final class PointerState', start)
old_backspace_section = s[start:end]
# Keep any methods between backspace and PointerState by replacing only backspace body using brace marker.
bs_end = old_backspace_section.index('\n    }\n', old_backspace_section.index('{')) + len('\n    }\n')
rest_after_bs = old_backspace_section[bs_end:]
new_backspace = r'''    private void backspaceNow() {
        AccessibilityNodeInfo node = focusedEditableNode();
        if (node == null) return;
        try {
            CharSequence cs = node.getText();
            String current = cs == null ? "" : cs.toString();
            int start;
            int end;
            if (remoteTextShadow != null && current.equals(remoteTextShadow) &&
                    remoteSelStart >= 0 && remoteSelEnd >= 0 &&
                    remoteSelStart <= current.length() && remoteSelEnd <= current.length()) {
                start = remoteSelStart;
                end = remoteSelEnd;
            } else {
                start = node.getTextSelectionStart();
                end = node.getTextSelectionEnd();
                if (start < 0 || start > current.length()) start = current.length();
                if (end < 0 || end > current.length()) end = start;
            }
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
                remoteTextShadow = next;
                remoteSelStart = remoteSelEnd = deleteFrom;
                setSelectionOnFocusedNode(deleteFrom, deleteFrom);
            }
        } catch (Throwable ignored) {}
    }
'''
s = s[:start] + new_backspace + rest_after_bs + s[end:]

p.write_text(s, encoding='utf-8')

# Version/UI only.
p = Path('app/src/main/java/kz/almas/remote/MainActivity.java')
s = p.read_text(encoding='utf-8').replace('ALMAS REMOTE HOST V2.8 HQ KEYBOARD', 'ALMAS REMOTE HOST V2.8.1 KEYBOARD FIX')
p.write_text(s, encoding='utf-8')

p = Path('app/build.gradle')
s = p.read_text(encoding='utf-8')
s = re.sub(r'versionCode\s+\d+', 'versionCode 9', s, count=1)
s = re.sub(r"versionName\s+'[^']+'", "versionName '2.8.1'", s, count=1)
p.write_text(s, encoding='utf-8')

print('V2.8.1 keyboard cursor fix applied')
