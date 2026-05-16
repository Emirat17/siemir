"""
Script migrasi cepat — tambah kolom link_spk_ttd dan link_bast_ttd.
Jalankan SEKALI: python migrasi_link_ttd.py
"""
import sqlite3, os, sys

# Cari database
db_path = None
for kandidat in ['instance/database.db', 'database.db', 'app/database.db']:
    if os.path.exists(kandidat):
        db_path = kandidat
        break

if not db_path:
    print("ERROR: Database tidak ditemukan.")
    print("Jalankan dari folder sistem-kontrak-bps/")
    sys.exit(1)

print(f"Database: {db_path}")
conn = sqlite3.connect(db_path)
cur  = conn.cursor()

# Cek dan tambah kolom di tabel kontrak
cur.execute("PRAGMA table_info(kontrak)")
cols_kontrak = [r[1] for r in cur.fetchall()]

if 'link_spk_ttd' not in cols_kontrak:
    cur.execute("ALTER TABLE kontrak ADD COLUMN link_spk_ttd TEXT")
    print("✅ Kolom link_spk_ttd ditambahkan ke tabel kontrak")
else:
    print("   link_spk_ttd sudah ada di tabel kontrak")

# Cek dan tambah kolom di tabel bast
cur.execute("PRAGMA table_info(bast)")
cols_bast = [r[1] for r in cur.fetchall()]

if 'link_bast_ttd' not in cols_bast:
    cur.execute("ALTER TABLE bast ADD COLUMN link_bast_ttd TEXT")
    print("✅ Kolom link_bast_ttd ditambahkan ke tabel bast")
else:
    print("   link_bast_ttd sudah ada di tabel bast")

conn.commit()
conn.close()
print("\n✅ Migrasi selesai. Restart server Flask sekarang.")
