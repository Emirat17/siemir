"""
migrasi_ke_postgresql.py
========================
Pindahkan data dari SQLite lokal ke PostgreSQL di Railway.

Cara pakai:
  1. Jalankan di komputer lokal (bukan di Railway)
  2. Pastikan DATABASE_URL PostgreSQL sudah di-set:
       set DATABASE_URL=postgresql://user:pass@host:5432/dbname   (Windows)
       export DATABASE_URL=postgresql://...                        (Mac/Linux)
  3. Jalankan: python migrasi_ke_postgresql.py
"""

import os, sqlite3, sys

# ── Cek DATABASE_URL ─────────────────────────────────────────────
pg_url = os.environ.get('DATABASE_URL', '')
if not pg_url:
    print("ERROR: Set DATABASE_URL ke URL PostgreSQL Railway terlebih dahulu.")
    sys.exit(1)

if pg_url.startswith('postgres://'):
    pg_url = pg_url.replace('postgres://', 'postgresql://', 1)

# ── Cari SQLite lokal ─────────────────────────────────────────────
sqlite_path = None
for p in ['instance/database.db', 'database.db', 'app/database.db']:
    if os.path.exists(p):
        sqlite_path = p
        break

if not sqlite_path:
    print("ERROR: Database SQLite lokal tidak ditemukan.")
    sys.exit(1)

print(f"SQLite sumber : {sqlite_path}")
print(f"PostgreSQL tujuan: {pg_url[:40]}...")

# ── Buat semua tabel di PostgreSQL via Flask app ──────────────────
print("\n[1/4] Membuat tabel di PostgreSQL...")
os.environ['DATABASE_URL'] = pg_url

from app import create_app, db
app = create_app('production')

with app.app_context():
    db.create_all()
    print("      Tabel berhasil dibuat.")

    # ── Baca data dari SQLite ─────────────────────────────────────
    print("\n[2/4] Membaca data dari SQLite...")
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    TABEL_URUTAN = [
        'user', 'petugas', 'daftar_kegiatan', 'nomor_urut',
        'kontrak', 'kegiatan', 'bast', 'bast_kegiatan',
    ]

    data = {}
    for tbl in TABEL_URUTAN:
        try:
            cur.execute(f"SELECT * FROM {tbl}")
            rows = cur.fetchall()
            data[tbl] = [dict(r) for r in rows]
            print(f"      {tbl}: {len(rows)} baris")
        except sqlite3.OperationalError:
            data[tbl] = []
            print(f"      {tbl}: tidak ada (skip)")

    conn.close()

    # ── Insert ke PostgreSQL ──────────────────────────────────────
    print("\n[3/4] Memasukkan data ke PostgreSQL...")
    from app.models import (User, Petugas, DaftarKegiatan, NomorUrut,
                             Kontrak, Kegiatan, BAST, BASTKegiatan)
    from sqlalchemy import text

    MODEL_MAP = {
        'user':           User,
        'petugas':        Petugas,
        'daftar_kegiatan': DaftarKegiatan,
        'nomor_urut':     NomorUrut,
        'kontrak':        Kontrak,
        'kegiatan':       Kegiatan,
        'bast':           BAST,
        'bast_kegiatan':  BASTKegiatan,
    }

    for tbl in TABEL_URUTAN:
        rows = data.get(tbl, [])
        if not rows:
            continue
        Model = MODEL_MAP[tbl]
        inserted = 0
        for row in rows:
            try:
                obj = Model(**row)
                db.session.merge(obj)   # merge = upsert by PK
                inserted += 1
            except Exception as e:
                print(f"      SKIP baris {row.get('id','?')} di {tbl}: {e}")
        db.session.commit()
        print(f"      {tbl}: {inserted} baris berhasil")

    # ── Reset sequence PostgreSQL ─────────────────────────────────
    print("\n[4/4] Reset sequence ID PostgreSQL...")
    for tbl in ['user','petugas','daftar_kegiatan','nomor_urut',
                 'kontrak','kegiatan','bast','bast_kegiatan']:
        try:
            db.session.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{tbl}','id'), "
                f"COALESCE(MAX(id),0)+1, false) FROM {tbl}"
            ))
        except:
            pass
    db.session.commit()
    print("      Sequence berhasil direset.")

print("\n✅ Migrasi selesai! Data lokal sudah ada di PostgreSQL Railway.")
print("   Buka URL Railway untuk memverifikasi data.")
