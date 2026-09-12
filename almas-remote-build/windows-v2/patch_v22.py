from pathlib import Path

p = Path('MainForm.cs')
s = p.read_text(encoding='utf-8')

# V2.2 window title (runs after V2.1 patch).
s = s.replace('Text = "Almas Remote V2.1";', 'Text = "Almas Remote V2.2";', 1)

old_fields = '''    private bool cameraLock;
    private bool cursorHidden;
    private int rawDx;
    private int rawDy;
'''
new_fields = '''    private bool cameraLock;
    private bool cursorHidden;
    private int rawDx;
    private int rawDy;
    private long lastRawInputTick;
    private Point fallbackLastMousePos;
    private bool fallbackMousePosValid;
'''
if old_fields not in s:
    raise SystemExit('camera fields block not found')
s = s.replace(old_fields, new_fields, 1)

start = s.index('    private void VideoMouseDown(object? sender, MouseEventArgs e)')
end = s.index('    private void VideoMouseWheel(object? sender, MouseEventArgs e)', start)
new_mouse = r'''    private void VideoMouseDown(object? sender, MouseEventArgs e)
    {
        videoBox.Focus();
        if (e.Button == MouseButtons.Right)
        {
            SendCommand("GLOBAL BACK");
            return;
        }
        if (e.Button != MouseButtons.Left || !TryNorm(e.Location, out float nx, out float ny)) return;

        if (pointPickAction != null)
        {
            profile.Targets[pointPickAction] = new NormPoint(nx, ny);
            profile.Save();
            string picked = pointPickAction;
            pointPickAction = null;
            SetStatus("Нүкте сақталды: " + PointLabel(picked));
            videoBox.Invalidate();
            return;
        }

        // Never kill clicks in Camera Lock. We decide TAP vs camera-drag on MouseUp.
        pointerDown = true;
        pointerDragged = false;
        pointerDownPoint = e.Location;
        pointerLastPoint = e.Location;
        fallbackLastMousePos = e.Location;
        fallbackMousePosValid = true;

        if (!cameraLock && !GameCameraActive)
            SendCommand($"DIRECT DOWN {F(nx)} {F(ny)}");
    }

    private void VideoMouseMove(object? sender, MouseEventArgs e)
    {
        int dxPx = 0;
        int dyPx = 0;
        if (fallbackMousePosValid)
        {
            dxPx = e.X - fallbackLastMousePos.X;
            dyPx = e.Y - fallbackLastMousePos.Y;
        }
        fallbackLastMousePos = e.Location;
        fallbackMousePosValid = true;

        if (pointerDown)
        {
            int totalDx = e.X - pointerDownPoint.X;
            int totalDy = e.Y - pointerDownPoint.Y;
            if (Math.Abs(totalDx) + Math.Abs(totalDy) > 6) pointerDragged = true;
        }

        if (cameraLock)
        {
            // Synaptics PS/2 fallback: if Raw Input has not produced movement recently,
            // standard WinForms MouseMove drives the camera instead.
            bool rawAlive = Environment.TickCount64 - lastRawInputTick <= 120;
            if (pointerDown && !pointerDragged) return; // preserve a clean tap
            if (!rawAlive && (dxPx != 0 || dyPx != 0))
            {
                Rectangle vr = GetImageRect();
                if (vr.Width > 10 && vr.Height > 10)
                {
                    NormPoint cam = profile.Target("camera");
                    float dx = Math.Clamp(dxPx / (float)vr.Width * profile.TouchpadCameraSensitivity, -0.12f, 0.12f);
                    float dy = Math.Clamp(dyPx / (float)vr.Height * profile.TouchpadCameraSensitivity, -0.12f, 0.12f);
                    if (Math.Abs(dx) > 0.0001f || Math.Abs(dy) > 0.0001f)
                    {
                        SendCommand($"CAM {F(cam.X)} {F(cam.Y)} {F(dx)} {F(dy)}");
                        lastManualCamera = DateTime.UtcNow;
                    }
                }
            }
            return;
        }

        if (!pointerDown) return;

        if (GameCameraActive)
        {
            if (!pointerDragged) return;
            Rectangle vr = GetImageRect();
            if (vr.Width < 10 || vr.Height < 10) return;
            int gameDx = e.X - pointerLastPoint.X;
            int gameDy = e.Y - pointerLastPoint.Y;
            pointerLastPoint = e.Location;
            if (gameDx == 0 && gameDy == 0) return;
            NormPoint cam = profile.Target("camera");
            float dx = Math.Clamp(gameDx / (float)vr.Width * profile.TouchpadCameraSensitivity, -0.12f, 0.12f);
            float dy = Math.Clamp(gameDy / (float)vr.Height * profile.TouchpadCameraSensitivity, -0.12f, 0.12f);
            SendCommand($"CAM {F(cam.X)} {F(cam.Y)} {F(dx)} {F(dy)}");
            lastManualCamera = DateTime.UtcNow;
        }
        else if (TryNorm(e.Location, out float nx, out float ny))
        {
            pointerLastPoint = e.Location;
            SendCommand($"DIRECT MOVE {F(nx)} {F(ny)}");
        }
    }

    private void VideoMouseUp(object? sender, MouseEventArgs e)
    {
        if (e.Button != MouseButtons.Left || !pointerDown) return;
        pointerDown = false;

        if (cameraLock)
        {
            if (!pointerDragged && TryNorm(e.Location, out float tx, out float ty))
                SendCommand($"TAP {F(tx)} {F(ty)}");
            pointerDragged = false;
            return;
        }

        if (GameCameraActive)
        {
            if (!pointerDragged && TryNorm(e.Location, out float nx, out float ny))
                SendCommand($"TAP {F(nx)} {F(ny)}");
        }
        else
        {
            SendCommand("DIRECT UP");
        }
        pointerDragged = false;
    }

'''
s = s[:start] + new_mouse + s[end:]

old_set = '''        cameraLock = enabled;
        if (cameraLock && !cursorHidden)
        {
            Cursor.Hide();
            cursorHidden = true;
            videoBox.Focus();
            SetStatus("🎯 Camera Lock ON — touchpad қозғалысы камераны бұрады. F2 = шығу");
        }
        else if (!cameraLock && cursorHidden)
        {
            Cursor.Show();
            cursorHidden = false;
        }
'''
new_set = '''        cameraLock = enabled;
        fallbackMousePosValid = false;
        if (cameraLock && !cursorHidden)
        {
            Cursor.Hide();
            cursorHidden = true;
            videoBox.Focus();
            videoBox.Capture = true;
            SetStatus("🎯 Camera Lock ON — Raw Input + Synaptics MouseMove fallback. Click = TAP. F2 = шығу");
        }
        else if (!cameraLock && cursorHidden)
        {
            videoBox.Capture = false;
            Cursor.Show();
            cursorHidden = false;
        }
'''
if old_set not in s:
    raise SystemExit('SetCameraLock block not found')
s = s.replace(old_set, new_set, 1)

old_raw = '''                                int dx = Marshal.ReadInt32(ptr, (int)headerSize + 12);
                                int dy = Marshal.ReadInt32(ptr, (int)headerSize + 16);
                                rawDx += dx;
                                rawDy += dy;
'''
new_raw = '''                                int dx = Marshal.ReadInt32(ptr, (int)headerSize + 12);
                                int dy = Marshal.ReadInt32(ptr, (int)headerSize + 16);
                                if (dx != 0 || dy != 0)
                                {
                                    lastRawInputTick = Environment.TickCount64;
                                    rawDx += dx;
                                    rawDy += dy;
                                }
'''
if old_raw not in s:
    raise SystemExit('raw input block not found')
s = s.replace(old_raw, new_raw, 1)

p.write_text(s, encoding='utf-8')
print('V2.2 touchpad fallback patch applied')
