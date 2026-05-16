"""
Script reset nomor SPK/BAST.
Jalankan ini jika nomor SPK/BAST tidak dimulai dari 1.
Data kontrak dan kegiatan TIDAK dihapus — hanya nomor yang diperbarui.

Cara pakai:
    python reset_nomor.py
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
    print("Jalankan script ini dari folder sistem-kontrak-bps/")
    sys.exit(1)

print(f"Database ditemukan: {db_path}")

FUNGSI_KODE = {
    'Umum': '14.101', 'Sosial': '14.102', 'Produksi': '14.103',
    'Distribusi': '14.104', 'Nerwilis': '14.105', 'IPDS': '14.106',
}

conn = sqlite3.connect(db_path)
cur  = conn.cursor()

# Ambil semua kontrak urut berdasarkan id
cur.execute("SELECT id, kode_fungsi, nama_fungsi, tahun FROM kontrak ORDER BY id ASC")
kontrak_list = cur.fetchall()

print(f"\nDitemukan {len(kontrak_list)} kontrak.")
print("Mereset nomor SPK dan BAST mulai dari 1...\n")

for i, (kid, kode_fungsi, nama_fungsi, tahun) in enumerate(kontrak_list, 1):
    # Tentukan kode fungsi
    kf = kode_fungsi or FUNGSI_KODE.get(nama_fungsi or '', '14.101')
    
    nomor_spk  = f"PK-{i}/{kf}/VS.330/{tahun}"
    nomor_bast = f"BAST-{i}/{kf}/VS.430/{tahun}"
    
    cur.execute(
        "UPDATE kontrak SET nomor_spk=?, nomor_bast=? WHERE id=?",
        (nomor_spk, nomor_bast, kid)
    )
    print(f"  Kontrak ID {kid}: {nomor_spk} | {nomor_bast}")

# Reset counter NomorUrut ke jumlah kontrak yang ada
total = len(kontrak_list)
cur.execute("SELECT id FROM nomor_urut WHERE jenis='SPK'")
row = cur.fetchone()
if row:
    cur.execute("UPDATE nomor_urut SET terakhir=? WHERE jenis='SPK'", (total,))
else:
    cur.execute("INSERT INTO nomor_urut (jenis, terakhir) VALUES ('SPK', ?)", (total,))
print(f"\nCounter SPK diset ke {total}")

# Hitung total BAST yang ada
cur.execute("SELECT COUNT(*) FROM bast")
total_bast = cur.fetchone()[0]
cur.execute("SELECT id FROM nomor_urut WHERE jenis='BAST'")
row_b = cur.fetchone()
if row_b:
    cur.execute("UPDATE nomor_urut SET terakhir=? WHERE jenis='BAST'", (total_bast,))
else:
    cur.execute("INSERT INTO nomor_urut (jenis, terakhir) VALUES ('BAST', ?)", (total_bast,))
print(f"Counter BAST diset ke {total_bast}")

conn.commit()
conn.close()

print(f"\n✅ Selesai! {total} kontrak dinomori ulang dari PK-1 s.d PK-{total}.")
print("Restart server Flask setelah ini.")
