package kz.almas.remote;

import android.content.Context;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** Persistent Magisk root backend backed by a virtual /dev/uinput touchscreen. */
public final class RootInputBackend {
    private static final int AXIS_MAX = 32767;
    private static final Object LOCK = new Object();
    private static Process process;
    private static BufferedWriter writer;
    private static volatile boolean ready;
    private static String remoteHelperPath;
    private static final Map<String, Integer> slots = new HashMap<>();

    static {
        slots.put("joystick", 0);
        slots.put("direct", 1);
        slots.put("hold:fire", 2);
        slots.put("hold:aim", 3);
        slots.put("hold:run", 4);
        slots.put("hold:jump", 5);
        slots.put("hold:reload", 6);
        slots.put("hold:interact", 7);
    }

    private RootInputBackend() {}

    public static boolean isReady() { return ready; }

    public static boolean start(Context context) {
        synchronized (LOCK) {
            if (ready && process != null && process.isAlive()) return true;
            stopLocked();
            if (!RootBridge.isRootGranted() || !RootBridge.isUinputAvailable()) return false;
            try {
                File helper = copyHelper(context);
                String src = shq(helper.getAbsolutePath());
                remoteHelperPath = "/data/local/tmp/almas_uinput_" + android.os.Process.myUid();
                String dst = shq(remoteHelperPath);
                String cmd = "cp " + src + " " + dst + "; chmod 755 " + dst + "; exec " + dst;
                process = new ProcessBuilder("su", "-c", cmd).redirectErrorStream(true).start();
                BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(4);
                String first = null;
                while (System.nanoTime() < deadline) {
                    if (reader.ready()) {
                        first = reader.readLine();
                        break;
                    }
                    if (!process.isAlive()) break;
                    Thread.sleep(20);
                }
                if (first == null || !first.startsWith("READY")) {
                    stopLocked();
                    return false;
                }
                writer = new BufferedWriter(new OutputStreamWriter(process.getOutputStream()));
                ready = true;
                Thread monitor = new Thread(() -> {
                    try {
                        while (process != null && process.isAlive()) {
                            String line = reader.readLine();
                            if (line == null) break;
                        }
                    } catch (Throwable ignored) {
                    } finally {
                        synchronized (LOCK) {
                            ready = false;
                            try { if (writer != null) writer.close(); } catch (Throwable ignored) {}
                            writer = null;
                        }
                    }
                }, "root-input-monitor");
                monitor.setDaemon(true);
                monitor.start();
                return true;
            } catch (Throwable ignored) {
                stopLocked();
                return false;
            }
        }
    }

    private static String shq(String s) {
        return "'" + s.replace("'", "'\\''") + "'";
    }

    private static File copyHelper(Context context) throws Exception {
        File out = new File(context.getFilesDir(), "almas_uinput");
        try (InputStream in = context.getAssets().open("almas_uinput");
             FileOutputStream fos = new FileOutputStream(out, false)) {
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) fos.write(buf, 0, n);
            fos.flush();
        }
        return out;
    }

    private static int slotFor(String id) {
        Integer s = slots.get(id);
        if (s != null) return s;
        if (id != null && id.startsWith("hold:")) return 7;
        return 1;
    }

    private static int n(float v) {
        if (v < 0f) v = 0f;
        if (v > 1f) v = 1f;
        return Math.round(v * AXIS_MAX);
    }

    private static boolean send(String line) {
        synchronized (LOCK) {
            if (!ready || writer == null || process == null || !process.isAlive()) return false;
            try {
                writer.write(line);
                writer.write('\n');
                writer.flush();
                return true;
            } catch (Throwable ignored) {
                ready = false;
                return false;
            }
        }
    }

    public static boolean pointerDown(String id, float x, float y) {
        return send("D " + slotFor(id) + " " + n(x) + " " + n(y));
    }

    public static boolean pointerMove(String id, float x, float y) {
        return send("M " + slotFor(id) + " " + n(x) + " " + n(y));
    }

    public static boolean pointerUp(String id) {
        return send("U " + slotFor(id));
    }

    public static boolean tap(float x, float y) {
        return send("T 8 " + n(x) + " " + n(y) + " 28");
    }

    public static boolean swipe(float x1, float y1, float x2, float y2, long durationMs) {
        int ms = (int)Math.max(16, Math.min(durationMs, 500));
        return send("S 9 " + n(x1) + " " + n(y1) + " " + n(x2) + " " + n(y2) + " " + ms);
    }

    public static boolean camera(float x, float y, float dx, float dy) {
        float x2 = Math.max(0f, Math.min(1f, x + dx));
        float y2 = Math.max(0f, Math.min(1f, y + dy));
        return send("S 9 " + n(x) + " " + n(y) + " " + n(x2) + " " + n(y2) + " 20");
    }

    public static void cancelAll() { send("CANCEL"); }

    public static void stop() {
        synchronized (LOCK) { stopLocked(); }
    }

    private static void stopLocked() {
        ready = false;
        try {
            if (writer != null) {
                writer.write("QUIT\n");
                writer.flush();
            }
        } catch (Throwable ignored) {}
        try { if (writer != null) writer.close(); } catch (Throwable ignored) {}
        writer = null;
        try { if (process != null) process.destroy(); } catch (Throwable ignored) {}
        process = null;
        if (remoteHelperPath != null && RootBridge.isRootGranted()) {
            try { RootBridge.shellFast("rm -f " + shq(remoteHelperPath)); } catch (Throwable ignored) {}
        }
        remoteHelperPath = null;
    }
}
