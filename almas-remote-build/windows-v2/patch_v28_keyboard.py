from pathlib import Path

p = Path('MainForm.cs')
s = p.read_text(encoding='utf-8')

# Title after V2.3 patch.
s = s.replace('Text = "Almas Remote V2.3";', 'Text = "Almas Remote V2.8 Keyboard";', 1)

old_ready = '''    private volatile bool controlReady;\n    private volatile bool accessibilityReady;\n    private volatile string foregroundPackage = "";\n'''
new_ready = '''    private volatile bool controlReady;\n    private volatile bool accessibilityReady;\n    private volatile bool phoneTextFocus;\n    private volatile string foregroundPackage = "";\n'''
if old_ready not in s:
    raise SystemExit('ready fields not found')
s = s.replace(old_ready, new_ready, 1)

old_labels = '''    private readonly Label statusLabel = new() { AutoSize = true, Text = "Қосылмаған" };\n    private readonly Label appLabel = new() { AutoSize = true, Text = "APP: —" };\n    private readonly Label rttLabel = new() { AutoSize = true, Text = "RTT: —" };\n'''
new_labels = '''    private readonly Label statusLabel = new() { AutoSize = true, Text = "Қосылмаған" };\n    private readonly Label appLabel = new() { AutoSize = true, Text = "APP: —" };\n    private readonly Label keyboardLabel = new() { AutoSize = true, Text = "⌨ PHONE TEXT: OFF" };\n    private readonly Label rttLabel = new() { AutoSize = true, Text = "RTT: —" };\n'''
if old_labels not in s:
    raise SystemExit('labels block not found')
s = s.replace(old_labels, new_labels, 1)

# Receive Unicode KeyPress events from the Windows keyboard.
old_handlers = '''        KeyDown += MainKeyDown;\n        KeyUp += MainKeyUp;\n'''
new_handlers = '''        KeyDown += MainKeyDown;\n        KeyUp += MainKeyUp;\n        KeyPress += MainKeyPress;\n'''
if old_handlers not in s:
    raise SystemExit('key handlers block not found')
s = s.replace(old_handlers, new_handlers, 1)

# Add keyboard status to bottom bar.
old_bottom = '''        appLabel.ForeColor = Color.Gainsboro;\n        rttLabel.ForeColor = Color.Gainsboro;\n        statusFlow.Controls.Add(statusLabel);\n        statusFlow.Controls.Add(new Label { Text = "   |   ", AutoSize = true, ForeColor = Color.Gray });\n        statusFlow.Controls.Add(appLabel);\n        statusFlow.Controls.Add(new Label { Text = "   |   ", AutoSize = true, ForeColor = Color.Gray });\n        statusFlow.Controls.Add(rttLabel);\n'''
new_bottom = '''        appLabel.ForeColor = Color.Gainsboro;\n        keyboardLabel.ForeColor = Color.Gainsboro;\n        rttLabel.ForeColor = Color.Gainsboro;\n        statusFlow.Controls.Add(statusLabel);\n        statusFlow.Controls.Add(new Label { Text = "   |   ", AutoSize = true, ForeColor = Color.Gray });\n        statusFlow.Controls.Add(appLabel);\n        statusFlow.Controls.Add(new Label { Text = "   |   ", AutoSize = true, ForeColor = Color.Gray });\n        statusFlow.Controls.Add(keyboardLabel);\n        statusFlow.Controls.Add(new Label { Text = "   |   ", AutoSize = true, ForeColor = Color.Gray });\n        statusFlow.Controls.Add(rttLabel);\n'''
if old_bottom not in s:
    raise SystemExit('bottom status block not found')
s = s.replace(old_bottom, new_bottom, 1)

# Reset text-focus state on disconnect.
old_stop = '''        controlReady = false;\n        accessibilityReady = false;\n        lock (jpegLock) latestJpeg = null;\n'''
new_stop = '''        controlReady = false;\n        accessibilityReady = false;\n        phoneTextFocus = false;\n        lock (jpegLock) latestJpeg = null;\n        Ui(() => keyboardLabel.Text = "⌨ PHONE TEXT: OFF");\n'''
if old_stop not in s:
    raise SystemExit('disconnect state block not found')
s = s.replace(old_stop, new_stop, 1)

# Handle host text-focus signal.
handle_anchor = '''        if (line.StartsWith("PONG ", StringComparison.Ordinal) && long.TryParse(line[5..], out long sent))\n'''
if handle_anchor not in s:
    raise SystemExit('PONG anchor not found')
textfocus = r'''        if (line.StartsWith("TEXTFOCUS ", StringComparison.Ordinal))
        {
            phoneTextFocus = line.EndsWith("1", StringComparison.Ordinal);
            Ui(() =>
            {
                keyboardLabel.Text = phoneTextFocus ? "⌨ PHONE TEXT: ON" : "⌨ PHONE TEXT: OFF";
                keyboardLabel.ForeColor = phoneTextFocus ? Color.LightGreen : Color.Gainsboro;
                if (phoneTextFocus)
                {
                    // Text entry owns the keyboard while an Android EditText is focused.
                    pressed.Clear();
                    if (joystickIsDown)
                    {
                        SendCommand("JOY UP");
                        joystickIsDown = false;
                    }
                }
            });
            return;
        }
'''
s = s.replace(handle_anchor, textfocus + handle_anchor, 1)

# Add helper that sends arbitrary Unicode as Base64 UTF-8.
send_anchor = '''    private void MainKeyDown(object? sender, KeyEventArgs e)\n'''
if send_anchor not in s:
    raise SystemExit('MainKeyDown anchor not found')
send_method = r'''    private bool SendPhoneText(string text)
    {
        if (!controlReady || string.IsNullOrEmpty(text)) return false;
        string b64 = Convert.ToBase64String(Encoding.UTF8.GetBytes(text));
        return SendCommand("TEXT64 " + b64);
    }

'''
s = s.replace(send_anchor, send_method + send_anchor, 1)

# Give focused Android text fields priority over game key mapping.
needle = '''        if (e.Control && e.Alt && e.KeyCode == Keys.Escape)\n        {\n            SafeStopInput();\n            SetCameraLock(false);\n            e.SuppressKeyPress = true;\n            return;\n        }\n\n        if (!profile.GameInputEnabled || !controlReady || IsTextEntryActive()) return;\n'''
replacement = r'''        if (e.Control && e.Alt && e.KeyCode == Keys.Escape)
        {
            SafeStopInput();
            SetCameraLock(false);
            e.SuppressKeyPress = true;
            return;
        }

        if (phoneTextFocus && controlReady && !IsTextEntryActive())
        {
            // When the phone owns a text cursor, suspend game mappings automatically.
            if (e.Control && e.KeyCode == Keys.V)
            {
                try
                {
                    if (Clipboard.ContainsText()) SendPhoneText(Clipboard.GetText());
                }
                catch { }
                e.SuppressKeyPress = true;
                return;
            }
            if (e.KeyCode == Keys.Back)
            {
                SendCommand("KEY BACKSPACE");
                e.SuppressKeyPress = true;
                return;
            }
            if (e.KeyCode == Keys.Enter)
            {
                SendCommand("KEY ENTER");
                e.SuppressKeyPress = true;
                return;
            }
            // Printable keys are forwarded by MainKeyPress so Windows keyboard layout
            // (Kazakh/Russian/English) is preserved as Unicode.
            return;
        }

        if (!profile.GameInputEnabled || !controlReady || IsTextEntryActive()) return;
'''
if needle not in s:
    raise SystemExit('MainKeyDown priority block not found')
s = s.replace(needle, replacement, 1)

# Unicode character forwarding.
keyup_anchor = '''    private void MainKeyUp(object? sender, KeyEventArgs e)\n'''
if keyup_anchor not in s:
    raise SystemExit('MainKeyUp anchor not found')
keypress = r'''    private void MainKeyPress(object? sender, KeyPressEventArgs e)
    {
        if (!controlReady || !phoneTextFocus || IsTextEntryActive()) return;
        if (char.IsControl(e.KeyChar)) return;
        if (SendPhoneText(e.KeyChar.ToString())) e.Handled = true;
    }

'''
s = s.replace(keyup_anchor, keypress + keyup_anchor, 1)

p.write_text(s, encoding='utf-8')
print('V2.8 Windows Unicode keyboard patch applied')
