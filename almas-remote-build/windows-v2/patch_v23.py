from pathlib import Path

p = Path('MainForm.cs')
s = p.read_text(encoding='utf-8')

s = s.replace('Text = "Almas Remote V2.2";', 'Text = "Almas Remote V2.3";', 1)

old_fields = '''    private readonly object frameLock = new();
    private Bitmap? pendingFrame;
'''
new_fields = '''    private readonly object frameLock = new();
    private Bitmap? pendingFrame;
    private readonly object jpegLock = new();
    private byte[]? latestJpeg;
'''
if old_fields not in s:
    raise SystemExit('frame fields block not found')
s = s.replace(old_fields, new_fields, 1)

old_start = '''        _ = Task.Run(() => ControlLoop(host, pin, sessionCts.Token));
        _ = Task.Run(() => VideoLoop(host, pin, sessionCts.Token));
'''
new_start = '''        _ = Task.Run(() => ControlLoop(host, pin, sessionCts.Token));
        _ = Task.Run(() => VideoLoop(host, pin, sessionCts.Token));
        _ = Task.Run(() => DecodeLoop(sessionCts.Token));
'''
if old_start not in s:
    raise SystemExit('StartSession task block not found')
s = s.replace(old_start, new_start, 1)

old_stop = '''        controlReady = false;
        accessibilityReady = false;
'''
new_stop = '''        controlReady = false;
        accessibilityReady = false;
        lock (jpegLock) latestJpeg = null;
'''
if old_stop not in s:
    raise SystemExit('stop state block not found')
s = s.replace(old_stop, new_stop, 1)

old_decode = '''                    byte[] jpeg = new byte[len];
                    await ReadExactAsync(stream, jpeg, ct);
                    using var ms = new MemoryStream(jpeg, writable: false);
                    using var img = Image.FromStream(ms, useEmbeddedColorManagement: false, validateImageData: false);
                    var bmp = new Bitmap(img);
                    lock (frameLock)
                    {
                        pendingFrame?.Dispose();
                        pendingFrame = bmp;
                    }
'''
new_decode = '''                    byte[] jpeg = new byte[len];
                    await ReadExactAsync(stream, jpeg, ct);

                    // Network reader never waits for JPEG decode. Keep only the newest encoded frame.
                    lock (jpegLock)
                    {
                        latestJpeg = jpeg;
                    }

                    // V2.3 protocol: ACK each received frame so Host keeps at most one frame in flight.
                    await stream.WriteAsync(new byte[] { 0x41 }, ct);
'''
if old_decode not in s:
    raise SystemExit('inline video decode block not found')
s = s.replace(old_decode, new_decode, 1)

insert_at = s.index('    private static async Task ReadExactAsync', s.index('    private async Task VideoLoop'))
decode_method = r'''    private async Task DecodeLoop(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            byte[]? jpeg = null;
            lock (jpegLock)
            {
                if (latestJpeg != null)
                {
                    jpeg = latestJpeg;
                    latestJpeg = null;
                }
            }

            if (jpeg == null)
            {
                try { await Task.Delay(4, ct); } catch { break; }
                continue;
            }

            try
            {
                using var ms = new MemoryStream(jpeg, writable: false);
                using var img = Image.FromStream(ms, useEmbeddedColorManagement: false, validateImageData: false);
                var bmp = new Bitmap(img);
                lock (frameLock)
                {
                    pendingFrame?.Dispose();
                    pendingFrame = bmp;
                }
            }
            catch
            {
                // Corrupt/stale frame: drop it. The next newest frame replaces it immediately.
            }
        }
    }

'''
s = s[:insert_at] + decode_method + s[insert_at:]

p.write_text(s, encoding='utf-8')
print('V2.3 Windows low-latency patch applied')
