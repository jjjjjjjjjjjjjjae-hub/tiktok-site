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
        b.setContentTitle("Almas Remote Host")
         .setContentText("Экран LAN арқылы бөлісіліп тұр")
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
                ByteArrayOutputStream bos = new ByteArrayOutputStream(150_000);
                cropped.compress(Bitmap.CompressFormat.JPEG, 62, bos);
                latestFrame.set(bos.toByteArray());
                cropped.recycle();
                full.recycle();
            } catch (Throwable ignored) {
            } finally {
                if (image != null) image.close();
            }
        }, null);

        virtualDisplay = projection.createVirtualDisplay(
                "AlmasRemote", captureW, captureH, dm.densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                reader.getSurface(), null, null);
    }

    private void startServers() {
        new Thread(this::videoLoop, "video-server").start();
        new Thread(this::controlLoop, "control-server").start();
    }

    private void videoLoop() {
        try (ServerSocket server = new ServerSocket(5050)) {
            server.setReuseAddress(true);
            while (running) {
                try (Socket s = server.accept()) {
                    s.setTcpNoDelay(true);
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
                        Thread.sleep(35);
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
                    BufferedReader in = new BufferedReader(new InputStreamReader(s.getInputStream()));
                    if (!authorized(in.readLine())) continue;
                    PrintWriter out = new PrintWriter(s.getOutputStream(), true);

                    Thread appState = new Thread(() -> {
                        String lastPkg = null;
                        while (running && !s.isClosed()) {
                            try {
                                String pkg = RemoteAccessibilityService.getForegroundPackage();
                                if (!pkg.equals(lastPkg)) {
                                    out.println("APP " + pkg);
                                    if (out.checkError()) break;
                                    lastPkg = pkg;
                                }
                                Thread.sleep(250);
                            } catch (Exception e) {
                                break;
                            }
                        }
                    }, "app-state");
                    appState.setDaemon(true);
                    appState.start();

                    String line;
                    while (running && (line = in.readLine()) != null) handleCommand(line.trim());
                } catch (Exception ignored) {}
            }
        } catch (Exception ignored) {}
    }

    private boolean authorized(String line) { return line != null && line.equals("PIN " + pin); }

    private void handleCommand(String line) {
        try {
            String[] p = line.split("\\s+");
            if (p.length == 3 && p[0].equals("TAP")) {
                RemoteAccessibilityService.tap(Float.parseFloat(p[1]), Float.parseFloat(p[2]));
            } else if (p.length == 6 && p[0].equals("SWIPE")) {
                RemoteAccessibilityService.swipe(
                        Float.parseFloat(p[1]), Float.parseFloat(p[2]),
                        Float.parseFloat(p[3]), Float.parseFloat(p[4]),
                        Long.parseLong(p[5]));
            } else if (p.length == 10 && p[0].equals("DUALSWIPE")) {
                RemoteAccessibilityService.dualSwipe(
                        Float.parseFloat(p[1]), Float.parseFloat(p[2]),
                        Float.parseFloat(p[3]), Float.parseFloat(p[4]),
                        Float.parseFloat(p[5]), Float.parseFloat(p[6]),
                        Float.parseFloat(p[7]), Float.parseFloat(p[8]),
                        Long.parseLong(p[9]));
            }
        } catch (Exception ignored) {}
    }

    @Override
    public void onDestroy() {
        running = false;
        try { if (virtualDisplay != null) virtualDisplay.release(); } catch (Exception ignored) {}
        try { if (reader != null) reader.close(); } catch (Exception ignored) {}
        try { if (projection != null) projection.stop(); } catch (Exception ignored) {}
        super.onDestroy();
    }
}
