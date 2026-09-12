from pathlib import Path
import re

# Apply after V2.3 root/video patch and V2.4 screen-share patch.

# ---- Host video quality: native display size, JPEG 88, keep 25 FPS from V2.3 ----
p = Path('app/src/main/java/kz/almas/remote/RemoteService.java')
s = p.read_text(encoding='utf-8')

old_size = '''    private int[] outputSize(DisplayMetrics dm) {
        int sw = Math.max(1, dm.widthPixels);
        int sh = Math.max(1, dm.heightPixels);
        float scale = Math.min(1f, 1280f / Math.max(sw, sh));
        return new int[]{even(Math.round(sw * scale)), even(Math.round(sh * scale))};
    }
'''
new_size = '''    private int[] outputSize(DisplayMetrics dm) {
        // V2.7 HQ: capture the phone's real display resolution. No artificial 1280px downscale.
        int sw = Math.max(2, dm.widthPixels);
        int sh = Math.max(2, dm.heightPixels);
        return new int[]{even(sw), even(sh)};
    }
'''
if old_size not in s:
    raise SystemExit('outputSize block not found')
s = s.replace(old_size, new_size, 1)

if 'cropped.compress(Bitmap.CompressFormat.JPEG, 66, bos);' not in s:
    raise SystemExit('JPEG 66 line not found')
s = s.replace('ByteArrayOutputStream bos = new ByteArrayOutputStream(160_000);',
              'ByteArrayOutputStream bos = new ByteArrayOutputStream(320_000);', 1)
s = s.replace('cropped.compress(Bitmap.CompressFormat.JPEG, 66, bos);',
              'cropped.compress(Bitmap.CompressFormat.JPEG, 88, bos);', 1)

s = s.replace('Almas Remote Host V2.3', 'Almas Remote Host V2.7 HQ')
s = s.replace('"AlmasRemoteV23"', '"AlmasRemoteV27HQ"')
s = s.replace('"video-server-v23"', '"video-server-v27-hq"')
s = s.replace('"control-server-v23"', '"control-server-v27-hq"')
s = s.replace('"app-state-v23"', '"app-state-v27-hq"')

p.write_text(s, encoding='utf-8')

# ---- UI title only; all V2.4 permission + V2.3 root/uinput logic stays intact ----
p = Path('app/src/main/java/kz/almas/remote/MainActivity.java')
s = p.read_text(encoding='utf-8')
s = s.replace('ALMAS REMOTE HOST V2.4', 'ALMAS REMOTE HOST V2.7 HQ')
p.write_text(s, encoding='utf-8')

# ---- Package version. Preserve the existing signed non-debuggable Release build settings. ----
p = Path('app/build.gradle')
s = p.read_text(encoding='utf-8')
s = re.sub(r'versionCode\s+\d+', 'versionCode 7', s, count=1)
s = re.sub(r"versionName\s+'[^']+'", "versionName '2.7'", s, count=1)
p.write_text(s, encoding='utf-8')

print('V2.7 HQ patch applied: native resolution + JPEG 88 + existing 25 FPS')
