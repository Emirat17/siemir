# PANDUAN DEPLOY SIEMIR KE RAILWAY
# Berikan file ini ke Claude Code sebagai referensi

## KONTEKS PROYEK
- Aplikasi: SIEMIR (Sistem Entri Mitra Rutinan)
- Stack: Python Flask + SQLAlchemy + Bootstrap 5
- Database lokal: SQLite di instance/database.db
- Target: Railway.app dengan PostgreSQL
- Folder proyek: sistem-kontrak-bps/

## FILE YANG SUDAH DISIAPKAN (dari sesi Claude.ai)
- requirements.txt   → tambah gunicorn + psycopg2-binary
- Procfile           → perintah gunicorn untuk Railway
- railway.toml       → konfigurasi Railway
- .gitignore         → exclude database.db dan .env
- config.py          → auto-switch SQLite/PostgreSQL via DATABASE_URL
- migrasi_ke_postgresql.py → pindah data lokal ke PostgreSQL

## TUGAS UNTUK CLAUDE CODE

### Tahap 1 - Siapkan file deploy
1. Salin requirements.txt, Procfile, railway.toml, .gitignore, config.py
   ke dalam folder sistem-kontrak-bps/
2. Update app/__init__.py untuk menggunakan config.py:
   - from config import config
   - app.config.from_object(config[os.environ.get('FLASK_ENV','production')])
3. Pastikan run.py menggunakan PORT dari environment:
   - port = int(os.environ.get('PORT', 5000))
   - app.run(host='0.0.0.0', port=port, debug=False)

### Tahap 2 - Push ke GitHub
1. git init (jika belum)
2. git remote add origin <URL_REPO_GITHUB>
3. git add .
4. git commit -m "Initial commit - SIEMIR ready for Railway deploy"
5. git push -u origin main

### Tahap 3 - Deploy di Railway
1. Login ke railway.app
2. New Project → Deploy from GitHub repo → pilih repo SIEMIR
3. Add Plugin → PostgreSQL (Railway otomatis set DATABASE_URL)
4. Set Environment Variables:
   - SECRET_KEY = [string acak panjang, minimal 32 karakter]
   - FLASK_ENV = production
5. Deploy → tunggu build selesai

### Tahap 4 - Inisialisasi database di Railway
Setelah deploy berhasil, buka Railway Shell dan jalankan:
  python -c "from app import create_app, db; app=create_app(); 
             ctx=app.app_context(); ctx.push(); db.create_all(); print('OK')"

### Tahap 5 - Migrasi data lokal (opsional)
Jika ingin pindahkan data dari SQLite lokal:
1. Ambil DATABASE_URL dari Railway dashboard (tab Variables)
2. Di komputer lokal:
   set DATABASE_URL=postgresql://... (Windows)
   export DATABASE_URL=postgresql://... (Mac/Linux)
3. python migrasi_ke_postgresql.py

### Tahap 6 - Verifikasi
1. Buka URL Railway yang diberikan
2. Login dengan admin/admin123
3. Ganti password segera
4. Test semua fitur utama

## CATATAN PENTING
- Template dokumen Word (DOKUMEN_SPK.docx, DOKUMEN_BAST.docx) harus ikut
  di-commit ke GitHub di dalam folder app/templates/
- Template Excel di templates_excel/ juga harus ikut
- JANGAN commit file .env atau database.db
- Setelah deploy berhasil, tambahkan semua akun user via Manajemen Pengguna
