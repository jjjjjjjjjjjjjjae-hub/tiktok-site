package kz.almas.remote;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.concurrent.TimeUnit;

/** Small, explicit Magisk/su bridge. Root is never hidden: the user must grant it in Magisk. */
public final class RootBridge {
    private static volatile boolean rootGranted;
    private static volatile boolean uinputAvailable;

    private RootBridge() {}

    public static final class Status {
        public final boolean root;
        public final boolean uinput;
        public final String detail;

        Status(boolean root, boolean uinput, String detail) {
            this.root = root;
            this.uinput = uinput;
            this.detail = detail == null ? "" : detail;
        }
    }

    /** Called from the UI. This may trigger the visible Magisk Grant dialog. */
    public static Status probeInteractive() {
        String id = shell("id", 30000);
        boolean root = id.contains("uid=0");
        boolean uinput = false;
        if (root) {
            String r = shell("if [ -e /dev/uinput ]; then echo 1; else echo 0; fi", 3000);
            uinput = r.trim().endsWith("1");
        }
        rootGranted = root;
        uinputAvailable = uinput;
        return new Status(root, uinput, id);
    }

    public static boolean isRootGranted() { return rootGranted; }
    public static boolean isUinputAvailable() { return uinputAvailable; }

    /** Short, bounded root command for the service. Never wait forever for a su prompt. */
    public static String shellFast(String command) {
        return shell(command, 2500);
    }

    private static String shell(String command, long timeoutMs) {
        Process p = null;
        try {
            p = new ProcessBuilder("su", "-c", command).redirectErrorStream(true).start();
            boolean done = p.waitFor(timeoutMs, TimeUnit.MILLISECONDS);
            if (!done) {
                try { p.destroy(); } catch (Throwable ignored) {}
                try { p.destroyForcibly(); } catch (Throwable ignored) {}
                return "";
            }
            BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()));
            StringBuilder b = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) {
                if (b.length() > 0) b.append('\n');
                b.append(line);
            }
            return b.toString().trim();
        } catch (Throwable ignored) {
            return "";
        } finally {
            if (p != null) try { p.destroy(); } catch (Throwable ignored) {}
        }
    }
}
