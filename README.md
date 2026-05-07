# Sistem Kontrak Petugas — BPS Kabupaten Kepulauan Meranti

Aplikasi web berbasis Flask (Python) untuk otomatisasi pembuatan
dokumen SPK dan BAST mitra rutin bulanan BPS.

---

## Cara Menjalankan

### 1. Pastikan Python sudah terinstall
```
python --version   # minimal Python 3.9
```

### 2. Buat virtual environment
```bash
python -m venv venv
```

Aktifkan virtual environment:
- Windows : `venv\Scripts\activate`
- Mac/Linux: `source venv/bin/activate`

### 3. Install semua library
```bash
pip install -r requirements.txt
```

### 4. Jalankan aplikasi
```bash
python run.py
```

### 5. Buka di browser
```
http://localhost:5000
```

---

## Struktur Folder

```
sistem-kontrak-bps/
├── app/
│   ├── __init__.py      ← Inisialisasi Flask & database
│   ├── models.py        ← Struktur tabel database
│   ├── routes.py        ← URL dan logika halaman
│   ├── utils.py         ← Generate PDF & hitung honor
│   ├── templates/       ← File HTML halaman
│   └── static/          ← CSS, JS, gambar
├── config.py            ← Konfigurasi aplikasi
├── run.py               ← Jalankan server
├── requirements.txt     ← Daftar library
└── database.db          ← File database (dibuat otomatis)
```

---

## Tabel Database

| Tabel     | Fungsi                                      |
|-----------|---------------------------------------------|
| petugas   | Data identitas mitra/petugas BPS            |
| kontrak   | Header surat SPK per bulan per petugas      |
| kegiatan  | Lampiran rincian kegiatan per kontrak       |

---

## Tahap Pengembangan

- [x] Tahap 1 — Analisis kebutuhan & perancangan basis data
- [ ] Tahap 2 — Backend & database (CRUD lengkap)
- [ ] Tahap 3 — Antarmuka frontend (form input kegiatan)
- [ ] Tahap 4 — Generate dokumen SPK & BAST (PDF)
- [ ] Tahap 5 — Uji coba & perbaikan
- [ ] Tahap 6 — Deployment

---

Pelatihan Fungsional Pranata Komputer Kategori Keahlian Angkatan II Tahun 2026
