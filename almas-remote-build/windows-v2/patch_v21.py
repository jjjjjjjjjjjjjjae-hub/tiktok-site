from pathlib import Path

p = Path('MainForm.cs')
s = p.read_text(encoding='utf-8')

s = s.replace('Text = "Almas Remote V2";', 'Text = "Almas Remote V2.1";', 1)

old = '''        if (line.StartsWith("APP ", StringComparison.Ordinal))
        {
            foregroundPackage = line.Length > 4 ? line[4..].Trim() : "";
            Ui(() =>
            {
                appLabel.Text = "APP: " + (foregroundPackage.Length == 0 ? "—" : foregroundPackage);
                UpdateModeButtons();
            });
            return;
        }
'''
new = '''        if (line.StartsWith("APP ", StringComparison.Ordinal))
        {
            foregroundPackage = line.Length > 4 ? line[4..].Trim() : "";
            bool gameNow = profile.GamePackages.Any(p => string.Equals(p, foregroundPackage, StringComparison.OrdinalIgnoreCase));
            SendCommand(gameNow ? "ORIENT LANDSCAPE" : "ORIENT AUTO");
            Ui(() =>
            {
                appLabel.Text = "APP: " + (foregroundPackage.Length == 0 ? "—" : foregroundPackage);
                UpdateModeButtons();
                if (gameNow) SetStatus("Free Fire: landscape + touchpad camera дайын");
            });
            return;
        }
'''
if old not in s:
    raise SystemExit('APP block not found')
s = s.replace(old, new, 1)

old2 = '''    private void StopSessionInternal(bool updateUi)
    {
        wantConnected = false;
'''
new2 = '''    private void StopSessionInternal(bool updateUi)
    {
        if (controlReady) SendCommand("ORIENT AUTO");
        wantConnected = false;
'''
if old2 not in s:
    raise SystemExit('StopSessionInternal block not found')
s = s.replace(old2, new2, 1)

p.write_text(s, encoding='utf-8')
print('V2.1 patch applied')
