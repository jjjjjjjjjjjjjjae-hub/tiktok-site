from pathlib import Path

# Apply after patch_v23_android.py.
p = Path('app/src/main/java/kz/almas/remote/MainActivity.java')
s = p.read_text(encoding='utf-8')

s = s.replace('ALMAS REMOTE HOST V2.3', 'ALMAS REMOTE HOST V2.4')

# Add a guard so the automatic MediaProjection dialog is only requested once
# per Activity instance. The manual button remains available for retry.
old_field = '''    private TextView rootStatus;\n    private String pin;\n'''
new_field = '''    private TextView rootStatus;\n    private String pin;\n    private boolean autoProjectionRequested;\n'''
if old_field not in s:
    raise SystemExit('MainActivity field block not found')
s = s.replace(old_field, new_field, 1)

old_build = '''        buildUi();\n    }\n'''
new_build = '''        buildUi();\n\n        // Ask for Android screen-capture permission automatically on first launch.\n        // Keep the explicit button below so the user can retry after cancelling.\n        if (savedInstanceState == null && !autoProjectionRequested) {\n            autoProjectionRequested = true;\n            status.setText("Экранды бөлісуге рұқсат сұралады...");\n            status.postDelayed(() -> {\n                if (!isFinishing() && !isDestroyed()) requestProjection();\n            }, 700);\n        }\n    }\n'''
if old_build not in s:
    raise SystemExit('MainActivity buildUi tail not found')
s = s.replace(old_build, new_build, 1)

s = s.replace('Button start = button("2. Экранды бөлісуді бастау");',
              'Button start = button("2. Экранды бөлісуге рұқсат сұрау / қайта сұрау");')

p.write_text(s, encoding='utf-8')

# Version V2.4.
p = Path('app/build.gradle')
s = p.read_text(encoding='utf-8')
s = s.replace("versionCode 3", "versionCode 4")
s = s.replace("versionName '2.2'", "versionName '2.4'")
p.write_text(s, encoding='utf-8')

print('V2.4 automatic MediaProjection permission patch applied')
