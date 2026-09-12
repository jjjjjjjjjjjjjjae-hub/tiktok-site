from pathlib import Path

# Apply after patch_v281_keyboard_cursor.py.
p = Path('app/src/main/java/kz/almas/remote/RemoteAccessibilityService.java')
s = p.read_text(encoding='utf-8')

old = '''    private String remoteTextShadow = null;\n    private int remoteSelStart = -1;\n    private int remoteSelEnd = -1;\n'''
new = '''    private String remoteTextShadow = null;\n    private int remoteSelStart = -1;\n    private int remoteSelEnd = -1;\n    private long remoteWriteUptime;\n'''
if old not in s:
    raise SystemExit('shadow fields not found')
s = s.replace(old, new, 1)

old_event_part = '''                    CharSequence cs = src.getText();\n                    remoteTextShadow = cs == null ? "" : cs.toString();\n                    int a = src.getTextSelectionStart();\n                    int b = src.getTextSelectionEnd();\n                    int len = remoteTextShadow.length();\n'''
new_event_part = '''                    CharSequence cs = src.getText();\n                    String eventText = cs == null ? "" : cs.toString();\n                    int a = src.getTextSelectionStart();\n                    int b = src.getTextSelectionEnd();\n\n                    // ACTION_SET_TEXT can emit a bogus selection=0,0 immediately after our own write.\n                    // Ignore that short echo so the next laptop character uses the correct shadow cursor.\n                    if (type == AccessibilityEvent.TYPE_VIEW_TEXT_SELECTION_CHANGED &&\n                            android.os.SystemClock.uptimeMillis() - remoteWriteUptime < 180 &&\n                            remoteTextShadow != null && eventText.equals(remoteTextShadow)) {\n                        return;\n                    }\n\n                    remoteTextShadow = eventText;\n                    int len = remoteTextShadow.length();\n'''
if old_event_part not in s:
    raise SystemExit('selection event block not found')
s = s.replace(old_event_part, new_event_part, 1)

old_write = '''                remoteTextShadow = next;\n                remoteSelStart = remoteSelEnd = cursor;\n                setSelectionOnFocusedNode(cursor, cursor);\n'''
new_write = '''                remoteTextShadow = next;\n                remoteSelStart = remoteSelEnd = cursor;\n                remoteWriteUptime = android.os.SystemClock.uptimeMillis();\n                setSelectionOnFocusedNode(cursor, cursor);\n'''
if old_write not in s:
    raise SystemExit('insert shadow write block not found')
s = s.replace(old_write, new_write, 1)

old_back = '''                remoteTextShadow = next;\n                remoteSelStart = remoteSelEnd = deleteFrom;\n                setSelectionOnFocusedNode(deleteFrom, deleteFrom);\n'''
new_back = '''                remoteTextShadow = next;\n                remoteSelStart = remoteSelEnd = deleteFrom;\n                remoteWriteUptime = android.os.SystemClock.uptimeMillis();\n                setSelectionOnFocusedNode(deleteFrom, deleteFrom);\n'''
if old_back not in s:
    raise SystemExit('backspace shadow write block not found')
s = s.replace(old_back, new_back, 1)

p.write_text(s, encoding='utf-8')
print('V2.8.1 keyboard cursor guard applied')
