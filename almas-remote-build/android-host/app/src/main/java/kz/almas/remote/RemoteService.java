package kz.almas.remote;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.WindowManager;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicReference;

public class RemoteService extends Service {
    private static final String CHANNEL = "almas_remote_active";
    private volatile boolean running;
    private String pin;
    private MediaProjection projection;
    private VirtualDisplay virtualDisplay;
    private ImageReader reader;
    private DisplayManager displayManager;
    private Handler mainHandler;
    private int captureW;
    private int captureH;
    private int captureDensity;
    private final Object captureLock = new Object();
    private final AtomicReference<byte[]> latestFrame = new AtomicReference<>();

    private boolean orientationSaved;
    private String savedAccelRotation = "1";
    private String savedUserRotation = "0";
    private boolean landscapeForced;

    private final DisplayManager.DisplayListener displayListener = new DisplayManager.DisplayListener() {
        @Override public void onDisplayAdded(int displayId) {}
        @Override public void onDisplayRemoved(int displayId) {}
        @Override public void onDisplayChanged(int displayId) {
            if (displayId == Display.DEFAULT_DISPLAY && running && mainHandler != null) {
                mainHandler.removeCallbacks(resizeRunnable);
                mainHandler.postDelayed(resizeRunnable, 120);
            }
        }
    };

    private final Runnable resizeRunnable = () -> {
        try { resizeCaptureIfNeeded(); } catch (Throwable ignored) {}
    };

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) return START_NOT_STICKY;
        pin = intent.getStringExtra("pin");
        createNotification();
        if (running) return START_STICKY;
        running = true;
        mainHandler = new Handler(Looper.getMainLooper());

        int resultCode = intent.getIntExtra("resultCode", 0);
        Intent data = intent.getParcelableExtra("projectionData");
        MediaProjectionManager mgr = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        projection = mgr.getMediaProjection(resultCode, data);
        projection.registerCallback(new MediaProjection.Callback() {
            @Override public void onStop() { stopSelf(); }
        }, mainHandler);

        displayManager = (DisplayManager) getSystemService(DISPLAY_SERVICE);
        displayManager.registerDisplayListener(displayListener, mainHandler);
        startCapture();
        startServers();
        return START_STICKY;
    }

    private void createNotification() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Almas Remote active", NotificationManager.IMPORTANCE_LOW));
        }
        android.app.Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new android.app.Notification.Builder(this, CHANNEL)
                : new android.app.Notification.Builder(this);
        b.setContentTitle("Almas Remote Host V2.1")
         .setContentText("Экран және басқару LAN арқылы белсенді")
         .setSmallIcon(android.R.drawable.presence_online)
         .setOngoing(true);
        startForeground(77, b.build());
    }

    private DisplayMetrics currentMetrics() {
        DisplayMetrics dm = new DisplayMetrics();
        try {
            Display d = displayManager != null ? displayManager.getDisplay(Display.DEFAULT_DISPLAY) : null;
            if (d != null) d.getRealMetrics(dm);
            else ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(dm);
        } catch (Throwable t) {
            ((WindowManager) getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(dm);
        }
        return dm;
    }

    private int even(int v) {
        v = Math.max(2, v);
        return (v & 1) == 0 ? v : v - 1;
    }

    private int[] outputSize(DisplayMetrics dm) {
        int sw = Math.max(1, dm.widthPixels);
        int sh = Math.max(1, dm.heightPixels);
        float scale = Math.min(1f, 1280f / Math.max(sw, sh));
        return new int[]{even(Math.round(sw * scale)), even(Math.round(sh * scale))};
    }

    private ImageReader createReader(final int width, final int height) {
        ImageReader r = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2);
        r.setOnImageAvailableListener(src -> {
            Image image = null;
            Bitmap full = null;
            Bitmap cropped = null;
            try {
                image = src.acquireLatestImage();
                if (image == null) return;
                Image.Plane plane = image.getPlanes()[0];
                ByteBuffer buffer = plane.getBuffer();
                int pixelStride = plane.getPixelStride();
                int rowStride = plane.getRowStride();
                int rowPadding = rowStride - pixelStride * width;
                int bitmapW = width + Math.max(0, rowPadding / Math.max(1, pixelStride));
                full = Bitmap.createBitmap(bitmapW, height, Bitmap.Config.ARGB_8888);
                full.copyPixelsFromBuffer(buffer);
                cropped = Bitmap.createBitmap(full, 0, 0, width, height);
                ByteArrayOutputStream bos = new ByteArrayOutputStream(160_000);
                cropped.compress(Bitmap.CompressFormat.JPEG, 66, bos);
                latestFrame.set(bos.toByteArray());
            } catch (Throwable ignored) {
            } finally {
                if (cropped != null) try { cropped.recycle(); } catch (Throwable ignored) {}
                if (full != null) try { full.recycle(); } catch (Throwable ignored) {}
                if (image != null) try { image.close(); } catch (Throwable ignored) {}
            }
        }, null);
        return r;
    }

    private void startCapture() {
        DisplayMetrics dm = currentMetrics();
        int[] sz = outputSize(dm);
        captureW = sz[0];
        captureH = sz[1];
        captureDensity = dm.densityDpi;
        reader = createReader(captureW, captureH);
        virtualDisplay = projection.createVirtualDisplay(
                "AlmasRemoteV21", captureW, captureH, captureDensity,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.getSurface(), null, null);
    }

    private void resizeCaptureIfNeeded() {
        synchronized (captureLock) {
            if (!running || virtualDisplay == null) return;
            DisplayMetrics dm = currentMetrics();
            int[] sz = outputSize(dm);
            int nw = sz[0], nh = sz[1];
            if (nw == captureW && nh == captureH && dm.densityDpi == captureDensity) return;

            ImageReader next = createReader(nw, nh);
            ImageReader old = reader;
            try {
                virtualDisplay.resize(nw, nh, dm.densityDpi);
                virtualDisplay.setSurface(next.getSurface());
                reader = next;
                captureW = nw;
                captureH = nh;
                captureDensity = dm.densityDpi;
                latestFrame.set(null);
                if (old != null) {
                    old.setOnImageAvailableListener(null, null);
                    old.close();
                }
            } catch (Throwable t) {
                try { next.close(); } catch (Throwable ignored) {}
            }
        }
    }

    private void startServers() {
        new Thread(this::videoLoop, "video-server-v21").start();
        new Thread(this::controlLoop, "control-server-v21").start();
    }

    private void videoLoop() {
        try (ServerSocket server = new ServerSocket(5050)) {
            server.setReuseAddress(true);
            while (running) {
                try (Socket s = server.accept()) {
                    s.setTcpNoDelay(true);
                    s.setKeepAlive(true);
                    BufferedReader auth = new BufferedReader(new InputStreamReader(s.getInputStream()));
                    String line = auth.readLine();
                    if (!authorized(line)) continue;
                    DataOutputStream out = new DataOutputStream(s.getOutputStream());
                    byte[] last = null;
                    while (running && !s.isClosed()) {
                        byte[] frame = latestFrame.get();
                        if (frame != null && frame != last) {
                            out.writeInt(frame.length);
                            out.write(frame);
                            out.flush();
                            last = frame;
                        }
                        Thread.sleep(30);
                    }
                } catch (Exception ignored) {}
            }
        } catch (Exception ignored) {}
    }

    private void controlLoop() {
        try (ServerSocket server = new ServerSocket(5051)) {
            server.setReuseAddress(true);
            while (running) {
                try (Socket s = server.accept()) {
                    s.setTcpNoDelay(true);
                    s.setKeepAlive(true);
                    BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream()));
                    if (!authorized(in.readLine())) continue;
                    PrintWriter out = new PrintWriter(s.getOutputStream(), true);
                    out.println("READY 21 " + (RemoteAccessibilityService.isReady() ? "1" : "0"));

                    Thread appState = new Thread(() -> {
                        String lastPkg = null;
                        String lastReady = null;
                        while (running && !s.isClosed()) {
                            try {
                                String pkg = RemoteAccessibilityService.getForegroundPackage();
                                String ready = RemoteAccessibilityService.isReady() ? "1" : "0";
                                synchronized (out) {
                                    if (!pkg.equals(lastPkg)) {
                                        out.println("APP " + pkg);
                                        lastPkg = pkg;
                                    }
                                    if (!ready.equals(lastReady)) {
                                        out.println("ACCESS " + ready);
                                        lastReady = ready;
                                    }
                                    if (out.checkError()) break;
                                }
                                Thread.sleep(250);
                            } catch (Exception e) {
                                break;
                            }
                        }
                    }, "app-state-v21");
                    appState.setDaemon(true);
                    appState.start();

                    String line;
                    while (running && (line = in.readLine()) != null) {
                        line = line.trim();
                        if (line.startsWith("PING ")) {
                            synchronized (out) { out.println("PONG " + line.substring(5)); }
                        } else {
                            handleCommand(line);
                        }
                    }
                    RemoteAccessibilityService.cancelAll();
                    restoreOrientationIfNeeded();
                } catch (Exception ignored) {
                    RemoteAccessibilityService.cancelAll();
                    restoreOrientationIfNeeded();
                }
            }
        } catch (Exception ignored) {}
    }

    private boolean authorized(String line) { return line != null && line.equals("PIN " + pin); }

    private void handleCommand(String line) {
        try {
            String[] p = line.split("\\s+");
            if (p.length == 3 && p[0].equals("TAP")) {
                RemoteAccessibilityService.tap(f(p[1]), f(p[2]));
                return;
            }
            if (p.length == 6 && p[0].equals("SWIPE")) {
                RemoteAccessibilityService.swipe(f(p[1]), f(p[2]), f(p[3]), f(p[4]), l(p[5]));
                return;
            }
            if (p.length >= 2 && p[0].equals("JOY")) {
                if (p[1].equals("DOWN") && p.length == 6) {
                    RemoteAccessibilityService.joystickDown(f(p[2]), f(p[3]), f(p[4]), f(p[5]));
                } else if (p[1].equals("MOVE") && p.length == 4) {
                    RemoteAccessibilityService.joystickMove(f(p[2]), f(p[3]));
                } else if (p[1].equals("UP")) {
                    RemoteAccessibilityService.joystickUp();
                }
                return;
            }
            if (p.length >= 2 && p[0].equals("DIRECT")) {
                if (p[1].equals("DOWN") && p.length == 4) {
                    RemoteAccessibilityService.directDown(f(p[2]), f(p[3]));
                } else if (p[1].equals("MOVE") && p.length == 4) {
                    RemoteAccessibilityService.directMove(f(p[2]), f(p[3]));
                } else if (p[1].equals("UP")) {
                    RemoteAccessibilityService.directUp();
                }
                return;
            }
            if (p.length >= 3 && p[0].equals("HOLD")) {
                String id = p[1];
                if (p[2].equals("DOWN") && p.length == 5) {
                    RemoteAccessibilityService.holdDown(id, f(p[3]), f(p[4]));
                } else if (p[2].equals("UP")) {
                    RemoteAccessibilityService.holdUp(id);
                }
                return;
            }
            if (p.length == 5 && p[0].equals("CAM")) {
                RemoteAccessibilityService.cameraDelta(f(p[1]), f(p[2]), f(p[3]), f(p[4]));
                return;
            }
            if (p.length >= 2 && p[0].equals("GLOBAL")) {
                if (p[1].equals("BACK")) RemoteAccessibilityService.globalBack();
                else if (p[1].equals("HOME")) RemoteAccessibilityService.globalHome();
                else if (p[1].equals("RECENTS")) RemoteAccessibilityService.globalRecents();
                return;
            }
            if (p.length >= 2 && p[0].equals("ORIENT")) {
                if (p[1].equals("LANDSCAPE")) forceLandscapeRoot();
                else if (p[1].equals("AUTO")) restoreOrientationIfNeeded();
                return;
            }
            if (p.length == 1 && p[0].equals("CANCEL")) {
                RemoteAccessibilityService.cancelAll();
            }
        } catch (Exception ignored) {}
    }

    private String shell(String command) {
        Process p = null;
        try {
            p = new ProcessBuilder("su", "-c", command).redirectErrorStream(true).start();
            BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()));
            StringBuilder b = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) {
                if (b.length() > 0) b.append('\n');
                b.append(line);
            }
            p.waitFor();
            return b.toString().trim();
        } catch (Throwable ignored) {
            return "";
        } finally {
            if (p != null) try { p.destroy(); } catch (Throwable ignored) {}
        }
    }

    private synchronized void forceLandscapeRoot() {
        if (landscapeForced) return;
        if (!orientationSaved) {
            String a = shell("settings get system accelerometer_rotation");
            String u = shell("settings get system user_rotation");
            if (!a.isEmpty()) savedAccelRotation = a;
            if (!u.isEmpty()) savedUserRotation = u;
            orientationSaved = true;
        }
        shell("settings put system accelerometer_rotation 0; settings put system user_rotation 1");
        landscapeForced = true;
        if (mainHandler != null) mainHandler.postDelayed(resizeRunnable, 250);
    }

    private synchronized void restoreOrientationIfNeeded() {
        if (!orientationSaved) return;
        shell("settings put system accelerometer_rotation " + savedAccelRotation + "; settings put system user_rotation " + savedUserRotation);
        landscapeForced = false;
        orientationSaved = false;
        if (mainHandler != null) mainHandler.postDelayed(resizeRunnable, 250);
    }

    private static float f(String s) { return Float.parseFloat(s); }
    private static long l(String s) { return Long.parseLong(s); }

    @Override
    public void onDestroy() {
        running = false;
        RemoteAccessibilityService.cancelAll();
        restoreOrientationIfNeeded();
        try { if (displayManager != null) displayManager.unregisterDisplayListener(displayListener); } catch (Exception ignored) {}
        try { if (virtualDisplay != null) virtualDisplay.release(); } catch (Exception ignored) {}
        try { if (reader != null) reader.close(); } catch (Exception ignored) {}
        try { if (projection != null) projection.stop(); } catch (Exception ignored) {}
        super.onDestroy();
    }
}
