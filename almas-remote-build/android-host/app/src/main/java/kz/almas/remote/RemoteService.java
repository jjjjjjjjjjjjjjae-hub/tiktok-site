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
import android.os.IBinder;
import android.util.DisplayMetrics;
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
    private final AtomicReference<byte[]> latestFrame = new AtomicReference<>();

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) return START_NOT_STICKY;
        pin = intent.getStringExtra("pin");
        createNotification();
        if (running) return START_STICKY;
        running = true;

        int resultCode = intent.getIntExtra("resultCode", 0);
        Intent data = intent.getParcelableExtra("projectionData");
        MediaProjectionManager mgr = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        projection = mgr.getMediaProjection(resultCode, data);
        projection.registerCallback(new MediaProjection.Callback() {
            @Override public void onStop() { stopSelf(); }
        }, new android.os.Handler(getMainLooper()));
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
        b.setContentTitle("Almas Remote Host V2")
         .setContentText("Экран және басқару LAN арқылы белсенді")
         .setSmallIcon(android.R.drawable.presence_online)
         .setOngoing(true);
        startForeground(77, b.build());
    }

    private void startCapture() {
        WindowManager wm = (WindowManager) getSystemService(WINDOW_SERVICE);
        DisplayMetrics dm = new DisplayMetrics();
        wm.getDefaultDisplay().getRealMetrics(dm);
        int screenW = dm.widthPixels, screenH = dm.heightPixels;
        int outW = Math.min(screenW, 1280);
        int outH = Math.max(1, Math.round(screenH * (outW / (float) screenW)));
        if ((outW & 1) == 1) outW--;
        if ((outH & 1) == 1) outH--;
        final int captureW = outW;
        final int captureH = outH;

        reader = ImageReader.newInstance(captureW, captureH, PixelFormat.RGBA_8888, 2);
        reader.setOnImageAvailableListener(r -> {
            Image image = null;
            try {
                image = r.acquireLatestImage();
                if (image == null) return;
                Image.Plane plane = image.getPlanes()[0];
                ByteBuffer buffer = plane.getBuffer();
                int pixelStride = plane.getPixelStride();
                int rowStride = plane.getRowStride();
                int rowPadding = rowStride - pixelStride * captureW;
                Bitmap full = Bitmap.createBitmap(captureW + rowPadding / pixelStride, captureH, Bitmap.Config.ARGB_8888);
                full.copyPixelsFromBuffer(buffer);
                Bitmap cropped = Bitmap.createBitmap(full, 0, 0, captureW, captureH);
                ByteArrayOutputStream bos = new ByteArrayOutputStream(160_000);
                cropped.compress(Bitmap.CompressFormat.JPEG, 66, bos);
                latestFrame.set(bos.toByteArray());
                cropped.recycle();
                full.recycle();
            } catch (Throwable ignored) {
            } finally {
                if (image != null) image.close();
            }
        }, null);

        virtualDisplay = projection.createVirtualDisplay(
                "AlmasRemoteV2", captureW, captureH, dm.densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.getSurface(), null, null);
    }

    private void startServers() {
        new Thread(this::videoLoop, "video-server-v2").start();
        new Thread(this::controlLoop, "control-server-v2").start();
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
                    out.println("READY 2 " + (RemoteAccessibilityService.isReady() ? "1" : "0"));

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
                    }, "app-state-v2");
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
                } catch (Exception ignored) {
                    RemoteAccessibilityService.cancelAll();
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
            if (p.length == 1 && p[0].equals("CANCEL")) {
                RemoteAccessibilityService.cancelAll();
            }
        } catch (Exception ignored) {}
    }

    private static float f(String s) { return Float.parseFloat(s); }
    private static long l(String s) { return Long.parseLong(s); }

    @Override
    public void onDestroy() {
        running = false;
        RemoteAccessibilityService.cancelAll();
        try { if (virtualDisplay != null) virtualDisplay.release(); } catch (Exception ignored) {}
        try { if (reader != null) reader.close(); } catch (Exception ignored) {}
        try { if (projection != null) projection.stop(); } catch (Exception ignored) {}
        super.onDestroy();
    }
}
