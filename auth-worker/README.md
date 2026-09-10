# almas projekt — шақыру сервері

Бұл Worker:

- Telegram әкімшісінен `/new Player_Name` пәрменін қабылдайды;
- AES-GCM арқылы шифрланған бір реттік `.almasinvite` файл жасайды;
- файлды тек бір құрылғыда қолдануға рұқсат етеді;
- парольді PBKDF2 хэші ретінде сақтайды;
- 5 қате парольден кейін кіруді 5 минутқа тоқтатады;
- телефон құлпы және пароль арқылы қайта кіруді қолдайды.

## Алғашқы баптау

PowerShell ішінде:

1. `npx wrangler login`
2. `npx wrangler d1 create almas-auth`
3. `wrangler.toml.example` файлын `wrangler.toml` деп көшіріп, шыққан `database_id` мәнін жазыңыз.
4. `powershell -ExecutionPolicy Bypass -File .\SETUP_BOT.ps1`
5. Telegram-дағы жаңа ботқа `/start` жіберіңіз.
6. Скрипт сұрағанда BotFather берген токенді енгізіңіз. Скрипт соңғы хабарламадан Telegram ID-ді өзі табады; табылмаса ғана ID-ді қолмен сұрайды.
7. Скрипт жариялаған Worker URL-ін түбірдегі `app-config.js` файлының `apiBase` жолына жазыңыз.

Токен экранда көрсетілмейді, файлға сақталмайды және GitHub-қа жіберілмейді.
