using System.Buffers.Binary;
using System.Drawing.Drawing2D;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;

namespace AlmasRemoteV2;

public sealed class MainForm : Form
{
    internal static readonly string[] Actions =
    {
        "move_up", "move_down", "move_left", "move_right",
        "run", "jump", "fire", "aim", "reload", "interact"
    };

    internal static readonly Dictionary<string, string> ActionLabels = new()
    {
        ["move_up"] = "Алға",
        ["move_down"] = "Артқа",
        ["move_left"] = "Солға",
        ["move_right"] = "Оңға",
        ["run"] = "Жүгіру",
        ["jump"] = "Секіру",
        ["fire"] = "Ату",
        ["aim"] = "Прицел",
        ["reload"] = "Оқтау",
        ["interact"] = "Әрекет"
    };

    private static readonly HashSet<string> MovementActions = new()
    {
        "move_up", "move_down", "move_left", "move_right"
    };

    private RemoteProfile profile = RemoteProfile.Load();

    private readonly TextBox ipBox = new() { Width = 125, Text = "192.168.1.100" };
    private readonly TextBox pinBox = new() { Width = 78, UseSystemPasswordChar = true };
    private readonly Button connectButton = new() { Text = "Қосылу", Width = 82 };
    private readonly Button backButton = new() { Text = "← Back", Width = 70 };
    private readonly Button homeButton = new() { Text = "⌂ Home", Width = 70 };
    private readonly Button inputButton = new() { Width = 118 };
    private readonly Button cameraButton = new() { Width = 122 };
    private readonly Button settingsButton = new() { Text = "⚙ Настройка", Width = 112 };
    private readonly Label statusLabel = new() { AutoSize = true, Text = "Қосылмаған" };
    private readonly Label appLabel = new() { AutoSize = true, Text = "APP: —" };
    private readonly Label rttLabel = new() { AutoSize = true, Text = "RTT: —" };
    private readonly PictureBox videoBox = new()
    {
        Dock = DockStyle.Fill,
        BackColor = Color.FromArgb(15, 17, 20),
        SizeMode = PictureBoxSizeMode.Zoom,
        TabStop = true
    };

    private readonly object sendLock = new();
    private StreamWriter? controlWriter;
    private TcpClient? controlClient;
    private TcpClient? videoClient;
    private CancellationTokenSource? sessionCts;
    private volatile bool wantConnected;
    private volatile bool controlReady;
    private volatile bool accessibilityReady;
    private volatile string foregroundPackage = "";

    private readonly object frameLock = new();
    private Bitmap? pendingFrame;

    private readonly HashSet<int> pressed = new();
    private bool joystickIsDown;
    private float lastJoyX;
    private float lastJoyY;
    private DateTime lastJoySend = DateTime.MinValue;
    private DateTime lastManualCamera = DateTime.MinValue;

    private bool pointerDown;
    private bool pointerDragged;
    private Point pointerDownPoint;
    private Point pointerLastPoint;
    private string? pointPickAction;

    private bool cameraLock;
    private bool cursorHidden;
    private int rawDx;
    private int rawDy;

    private readonly System.Windows.Forms.Timer inputTimer = new() { Interval = 20 };
    private readonly System.Windows.Forms.Timer frameTimer = new() { Interval = 30 };
    private readonly System.Windows.Forms.Timer pingTimer = new() { Interval = 2000 };

    public MainForm()
    {
        Text = "Almas Remote V2";
        Width = 1220;
        Height = 760;
        MinimumSize = new Size(900, 560);
        StartPosition = FormStartPosition.CenterScreen;
        KeyPreview = true;
        BackColor = Color.FromArgb(20, 22, 26);

        BuildUi();
        UpdateModeButtons();

        connectButton.Click += (_, _) => ToggleConnection();
        backButton.Click += (_, _) => SendCommand("GLOBAL BACK");
        homeButton.Click += (_, _) => SendCommand("GLOBAL HOME");
        inputButton.Click += (_, _) =>
        {
            profile.GameInputEnabled = !profile.GameInputEnabled;
            if (!profile.GameInputEnabled) SafeStopInput();
            profile.Save();
            UpdateModeButtons();
        };
        cameraButton.Click += (_, _) => SetCameraLock(!cameraLock);
        settingsButton.Click += (_, _) => OpenSettings();

        videoBox.MouseDown += VideoMouseDown;
        videoBox.MouseMove += VideoMouseMove;
        videoBox.MouseUp += VideoMouseUp;
        videoBox.MouseWheel += VideoMouseWheel;
        videoBox.MouseEnter += (_, _) => videoBox.Focus();
        videoBox.Paint += VideoBoxPaint;

        KeyDown += MainKeyDown;
        KeyUp += MainKeyUp;
        Deactivate += (_, _) =>
        {
            if (cameraLock) SetCameraLock(false);
            SafeStopInput();
        };
        FormClosing += (_, _) =>
        {
            wantConnected = false;
            SafeStopInput();
            sessionCts?.Cancel();
            DisposeSockets();
            lock (frameLock) { pendingFrame?.Dispose(); pendingFrame = null; }
            videoBox.Image?.Dispose();
        };

        inputTimer.Tick += (_, _) => InputTick();
        frameTimer.Tick += (_, _) => PresentLatestFrame();
        pingTimer.Tick += (_, _) =>
        {
            if (controlReady) SendCommand("PING " + Environment.TickCount64);
        };
        inputTimer.Start();
        frameTimer.Start();
        pingTimer.Start();
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        RegisterRawMouse();
    }

    private void BuildUi()
    {
        var top = new Panel { Dock = DockStyle.Top, Height = 52, Padding = new Padding(8, 9, 8, 7), BackColor = Color.FromArgb(31, 34, 40) };
        var left = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = false,
            AutoScroll = true,
            BackColor = Color.Transparent
        };
        settingsButton.Dock = DockStyle.Right;
        settingsButton.Margin = new Padding(6, 0, 0, 0);

        left.Controls.Add(new Label { Text = "Телефон IP:", AutoSize = true, Padding = new Padding(0, 6, 0, 0), ForeColor = Color.White });
        left.Controls.Add(ipBox);
        left.Controls.Add(new Label { Text = "PIN:", AutoSize = true, Padding = new Padding(6, 6, 0, 0), ForeColor = Color.White });
        left.Controls.Add(pinBox);
        left.Controls.Add(connectButton);
        left.Controls.Add(backButton);
        left.Controls.Add(homeButton);
        left.Controls.Add(inputButton);
        left.Controls.Add(cameraButton);
        top.Controls.Add(left);
        top.Controls.Add(settingsButton);

        var bottom = new Panel { Dock = DockStyle.Bottom, Height = 34, Padding = new Padding(10, 7, 10, 4), BackColor = Color.FromArgb(31, 34, 40) };
        var statusFlow = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, WrapContents = false, AutoScroll = true };
        statusLabel.ForeColor = Color.White;
        appLabel.ForeColor = Color.Gainsboro;
        rttLabel.ForeColor = Color.Gainsboro;
        statusFlow.Controls.Add(statusLabel);
        statusFlow.Controls.Add(new Label { Text = "   |   ", AutoSize = true, ForeColor = Color.Gray });
        statusFlow.Controls.Add(appLabel);
        statusFlow.Controls.Add(new Label { Text = "   |   ", AutoSize = true, ForeColor = Color.Gray });
        statusFlow.Controls.Add(rttLabel);
        bottom.Controls.Add(statusFlow);

        Controls.Add(videoBox);
        Controls.Add(bottom);
        Controls.Add(top);
    }

    private void ToggleConnection()
    {
        if (wantConnected) StopSession();
        else StartSession();
    }

    private void StartSession()
    {
        string host = ipBox.Text.Trim();
        string pin = pinBox.Text.Trim();
        if (host.Length == 0 || pin.Length == 0)
        {
            MessageBox.Show(this, "Телефон IP және PIN енгіз.", "Almas Remote V2", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        StopSessionInternal(updateUi: false);
        wantConnected = true;
        sessionCts = new CancellationTokenSource();
        connectButton.Text = "Ажырату";
        SetStatus("Қосылып жатыр...");
        _ = Task.Run(() => ControlLoop(host, pin, sessionCts.Token));
        _ = Task.Run(() => VideoLoop(host, pin, sessionCts.Token));
    }

    private void StopSession()
    {
        StopSessionInternal(updateUi: true);
    }

    private void StopSessionInternal(bool updateUi)
    {
        wantConnected = false;
        SafeStopInput();
        sessionCts?.Cancel();
        sessionCts?.Dispose();
        sessionCts = null;
        DisposeSockets();
        controlReady = false;
        accessibilityReady = false;
        if (updateUi)
        {
            connectButton.Text = "Қосылу";
            SetStatus("Қосылмаған");
        }
    }

    private void DisposeSockets()
    {
        try { controlClient?.Close(); } catch { }
        try { videoClient?.Close(); } catch { }
        controlClient = null;
        videoClient = null;
        lock (sendLock) { controlWriter = null; }
    }

    private async Task ControlLoop(string host, string pin, CancellationToken ct)
    {
        int delay = 250;
        while (!ct.IsCancellationRequested && wantConnected)
        {
            TcpClient? client = null;
            StreamWriter? writer = null;
            try
            {
                client = new TcpClient { NoDelay = true };
                using var connectCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                connectCts.CancelAfter(TimeSpan.FromSeconds(5));
                await client.ConnectAsync(host, 5051, connectCts.Token);
                client.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.KeepAlive, true);
                NetworkStream stream = client.GetStream();
                writer = new StreamWriter(stream, new UTF8Encoding(false), 1024, leaveOpen: true) { AutoFlush = true };
                var reader = new StreamReader(stream, Encoding.UTF8, false, 1024, leaveOpen: true);
                await writer.WriteLineAsync("PIN " + pin);

                controlClient = client;
                lock (sendLock) controlWriter = writer;
                controlReady = true;
                delay = 250;
                Ui(() =>
                {
                    connectButton.Text = "Ажырату";
                    SetStatus("Control қосылды");
                });

                while (!ct.IsCancellationRequested && wantConnected)
                {
                    string? line = await reader.ReadLineAsync(ct);
                    if (line == null) throw new IOException("Control EOF");
                    HandleControlLine(line.Trim());
                }
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                Ui(() => SetStatus("Control қайта қосылуда: " + ex.Message));
            }
            finally
            {
                controlReady = false;
                lock (sendLock)
                {
                    if (ReferenceEquals(controlWriter, writer)) controlWriter = null;
                }
                try { client?.Close(); } catch { }
                Ui(() =>
                {
                    pressed.Clear();
                    joystickIsDown = false;
                    rawDx = rawDy = 0;
                });
            }

            if (!ct.IsCancellationRequested && wantConnected)
            {
                try { await Task.Delay(delay, ct); } catch { break; }
                delay = Math.Min(delay * 2, 2500);
            }
        }
    }

    private async Task VideoLoop(string host, string pin, CancellationToken ct)
    {
        int delay = 250;
        while (!ct.IsCancellationRequested && wantConnected)
        {
            TcpClient? client = null;
            try
            {
                client = new TcpClient { NoDelay = true };
                using var connectCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                connectCts.CancelAfter(TimeSpan.FromSeconds(5));
                await client.ConnectAsync(host, 5050, connectCts.Token);
                client.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.KeepAlive, true);
                videoClient = client;
                NetworkStream stream = client.GetStream();
                byte[] auth = Encoding.UTF8.GetBytes("PIN " + pin + "\n");
                await stream.WriteAsync(auth.AsMemory(), ct);
                await stream.FlushAsync(ct);
                delay = 250;
                Ui(() => SetStatus(controlReady ? "Қосылды" : "Видео қосылды, control күтілуде"));

                byte[] lenBuf = new byte[4];
                while (!ct.IsCancellationRequested && wantConnected)
                {
                    await ReadExactAsync(stream, lenBuf, ct);
                    int len = BinaryPrimitives.ReadInt32BigEndian(lenBuf);
                    if (len <= 0 || len > 8_000_000) throw new InvalidDataException("Қате frame өлшемі: " + len);
                    byte[] jpeg = new byte[len];
                    await ReadExactAsync(stream, jpeg, ct);
                    using var ms = new MemoryStream(jpeg, writable: false);
                    using var img = Image.FromStream(ms, useEmbeddedColorManagement: false, validateImageData: false);
                    var bmp = new Bitmap(img);
                    lock (frameLock)
                    {
                        pendingFrame?.Dispose();
                        pendingFrame = bmp;
                    }
                }
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                Ui(() => SetStatus("Видео қайта қосылуда: " + ex.Message));
            }
            finally
            {
                try { client?.Close(); } catch { }
                if (ReferenceEquals(videoClient, client)) videoClient = null;
            }

            if (!ct.IsCancellationRequested && wantConnected)
            {
                try { await Task.Delay(delay, ct); } catch { break; }
                delay = Math.Min(delay * 2, 2500);
            }
        }
    }

    private static async Task ReadExactAsync(Stream stream, byte[] buffer, CancellationToken ct)
    {
        int offset = 0;
        while (offset < buffer.Length)
        {
            int n = await stream.ReadAsync(buffer.AsMemory(offset, buffer.Length - offset), ct);
            if (n <= 0) throw new EndOfStreamException("EOF");
            offset += n;
        }
    }

    private void PresentLatestFrame()
    {
        Bitmap? bmp = null;
        lock (frameLock)
        {
            if (pendingFrame != null)
            {
                bmp = pendingFrame;
                pendingFrame = null;
            }
        }
        if (bmp == null) return;
        var old = videoBox.Image;
        videoBox.Image = bmp;
        old?.Dispose();
        videoBox.Invalidate();
    }

    private void HandleControlLine(string line)
    {
        if (line.StartsWith("APP ", StringComparison.Ordinal))
        {
            foregroundPackage = line.Length > 4 ? line[4..].Trim() : "";
            Ui(() =>
            {
                appLabel.Text = "APP: " + (foregroundPackage.Length == 0 ? "—" : foregroundPackage);
                UpdateModeButtons();
            });
            return;
        }
        if (line.StartsWith("ACCESS ", StringComparison.Ordinal))
        {
            accessibilityReady = line.EndsWith("1", StringComparison.Ordinal);
            Ui(() => SetStatus(accessibilityReady ? "Қосылды — басқару дайын" : "Accessibility қосылмаған"));
            return;
        }
        if (line.StartsWith("READY ", StringComparison.Ordinal))
        {
            string[] p = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (p.Length >= 3) accessibilityReady = p[2] == "1";
            Ui(() => SetStatus(accessibilityReady ? "Қосылды — V2 input дайын" : "Қосылды, бірақ Accessibility керек"));
            return;
        }
        if (line.StartsWith("PONG ", StringComparison.Ordinal) && long.TryParse(line[5..], out long sent))
        {
            long rtt = Math.Max(0, Environment.TickCount64 - sent);
            Ui(() => rttLabel.Text = "RTT: " + rtt + " ms");
        }
    }

    internal bool SendCommand(string command)
    {
        lock (sendLock)
        {
            try
            {
                if (controlWriter == null || !controlReady) return false;
                controlWriter.WriteLine(command);
                controlWriter.Flush();
                return true;
            }
            catch
            {
                return false;
            }
        }
    }

    private void MainKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.KeyCode == Keys.F2)
        {
            SetCameraLock(!cameraLock);
            e.SuppressKeyPress = true;
            return;
        }
        if (e.Control && e.Alt && e.KeyCode == Keys.Escape)
        {
            SafeStopInput();
            SetCameraLock(false);
            e.SuppressKeyPress = true;
            return;
        }

        if (!profile.GameInputEnabled || !controlReady || IsTextEntryActive()) return;
        string? action = ActionForKey(e.KeyCode);
        if (action == null) return;
        int code = (int)e.KeyCode;
        if (!pressed.Add(code))
        {
            e.SuppressKeyPress = true;
            return;
        }

        if (!MovementActions.Contains(action))
        {
            NormPoint p = profile.Target(action);
            if (profile.Mode(action) == "hold") SendCommand($"HOLD {action} DOWN {F(p.X)} {F(p.Y)}");
            else SendCommand($"TAP {F(p.X)} {F(p.Y)}");
        }
        e.SuppressKeyPress = true;
    }

    private void MainKeyUp(object? sender, KeyEventArgs e)
    {
        int code = (int)e.KeyCode;
        string? action = ActionForKey(e.KeyCode);
        pressed.Remove(code);
        if (action != null && !MovementActions.Contains(action) && profile.Mode(action) == "hold")
            SendCommand($"HOLD {action} UP");
        if (action != null) e.SuppressKeyPress = true;
    }

    private string? ActionForKey(Keys key)
    {
        int code = (int)key;
        foreach (var kv in profile.KeyBindings)
            if (kv.Value != 0 && kv.Value == code) return kv.Key;
        return null;
    }

    private bool IsTextEntryActive()
    {
        return ActiveControl is TextBoxBase || ipBox.Focused || pinBox.Focused;
    }

    private void InputTick()
    {
        if (!profile.GameInputEnabled || !controlReady || !accessibilityReady)
        {
            if (joystickIsDown)
            {
                SendCommand("JOY UP");
                joystickIsDown = false;
            }
            rawDx = rawDy = 0;
            return;
        }

        int x = (profile.IsKeyDownFor("move_right", pressed) ? 1 : 0) - (profile.IsKeyDownFor("move_left", pressed) ? 1 : 0);
        int y = (profile.IsKeyDownFor("move_down", pressed) ? 1 : 0) - (profile.IsKeyDownFor("move_up", pressed) ? 1 : 0);

        if (x == 0 && y == 0)
        {
            if (joystickIsDown)
            {
                SendCommand("JOY UP");
                joystickIsDown = false;
            }
        }
        else
        {
            float mag = MathF.Sqrt(x * x + y * y);
            float ux = x / mag;
            float uy = y / mag;
            NormPoint c = profile.Target("joystick");
            float tx = Clamp(c.X + profile.JoystickRadius * ux);
            float ty = Clamp(c.Y + profile.JoystickRadius * uy);
            bool heartbeat = (DateTime.UtcNow - lastJoySend).TotalMilliseconds > 90;
            if (!joystickIsDown)
            {
                SendCommand($"JOY DOWN {F(c.X)} {F(c.Y)} {F(tx)} {F(ty)}");
                joystickIsDown = true;
                lastJoyX = tx; lastJoyY = ty; lastJoySend = DateTime.UtcNow;
            }
            else if (heartbeat || Math.Abs(tx - lastJoyX) > 0.001f || Math.Abs(ty - lastJoyY) > 0.001f)
            {
                SendCommand($"JOY MOVE {F(tx)} {F(ty)}");
                lastJoyX = tx; lastJoyY = ty; lastJoySend = DateTime.UtcNow;
            }

            if (profile.AutoCamera && x != 0 && (DateTime.UtcNow - lastManualCamera).TotalMilliseconds > 150)
            {
                NormPoint cam = profile.Target("camera");
                float sign = profile.AutoCameraInvertX ? -1f : 1f;
                float dx = sign * ux * profile.AutoCameraStep;
                SendCommand($"CAM {F(cam.X)} {F(cam.Y)} {F(dx)} 0");
            }
        }

        if (cameraLock && (rawDx != 0 || rawDy != 0))
        {
            int dxRaw = rawDx;
            int dyRaw = rawDy;
            rawDx = rawDy = 0;
            Rectangle vr = GetImageRect();
            if (vr.Width > 10 && vr.Height > 10)
            {
                NormPoint cam = profile.Target("camera");
                float dx = Math.Clamp(dxRaw / (float)vr.Width * profile.TouchpadCameraSensitivity, -0.12f, 0.12f);
                float dy = Math.Clamp(dyRaw / (float)vr.Height * profile.TouchpadCameraSensitivity, -0.12f, 0.12f);
                if (Math.Abs(dx) > 0.0001f || Math.Abs(dy) > 0.0001f)
                {
                    SendCommand($"CAM {F(cam.X)} {F(cam.Y)} {F(dx)} {F(dy)}");
                    lastManualCamera = DateTime.UtcNow;
                }
            }
        }
    }

    private void VideoMouseDown(object? sender, MouseEventArgs e)
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

        if (cameraLock) return;
        pointerDown = true;
        pointerDragged = false;
        pointerDownPoint = e.Location;
        pointerLastPoint = e.Location;
        if (!GameCameraActive)
            SendCommand($"DIRECT DOWN {F(nx)} {F(ny)}");
    }

    private void VideoMouseMove(object? sender, MouseEventArgs e)
    {
        if (!pointerDown || cameraLock) return;
        int totalDx = e.X - pointerDownPoint.X;
        int totalDy = e.Y - pointerDownPoint.Y;
        if (Math.Abs(totalDx) + Math.Abs(totalDy) > 5) pointerDragged = true;

        if (GameCameraActive)
        {
            if (!pointerDragged) return;
            Rectangle vr = GetImageRect();
            if (vr.Width < 10 || vr.Height < 10) return;
            int dxPx = e.X - pointerLastPoint.X;
            int dyPx = e.Y - pointerLastPoint.Y;
            pointerLastPoint = e.Location;
            if (dxPx == 0 && dyPx == 0) return;
            NormPoint cam = profile.Target("camera");
            float dx = Math.Clamp(dxPx / (float)vr.Width * profile.TouchpadCameraSensitivity, -0.12f, 0.12f);
            float dy = Math.Clamp(dyPx / (float)vr.Height * profile.TouchpadCameraSensitivity, -0.12f, 0.12f);
            SendCommand($"CAM {F(cam.X)} {F(cam.Y)} {F(dx)} {F(dy)}");
            lastManualCamera = DateTime.UtcNow;
        }
        else if (TryNorm(e.Location, out float nx, out float ny))
        {
            SendCommand($"DIRECT MOVE {F(nx)} {F(ny)}");
        }
    }

    private void VideoMouseUp(object? sender, MouseEventArgs e)
    {
        if (e.Button != MouseButtons.Left || !pointerDown) return;
        pointerDown = false;
        if (cameraLock) return;

        if (GameCameraActive)
        {
            if (!pointerDragged && TryNorm(e.Location, out float nx, out float ny))
                SendCommand($"TAP {F(nx)} {F(ny)}");
        }
        else
        {
            SendCommand("DIRECT UP");
        }
    }

    private void VideoMouseWheel(object? sender, MouseEventArgs e)
    {
        if (!controlReady) return;
        float y1 = 0.56f;
        float y2 = e.Delta > 0 ? 0.34f : 0.78f;
        SendCommand($"SWIPE 0.50 {F(y1)} 0.50 {F(y2)} 150");
    }

    private bool GameCameraActive
    {
        get
        {
            if (profile.ForceGameCamera) return true;
            string pkg = foregroundPackage;
            return profile.GamePackages.Any(p => string.Equals(p, pkg, StringComparison.OrdinalIgnoreCase));
        }
    }

    private void OpenSettings()
    {
        SetCameraLock(false);
        SafeStopInput();
        using var f = new SettingsForm(this, profile);
        f.ShowDialog(this);
        profile.Save();
        UpdateModeButtons();
        videoBox.Focus();
    }

    internal void AssignKey(string action, Keys key)
    {
        profile.AssignKey(action, key);
        profile.Save();
    }

    internal void StartPointPick(string action)
    {
        pointPickAction = action;
        SetStatus("Экраннан нүктені бас: " + PointLabel(action));
        videoBox.Focus();
        videoBox.Invalidate();
    }

    internal void ApplySettings(bool gameInputEnabled, bool autoCamera, bool autoInvert, bool forceGameCamera,
        float joyRadius, float autoStep, float touchSensitivity)
    {
        profile.GameInputEnabled = gameInputEnabled;
        profile.AutoCamera = autoCamera;
        profile.AutoCameraInvertX = autoInvert;
        profile.ForceGameCamera = forceGameCamera;
        profile.JoystickRadius = joyRadius;
        profile.AutoCameraStep = autoStep;
        profile.TouchpadCameraSensitivity = touchSensitivity;
        profile.Save();
        UpdateModeButtons();
    }

    private void SafeStopInput()
    {
        pressed.Clear();
        joystickIsDown = false;
        pointerDown = false;
        rawDx = rawDy = 0;
        SendCommand("CANCEL");
    }

    private void SetCameraLock(bool enabled)
    {
        if (enabled && !controlReady)
        {
            SetStatus("Алдымен телефонға қосыл");
            return;
        }
        cameraLock = enabled;
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
        UpdateModeButtons();
    }

    private void UpdateModeButtons()
    {
        inputButton.Text = profile.GameInputEnabled ? "⌨ KEYMAP: ON" : "⌨ KEYMAP: OFF";
        cameraButton.Text = cameraLock ? "🎯 CAMERA: ON" : "🎯 CAMERA: OFF";
        cameraButton.BackColor = cameraLock ? Color.LightGreen : SystemColors.Control;
    }

    private void VideoBoxPaint(object? sender, PaintEventArgs e)
    {
        if (videoBox.Image == null) return;
        if (pointPickAction == null) return;
        Rectangle r = GetImageRect();
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var pen = new Pen(Color.Lime, 2);
        using var brush = new SolidBrush(Color.FromArgb(80, Color.Lime));
        foreach (var kv in profile.Targets)
        {
            int x = r.Left + (int)(kv.Value.X * r.Width);
            int y = r.Top + (int)(kv.Value.Y * r.Height);
            e.Graphics.FillEllipse(brush, x - 8, y - 8, 16, 16);
            e.Graphics.DrawEllipse(pen, x - 8, y - 8, 16, 16);
        }
    }

    private Rectangle GetImageRect()
    {
        if (videoBox.Image == null || videoBox.ClientSize.Width <= 0 || videoBox.ClientSize.Height <= 0)
            return Rectangle.Empty;
        float imageAspect = videoBox.Image.Width / (float)videoBox.Image.Height;
        float boxAspect = videoBox.ClientSize.Width / (float)videoBox.ClientSize.Height;
        int w, h, x, y;
        if (imageAspect > boxAspect)
        {
            w = videoBox.ClientSize.Width;
            h = (int)(w / imageAspect);
            x = 0; y = (videoBox.ClientSize.Height - h) / 2;
        }
        else
        {
            h = videoBox.ClientSize.Height;
            w = (int)(h * imageAspect);
            y = 0; x = (videoBox.ClientSize.Width - w) / 2;
        }
        return new Rectangle(x, y, Math.Max(1, w), Math.Max(1, h));
    }

    private bool TryNorm(Point p, out float x, out float y)
    {
        Rectangle r = GetImageRect();
        if (r.Width <= 1 || r.Height <= 1 || !r.Contains(p))
        {
            x = y = 0;
            return false;
        }
        x = Clamp((p.X - r.Left) / (float)r.Width);
        y = Clamp((p.Y - r.Top) / (float)r.Height);
        return true;
    }

    private void SetStatus(string text)
    {
        if (InvokeRequired) { Ui(() => SetStatus(text)); return; }
        statusLabel.Text = text;
    }

    private void Ui(Action action)
    {
        try
        {
            if (IsDisposed || Disposing) return;
            if (InvokeRequired) BeginInvoke(action); else action();
        }
        catch { }
    }

    private static string F(float v) => v.ToString("0.00000", System.Globalization.CultureInfo.InvariantCulture);
    private static float Clamp(float v) => Math.Max(0f, Math.Min(1f, v));
    private static string PointLabel(string action) => action switch
    {
        "joystick" => "Joystick ортасы",
        "camera" => "Камера аймағы",
        _ => ActionLabels.TryGetValue(action, out string? s) ? s : action
    };

    // ---------------- Raw Input: real relative movement from mouse/touchpad ----------------
    private const int WM_INPUT = 0x00FF;
    private const uint RID_INPUT = 0x10000003;
    private const uint RIM_TYPEMOUSE = 0;

    [StructLayout(LayoutKind.Sequential)]
    private struct RAWINPUTDEVICE
    {
        public ushort usUsagePage;
        public ushort usUsage;
        public uint dwFlags;
        public IntPtr hwndTarget;
    }

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterRawInputDevices([In] RAWINPUTDEVICE[] pRawInputDevices, uint uiNumDevices, uint cbSize);

    [DllImport("user32.dll")]
    private static extern uint GetRawInputData(IntPtr hRawInput, uint uiCommand, IntPtr pData, ref uint pcbSize, uint cbSizeHeader);

    private void RegisterRawMouse()
    {
        try
        {
            var rid = new RAWINPUTDEVICE
            {
                usUsagePage = 0x01,
                usUsage = 0x02,
                dwFlags = 0,
                hwndTarget = Handle
            };
            RegisterRawInputDevices(new[] { rid }, 1, (uint)Marshal.SizeOf<RAWINPUTDEVICE>());
        }
        catch { }
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == WM_INPUT && cameraLock && controlReady)
        {
            try
            {
                uint size = 0;
                uint headerSize = (uint)(IntPtr.Size == 8 ? 24 : 16);
                GetRawInputData(m.LParam, RID_INPUT, IntPtr.Zero, ref size, headerSize);
                if (size >= headerSize + 20)
                {
                    IntPtr ptr = Marshal.AllocHGlobal((int)size);
                    try
                    {
                        if (GetRawInputData(m.LParam, RID_INPUT, ptr, ref size, headerSize) == size)
                        {
                            uint type = (uint)Marshal.ReadInt32(ptr, 0);
                            if (type == RIM_TYPEMOUSE)
                            {
                                int dx = Marshal.ReadInt32(ptr, (int)headerSize + 12);
                                int dy = Marshal.ReadInt32(ptr, (int)headerSize + 16);
                                rawDx += dx;
                                rawDy += dy;
                            }
                        }
                    }
                    finally { Marshal.FreeHGlobal(ptr); }
                }
            }
            catch { }
        }
        base.WndProc(ref m);
    }

    // ---------------- Settings ----------------
    private sealed class SettingsForm : Form
    {
        private readonly MainForm owner;
        private readonly RemoteProfile profile;
        private readonly CheckBox inputEnabled = new() { Text = "⌨ Перне басқаруын қосу", AutoSize = true };
        private readonly CheckBox autoCamera = new() { Text = "Joystick оң/солға кеткенде камераны автоматты бұру", AutoSize = true };
        private readonly CheckBox invertAuto = new() { Text = "Auto camera X кері бағыт (оңға жүрсе — экран солға ыңайланады)", AutoSize = true };
        private readonly CheckBox forceGame = new() { Text = "Камера режимін қолмен мәжбүрлеу", AutoSize = true };
        private readonly TrackBar radius = new() { Minimum = 3, Maximum = 22, TickFrequency = 1, Width = 360 };
        private readonly TrackBar autoStep = new() { Minimum = 2, Maximum = 40, TickFrequency = 2, Width = 360 };
        private readonly TrackBar touchSens = new() { Minimum = 30, Maximum = 300, TickFrequency = 10, Width = 360 };
        private readonly Dictionary<string, Button> keyButtons = new();

        public SettingsForm(MainForm owner, RemoteProfile profile)
        {
            this.owner = owner;
            this.profile = profile;
            Text = "Almas Remote V2 — Настройка";
            Width = 760;
            Height = 700;
            MinimumSize = new Size(650, 560);
            StartPosition = FormStartPosition.CenterParent;
            KeyPreview = true;

            var tabs = new TabControl { Dock = DockStyle.Fill };
            var keysTab = new TabPage("Пернелер");
            var pointsTab = new TabPage("Экран нүктелері");
            var cameraTab = new TabPage("Joystick / камера");
            tabs.TabPages.Add(keysTab);
            tabs.TabPages.Add(pointsTab);
            tabs.TabPages.Add(cameraTab);

            BuildKeys(keysTab);
            BuildPoints(pointsTab);
            BuildCamera(cameraTab);

            var bottom = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 52, FlowDirection = FlowDirection.RightToLeft, Padding = new Padding(8) };
            var save = new Button { Text = "Сақтау", Width = 100 };
            var close = new Button { Text = "Жабу", Width = 100 };
            save.Click += (_, _) => SaveSettings(closeAfter: true);
            close.Click += (_, _) => Close();
            bottom.Controls.Add(save);
            bottom.Controls.Add(close);

            Controls.Add(tabs);
            Controls.Add(bottom);
        }

        private void BuildKeys(TabPage tab)
        {
            var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoScroll = true, FlowDirection = FlowDirection.TopDown, WrapContents = false, Padding = new Padding(12) };
            inputEnabled.Checked = profile.GameInputEnabled;
            panel.Controls.Add(inputEnabled);
            panel.Controls.Add(new Label
            {
                Text = "Функция → «Перне таңдау» → клавиатурадан бір батырма бас. Бір перне тек бір функцияда қалады.",
                AutoSize = true,
                MaximumSize = new Size(680, 0),
                Padding = new Padding(0, 8, 0, 10)
            });

            foreach (string action in Actions)
            {
                var row = new FlowLayoutPanel { Width = 680, Height = 38, FlowDirection = FlowDirection.LeftToRight, WrapContents = false };
                row.Controls.Add(new Label { Text = ActionLabels[action], Width = 150, Padding = new Padding(0, 8, 0, 0) });
                var key = new Button { Width = 125, Text = KeyName(action) };
                keyButtons[action] = key;
                key.Click += (_, _) => CaptureKey(action);
                row.Controls.Add(key);
                if (!MovementActions.Contains(action))
                {
                    var mode = new ComboBox { Width = 100, DropDownStyle = ComboBoxStyle.DropDownList, Tag = action };
                    mode.Items.AddRange(new object[] { "tap", "hold" });
                    mode.SelectedItem = profile.Mode(action);
                    mode.SelectedIndexChanged += (_, _) =>
                    {
                        if (mode.SelectedItem is string m) profile.Modes[action] = m;
                    };
                    row.Controls.Add(new Label { Text = "Режим:", Width = 60, Padding = new Padding(6, 8, 0, 0) });
                    row.Controls.Add(mode);
                }
                panel.Controls.Add(row);
            }
            tab.Controls.Add(panel);
        }

        private void BuildPoints(TabPage tab)
        {
            var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoScroll = true, FlowDirection = FlowDirection.TopDown, WrapContents = false, Padding = new Padding(12) };
            panel.Controls.Add(new Label
            {
                Text = "Нүктені таңдау батырмасын бас. Настройка жабылады. Сосын телефон видеосының үстінен дәл керекті батырманы touchpad-пен бір рет бас.",
                AutoSize = true,
                MaximumSize = new Size(680, 0),
                Padding = new Padding(0, 0, 0, 12)
            });
            string[] points = { "joystick", "camera", "run", "jump", "fire", "aim", "reload", "interact" };
            foreach (string action in points)
            {
                var b = new Button { Width = 500, Height = 38, Text = "Экраннан таңдау: " + PointLabel(action) };
                b.Click += (_, _) =>
                {
                    SaveSettings(closeAfter: false);
                    owner.StartPointPick(action);
                    Close();
                };
                panel.Controls.Add(b);
            }
            tab.Controls.Add(panel);
        }

        private void BuildCamera(TabPage tab)
        {
            var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoScroll = true, FlowDirection = FlowDirection.TopDown, WrapContents = false, Padding = new Padding(12) };
            autoCamera.Checked = profile.AutoCamera;
            invertAuto.Checked = profile.AutoCameraInvertX;
            forceGame.Checked = profile.ForceGameCamera;
            radius.Value = Math.Clamp((int)Math.Round(profile.JoystickRadius * 100), radius.Minimum, radius.Maximum);
            autoStep.Value = Math.Clamp((int)Math.Round(profile.AutoCameraStep * 1000), autoStep.Minimum, autoStep.Maximum);
            touchSens.Value = Math.Clamp((int)Math.Round(profile.TouchpadCameraSensitivity * 100), touchSens.Minimum, touchSens.Maximum);

            panel.Controls.Add(autoCamera);
            panel.Controls.Add(invertAuto);
            panel.Controls.Add(forceGame);
            panel.Controls.Add(new Label { Text = "Joystick радиусы", AutoSize = true, Padding = new Padding(0, 14, 0, 0) });
            panel.Controls.Add(radius);
            panel.Controls.Add(new Label { Text = "Auto camera күші", AutoSize = true, Padding = new Padding(0, 14, 0, 0) });
            panel.Controls.Add(autoStep);
            panel.Controls.Add(new Label { Text = "Touchpad камера сезімталдығы", AutoSize = true, Padding = new Padding(0, 14, 0, 0) });
            panel.Controls.Add(touchSens);
            panel.Controls.Add(new Label
            {
                Text = "F2 — Camera Lock. Camera Lock қосылса, touchpad-ты жай қозғау камераны бұрады; қайта F2 бассаң кәдімгі курсор режиміне қайтады. Ctrl+Alt+Esc — барлық remote input-ты шұғыл тоқтату.",
                AutoSize = true,
                MaximumSize = new Size(680, 0),
                Padding = new Padding(0, 18, 0, 0)
            });
            tab.Controls.Add(panel);
        }

        private void CaptureKey(string action)
        {
            using var cap = new KeyCaptureForm(ActionLabels[action]);
            if (cap.ShowDialog(this) == DialogResult.OK && cap.CapturedKey != Keys.None)
            {
                owner.AssignKey(action, cap.CapturedKey);
                foreach (var kv in keyButtons) kv.Value.Text = KeyName(kv.Key);
            }
        }

        private string KeyName(string action)
        {
            if (!profile.KeyBindings.TryGetValue(action, out int code) || code == 0) return "—";
            return ((Keys)code).ToString();
        }

        private void SaveSettings(bool closeAfter)
        {
            owner.ApplySettings(
                inputEnabled.Checked,
                autoCamera.Checked,
                invertAuto.Checked,
                forceGame.Checked,
                radius.Value / 100f,
                autoStep.Value / 1000f,
                touchSens.Value / 100f);
            profile.Save();
            if (closeAfter) Close();
        }
    }

    private sealed class KeyCaptureForm : Form
    {
        public Keys CapturedKey { get; private set; } = Keys.None;

        public KeyCaptureForm(string actionName)
        {
            Text = "Перне таңдау";
            Width = 420;
            Height = 180;
            StartPosition = FormStartPosition.CenterParent;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            KeyPreview = true;
            var label = new Label
            {
                Dock = DockStyle.Fill,
                TextAlign = ContentAlignment.MiddleCenter,
                Font = new Font("Segoe UI", 12, FontStyle.Bold),
                Text = actionName + " үшін бір пернені бас\n\nEsc = бас тарту"
            };
            Controls.Add(label);
            KeyDown += (_, e) =>
            {
                if (e.KeyCode == Keys.Escape)
                {
                    DialogResult = DialogResult.Cancel;
                    Close();
                    return;
                }
                if (e.KeyCode is Keys.ControlKey or Keys.Menu or Keys.ShiftKey) return;
                CapturedKey = e.KeyCode;
                DialogResult = DialogResult.OK;
                e.SuppressKeyPress = true;
                Close();
            };
        }
    }
}
