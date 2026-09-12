using System.Text.Json;

namespace AlmasRemoteV2;

public sealed class NormPoint
{
    public float X { get; set; }
    public float Y { get; set; }

    public NormPoint() { }
    public NormPoint(float x, float y) { X = x; Y = y; }
}

public sealed class RemoteProfile
{
    public int SchemaVersion { get; set; } = 2;
    public Dictionary<string, int> KeyBindings { get; set; } = new();
    public Dictionary<string, NormPoint> Targets { get; set; } = new();
    public Dictionary<string, string> Modes { get; set; } = new();
    public float JoystickRadius { get; set; } = 0.10f;
    public float AutoCameraStep { get; set; } = 0.012f;
    public float TouchpadCameraSensitivity { get; set; } = 1.35f;
    public bool AutoCamera { get; set; } = true;
    public bool AutoCameraInvertX { get; set; } = true;
    public bool GameInputEnabled { get; set; } = true;
    public bool ForceGameCamera { get; set; } = false;
    public List<string> GamePackages { get; set; } = new()
    {
        "com.dts.freefireth",
        "com.dts.freefiremax"
    };

    public static string ProfilePath
    {
        get
        {
            string dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AlmasRemoteV2");
            Directory.CreateDirectory(dir);
            return Path.Combine(dir, "profile.json");
        }
    }

    public static RemoteProfile CreateDefault()
    {
        var p = new RemoteProfile();
        p.KeyBindings["move_up"] = (int)System.Windows.Forms.Keys.W;
        p.KeyBindings["move_down"] = (int)System.Windows.Forms.Keys.S;
        p.KeyBindings["move_left"] = (int)System.Windows.Forms.Keys.A;
        p.KeyBindings["move_right"] = (int)System.Windows.Forms.Keys.D;
        p.KeyBindings["run"] = (int)System.Windows.Forms.Keys.ShiftKey;
        p.KeyBindings["jump"] = (int)System.Windows.Forms.Keys.Space;
        p.KeyBindings["fire"] = 0;
        p.KeyBindings["aim"] = 0;
        p.KeyBindings["reload"] = (int)System.Windows.Forms.Keys.R;
        p.KeyBindings["interact"] = (int)System.Windows.Forms.Keys.F;

        p.Targets["joystick"] = new NormPoint(0.18f, 0.73f);
        p.Targets["camera"] = new NormPoint(0.72f, 0.50f);
        p.Targets["run"] = new NormPoint(0.82f, 0.61f);
        p.Targets["jump"] = new NormPoint(0.89f, 0.48f);
        p.Targets["fire"] = new NormPoint(0.92f, 0.67f);
        p.Targets["aim"] = new NormPoint(0.82f, 0.37f);
        p.Targets["reload"] = new NormPoint(0.76f, 0.77f);
        p.Targets["interact"] = new NormPoint(0.62f, 0.64f);

        p.Modes["run"] = "tap";
        p.Modes["jump"] = "tap";
        p.Modes["fire"] = "hold";
        p.Modes["aim"] = "hold";
        p.Modes["reload"] = "tap";
        p.Modes["interact"] = "tap";
        return p;
    }

    public static RemoteProfile Load()
    {
        try
        {
            if (!File.Exists(ProfilePath)) return CreateDefault();
            var p = JsonSerializer.Deserialize<RemoteProfile>(File.ReadAllText(ProfilePath));
            if (p == null) return CreateDefault();
            p.MergeMissingDefaults();
            return p;
        }
        catch
        {
            return CreateDefault();
        }
    }

    public void Save()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(ProfilePath)!);
        string tmp = ProfilePath + ".tmp";
        File.WriteAllText(tmp, JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
        File.Move(tmp, ProfilePath, true);
    }

    public void AssignKey(string action, System.Windows.Forms.Keys key)
    {
        int v = (int)key;
        foreach (string a in KeyBindings.Keys.ToList())
        {
            if (a != action && KeyBindings[a] == v) KeyBindings[a] = 0;
        }
        KeyBindings[action] = v;
    }

    public bool IsKeyDownFor(string action, HashSet<int> pressed)
    {
        return KeyBindings.TryGetValue(action, out int k) && k != 0 && pressed.Contains(k);
    }

    public NormPoint Target(string action)
    {
        if (Targets.TryGetValue(action, out var p)) return p;
        var d = CreateDefault();
        return d.Targets.TryGetValue(action, out var q) ? q : new NormPoint(0.5f, 0.5f);
    }

    public string Mode(string action)
    {
        return Modes.TryGetValue(action, out var m) ? m : "tap";
    }

    private void MergeMissingDefaults()
    {
        var d = CreateDefault();
        KeyBindings ??= new Dictionary<string, int>();
        Targets ??= new Dictionary<string, NormPoint>();
        Modes ??= new Dictionary<string, string>();
        foreach (var kv in d.KeyBindings) if (!KeyBindings.ContainsKey(kv.Key)) KeyBindings[kv.Key] = kv.Value;
        foreach (var kv in d.Targets) if (!Targets.ContainsKey(kv.Key)) Targets[kv.Key] = kv.Value;
        foreach (var kv in d.Modes) if (!Modes.ContainsKey(kv.Key)) Modes[kv.Key] = kv.Value;
        if (GamePackages == null || GamePackages.Count == 0) GamePackages = d.GamePackages;
        if (JoystickRadius <= 0f) JoystickRadius = d.JoystickRadius;
        if (TouchpadCameraSensitivity <= 0f) TouchpadCameraSensitivity = d.TouchpadCameraSensitivity;
        if (AutoCameraStep <= 0f) AutoCameraStep = d.AutoCameraStep;
    }
}
