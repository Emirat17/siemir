"""
Script LOKAL — sisip screenshot Aplikasi FASIH ke dokumen BAPP SE2026.

Dijalankan di komputer sendiri (bukan di server Railway). Untuk tiap petugas:
generate BAPP + unduh screenshot dari Google Drive + sisipkan ke dokumen,
lalu simpan ke folder OUTPUT.

LANGKAH PAKAI
=============
1. Install sekali:  py -m pip install requests python-docx pillow
2. Login ke website, lalu buka & SIMPAN dua file JSON ini:
     https://siemir.up.railway.app/se2026/ppl/bapp-data.json   -> simpan sebagai ppl.json
     https://siemir.up.railway.app/se2026/pml/bapp-data.json   -> simpan sebagai pml.json
   Letakkan kedua file di folder yang sama dengan script ini (atau sesuaikan path di KONFIGURASI).
3. Jalankan:  py tools/sisip_screenshot_bapp.py
4. Hasil ada di folder OUTPUT (lihat KONFIGURASI). Nama file = nomor + nama petugas.

Catatan: file screenshot di Drive HARUS 'Anyone with the link can view'.
"""
import csv
import io
import math
import os
import re
import sys
import importlib.util
from datetime import date

import requests
from docx import Document
from docx.shared import Inches
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ─────────────────────────── KONFIGURASI ────────────────────────────
HERE      = os.path.dirname(os.path.abspath(__file__))
REPO      = os.path.dirname(HERE)                       # folder sistem-kontrak-bps
TEMPLATE  = os.path.join(REPO, 'app', 'templates')

TERMIN    = 1                                           # 1 atau 2
TANGGAL   = date(2026, 7, 15) if TERMIN == 1 else date(2026, 9, 1)

PPL_JSON  = os.path.join(HERE, 'ppl.json')
PML_JSON  = os.path.join(HERE, 'pml.json')
OUTPUT    = os.path.join(HERE, f'BAPP_Termin{TERMIN}_dengan_screenshot')

# Link spreadsheet (ekspor CSV). gid PML dari URL yang diberikan.
SHEET = {
    'PPL': ('https://docs.google.com/spreadsheets/d/1p4WgySvJDvMErG21S8aBPe95PW7oN8uFanv0_4kytR4/export?format=csv',
            'Pendataan'),   # substring header kolom nama
    'PML': ('https://docs.google.com/spreadsheets/d/1CpsYjv-Y_LRLXgm_zLRAy6Bmf60Pdz3eraQFObh0vNs/export?format=csv&gid=1300583351',
            'Pemeriksa'),
}

TPL_BAPP = {
    ('PPL', 1): 'Template_BAPP termin I untuk Petugas Lapangan final.docx',
    ('PPL', 2): 'Template_BAPP termin II untuk Petugas Lapangan final .docx',
    ('PML', 1): 'Template_BAPP termin I untuk Pemeriksa Lapangan Final.docx',
    ('PML', 2): 'Template_BAPP termin II untuk Pemeriksa Lapangan Final.docx',
}

IMG_PER_PAGE  = 6        # jumlah foto per halaman lampiran
RESERVE_JUDUL = 1.5      # inci ruang untuk judul di halaman pertama
GAP           = 0.08     # inci jarak antar sel
# ─────────────────────────────────────────────────────────────────────


def load_docgen():
    spec = importlib.util.spec_from_file_location(
        'docgen', os.path.join(REPO, 'app', 'doc_generator.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def norm(nama):
    return re.sub(r'\s+', ' ', (nama or '').strip()).upper()


def baca_sheet(url, nama_sub):
    """Kembalikan {nama_norm: [drive_file_id, ...]} dari sheet."""
    r = requests.get(url, allow_redirects=True, timeout=60)
    r.raise_for_status()
    rows = list(csv.reader(io.StringIO(r.text)))
    if not rows:
        return {}
    hdr = rows[0]
    # kolom nama: header memuat substring (mis. 'Pendataan'/'Pemeriksa')
    col_nama = next((i for i, h in enumerate(hdr)
                     if 'Nama' in h and nama_sub in h), 1)
    # kolom screenshot: header memuat 'creenshoot'
    col_ss = [i for i, h in enumerate(hdr) if 'creenshoot' in h]

    hasil = {}
    for row in rows[1:]:
        if col_nama >= len(row):
            continue
        nama = row[col_nama].strip()
        if not nama:
            continue
        ids = []
        for ci in col_ss:
            if ci < len(row):
                for fid in re.findall(r'[?&]id=([A-Za-z0-9_-]+)', row[ci]):
                    if fid not in ids:
                        ids.append(fid)
        hasil[norm(nama)] = ids
    return hasil


def unduh_gambar(session, fid):
    """Unduh 1 file Drive publik -> bytes gambar (PNG/JPG), atau None."""
    url = f'https://drive.google.com/uc?export=download&id={fid}'
    r = session.get(url, timeout=120)
    ct = r.headers.get('content-type', '')
    if 'image' in ct:
        return r.content
    if 'text/html' in ct:  # file besar -> perlu token konfirmasi
        m = re.search(r'confirm=([0-9A-Za-z_-]+)', r.text)
        if m:
            r2 = session.get(url + f'&confirm={m.group(1)}', timeout=180)
            if 'image' in r2.headers.get('content-type', ''):
                return r2.content
    return None


def sebagai_png(data):
    """Pastikan bytes bisa dipakai python-docx; konversi bila perlu (Pillow)."""
    try:
        Document().add_paragraph().add_run().add_picture(io.BytesIO(data))
        return data
    except Exception:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data)).convert('RGB')
            buf = io.BytesIO(); im.save(buf, format='PNG')
            return buf.getvalue()
        except Exception:
            return None


def _section_usable(doc, heading_p):
    """Lebar & tinggi area cetak (inci) untuk section tempat heading berada."""
    body = doc.element.body
    els = list(body)
    hi = els.index(heading_p)
    sect = None
    for el in els[hi:]:
        if el.tag == qn('w:p'):
            pPr = el.find(qn('w:pPr'))
            if pPr is not None:
                sp = pPr.find(qn('w:sectPr'))
                if sp is not None:
                    sect = sp; break
    if sect is None:
        sect = body.find(qn('w:sectPr'))
    pg = sect.find(qn('w:pgSz')); mar = sect.find(qn('w:pgMar'))
    def g(el, a, d=1440):
        try: return int(el.get(qn(a)))
        except (TypeError, ValueError, AttributeError): return d
    w = g(pg, 'w:w', 11906); h = g(pg, 'w:h', 16838)
    ml = g(mar, 'w:left'); mr = g(mar, 'w:right')
    mt = g(mar, 'w:top'); mb = g(mar, 'w:bottom')
    return (w - ml - mr) / 1440.0, (h - mt - mb) / 1440.0


def _ukuran_gambar(data, cell_w, cell_h):
    """Lebar tampil (inci) agar gambar muat dalam sel cell_w x cell_h."""
    try:
        from PIL import Image
        iw, ih = Image.open(io.BytesIO(data)).size
        aspect = iw / ih if ih else 1.0
    except Exception:
        aspect = 0.46   # asumsi screenshot HP (portrait)
    w = min(cell_w, cell_h * aspect)
    return max(w, 0.5)


def _grid_terbaik(uw, uh, n=IMG_PER_PAGE, aspect=0.46):
    """Pilih (kolom, baris) untuk n foto/halaman yang memberi foto TERBESAR
    pada area uw x uh (memperhitungkan ruang judul)."""
    avail_h = max(uh - RESERVE_JUDUL, 1.0)
    pilihan = []
    c = 1
    while c <= n:
        if n % c == 0:
            pilihan.append((c, n // c))
        c += 1
    best, best_w = (n, 1), 0
    for c, r in pilihan:
        cw = uw / c - GAP
        ch = avail_h / r - GAP
        iw = min(cw, ch * aspect)
        if iw > best_w:
            best_w, best = iw, (c, r)
    return best


def sisip_gambar(doc, imgs):
    """Sisipkan foto setelah heading 'Screenshoot Aplikasi Fasih' — NCOLxNROW
    (6) per halaman, judul + 6 foto pertama tetap satu halaman."""
    if not imgs:
        return 0
    heading = next((p for p in doc.paragraphs
                    if 'Screenshoot Aplikasi Fasih' in p.text), None)
    if heading is None:
        return 0
    hp = heading._p
    body = doc.element.body
    # hapus tabel placeholder lama setelah heading
    els = list(body)
    old_tbl = next((e for e in els[els.index(hp) + 1:] if e.tag == qn('w:tbl')), None)
    if old_tbl is not None and old_tbl.getparent() is not None:
        old_tbl.getparent().remove(old_tbl)
    # judul menempel dengan tabel foto pertama
    heading.paragraph_format.keep_with_next = True

    uw, uh = _section_usable(doc, hp)
    ncol, nrow = _grid_terbaik(uw, uh)
    per_page = ncol * nrow
    cell_w = uw / ncol - GAP
    cell_h = (uh - RESERVE_JUDUL) / nrow - GAP   # sisakan ruang judul → muat 1 halaman

    anchor = hp
    for pi in range(0, len(imgs), per_page):
        chunk = imgs[pi:pi + per_page]
        if pi > 0:   # page break sebelum halaman foto berikutnya
            brk = OxmlElement('w:p'); run = OxmlElement('w:r')
            br = OxmlElement('w:br'); br.set(qn('w:type'), 'page')
            run.append(br); brk.append(run)
            anchor.addnext(brk); anchor = brk
        nr = math.ceil(len(chunk) / ncol)
        tbl = doc.add_table(rows=nr, cols=ncol)
        tbl.autofit = False
        for k, data in enumerate(chunk):
            cell = tbl.rows[k // ncol].cells[k % ncol]
            p0 = cell.paragraphs[0]
            p0.alignment = WD_ALIGN_PARAGRAPH.CENTER
            try:
                p0.add_run().add_picture(io.BytesIO(data),
                                         width=Inches(_ukuran_gambar(data, cell_w, cell_h)))
            except Exception as e:
                print(f'      ! gagal sisip 1 foto: {e}')
        anchor.addnext(tbl._tbl); anchor = tbl._tbl
    return len(imgs)


def proses(dg, jenis, session):
    import json
    jpath = PPL_JSON if jenis == 'PPL' else PML_JSON
    if not os.path.exists(jpath):
        print(f'[{jenis}] LEWATI — file {os.path.basename(jpath)} tidak ada.')
        return
    petugas = json.load(open(jpath, encoding='utf-8'))
    url, nama_sub = SHEET[jenis]
    ss_map = baca_sheet(url, nama_sub)
    tpl = os.path.join(TEMPLATE, TPL_BAPP[(jenis, TERMIN)])
    outdir = os.path.join(OUTPUT, jenis)
    os.makedirs(outdir, exist_ok=True)

    ok = tanpa_ss = 0
    baris_ringkasan = []
    print(f'\n[{jenis}] {len(petugas)} petugas | {len(ss_map)} nama di sheet')
    for k in petugas:
        nama = k['nama']
        ids = ss_map.get(norm(nama), [])
        # unduh screenshot
        imgs = []
        for fid in ids:
            b = unduh_gambar(session, fid)
            if b:
                b = sebagai_png(b)
            if b:
                imgs.append(b)
        # generate BAPP
        data = dict(k); data['tanggal'] = TANGGAL
        docx_bytes = dg.generate_bapp_se2026(data, tpl)
        doc = Document(io.BytesIO(docx_bytes))
        n = sisip_gambar(doc, imgs)
        aman = re.sub(r'[^A-Za-z0-9 _-]', '', nama).strip().replace(' ', '_')
        doc.save(os.path.join(outdir, f"{k['nomor']}_{aman}.docx"))
        if n:
            ok += 1
        else:
            tanpa_ss += 1
        ket = '' if ids else 'nama tidak ada di sheet'
        if ids and n < len(ids):
            ket = f'{len(ids)-n} foto gagal diunduh'
        print(f"   {k['nomor']} {nama:<28} : {n} foto"
              + (f'  ({ket})' if ket else ''))
        baris_ringkasan.append(f"{k['nomor']}\t{nama}\t{n} foto\t{ket}")

    # tulis RINGKASAN per jenis
    ring = os.path.join(OUTPUT, f'RINGKASAN_{jenis}.txt')
    with open(ring, 'w', encoding='utf-8') as f:
        f.write(f'RINGKASAN SISIP SCREENSHOT BAPP — {jenis} (Termin {TERMIN})\n')
        f.write(f'Total {len(petugas)} petugas | {ok} dgn foto | {tanpa_ss} tanpa foto\n')
        f.write('Nomor\tNama\tJumlah Foto\tKeterangan\n')
        f.write('\n'.join(baris_ringkasan) + '\n')
    print(f'[{jenis}] selesai. {ok} dgn foto, {tanpa_ss} tanpa foto. '
          f'-> {outdir}\n           ringkasan: {ring}')


def main():
    dg = load_docgen()
    os.makedirs(OUTPUT, exist_ok=True)
    session = requests.Session()
    for jenis in ('PPL', 'PML'):
        try:
            proses(dg, jenis, session)
        except Exception as e:
            print(f'[{jenis}] ERROR: {e}')
    print(f'\nSemua hasil di: {OUTPUT}')


if __name__ == '__main__':
    main()
