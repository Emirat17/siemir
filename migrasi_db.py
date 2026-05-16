"""
Script migrasi: tambah kolom tgl_mulai dan tgl_selesai ke tabel daftar_kegiatan
Jalankan SEKALI jika tidak mau reset database (data lama terjaga).
"""
import sqlite3
import os

# Cari file database
db_path = None
for kandidat in ['instance/database.db', 'database.db', 'app/database.db']:
    if os.path.exists(kandidat):
        db_path = kandidat
        break

if not db_path:
    print("Database tidak ditemukan. Jalankan dari folder sistem-kontrak-bps/")
    exit(1)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Cek kolom yang sudah ada
cur.execute("PRAGMA table_info(daftar_kegiatan)")
kolom_ada = [row[1] for row in cur.fetchall()]
print("Kolom saat ini:", kolom_ada)

# Tambah kolom yang belum ada
if 'tgl_mulai' not in kolom_ada:
    cur.execute("ALTER TABLE daftar_kegiatan ADD COLUMN tgl_mulai DATE")
    print("✅ Kolom tgl_mulai ditambahkan")
else:
    print("   tgl_mulai sudah ada")

if 'tgl_selesai' not in kolom_ada:
    cur.execute("ALTER TABLE daftar_kegiatan ADD COLUMN tgl_selesai DATE")
    print("✅ Kolom tgl_selesai ditambahkan")
else:
    print("   tgl_selesai sudah ada")

if 'bulan_pencairan' not in kolom_ada:
    cur.execute("ALTER TABLE daftar_kegiatan ADD COLUMN bulan_pencairan INTEGER")
    print("✅ Kolom bulan_pencairan ditambahkan")
else:
    print("   bulan_pencairan sudah ada")

# Cek tabel BAST
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bast'")
if not cur.fetchone():
    print("\nMembuat tabel bast dan bast_kegiatan...")

# Cek dan tambah tabel bast_kegiatan jika belum ada
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bast_kegiatan'")
if not cur.fetchone():
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bast (
            id INTEGER PRIMARY KEY,
            kontrak_id INTEGER NOT NULL REFERENCES kontrak(id),
            nomor_bast VARCHAR(100),
            bulan_bast INTEGER NOT NULL,
            tahun_bast INTEGER NOT NULL,
            tanggal_bast DATE,
            total_honor NUMERIC(15,2) DEFAULT 0,
            dibuat DATETIME
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bast_kegiatan (
            id INTEGER PRIMARY KEY,
            bast_id INTEGER NOT NULL REFERENCES bast(id),
            kegiatan_id INTEGER NOT NULL REFERENCES kegiatan(id)
        )
    """)
    print("✅ Tabel bast dan bast_kegiatan dibuat")
else:
    print("   Tabel bast sudah ada")

conn.commit()
conn.close()
print("\n✅ Migrasi selesai — database diperbarui tanpa menghapus data.")
