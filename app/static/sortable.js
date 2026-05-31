
// ── SORTABLE TABLE ──────────────────────────────────────────────
// Panggil: initSortableTable('id-tabel')
function initSortableTable(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const thead = table.querySelector('thead tr');
  const tbody = table.querySelector('tbody');
  if (!thead || !tbody) return;

  let sortCol = -1;
  let sortAsc = true;

  // Tambah ikon dan cursor ke setiap th
  thead.querySelectorAll('th[data-sort]').forEach((th, idx) => {
    th.style.cursor = 'pointer';
    th.style.userSelect = 'none';
    th.style.whiteSpace = 'nowrap';

    const icon = document.createElement('span');
    icon.className = 'sort-icon ms-1';
    icon.innerHTML = '<i class="bi bi-arrow-down-up" style="font-size:10px;opacity:0.4;"></i>';
    th.appendChild(icon);

    th.addEventListener('click', () => {
      // Arah sort
      if (sortCol === idx) {
        sortAsc = !sortAsc;
      } else {
        sortCol = idx;
        sortAsc = true;
      }

      // Update semua ikon
      thead.querySelectorAll('th[data-sort] .sort-icon').forEach((ic, i) => {
        if (i === idx) {
          ic.innerHTML = sortAsc
            ? '<i class="bi bi-arrow-up" style="font-size:10px;color:#1341A0;"></i>'
            : '<i class="bi bi-arrow-down" style="font-size:10px;color:#1341A0;"></i>';
        } else {
          ic.innerHTML = '<i class="bi bi-arrow-down-up" style="font-size:10px;opacity:0.4;"></i>';
        }
      });

      // Ambil semua baris tbody (kecuali baris kosong/no-data)
      const rows = Array.from(tbody.querySelectorAll('tr:not(.no-sort)'));
      const tipe = th.dataset.sort || 'text';

      rows.sort((a, b) => {
        const cellA = a.querySelectorAll('td')[idx];
        const cellB = b.querySelectorAll('td')[idx];
        if (!cellA || !cellB) return 0;

        let valA = cellA.dataset.val ?? cellA.textContent.trim();
        let valB = cellB.dataset.val ?? cellB.textContent.trim();

        if (tipe === 'number') {
          // Hapus titik ribuan dan Rp
          valA = parseFloat(valA.replace(/[^0-9,-]/g, '').replace(',', '.')) || 0;
          valB = parseFloat(valB.replace(/[^0-9,-]/g, '').replace(',', '.')) || 0;
          return sortAsc ? valA - valB : valB - valA;
        } else if (tipe === 'spk') {
          // Natural sort untuk nomor SPK/BAST: PK-2 < PK-11 < PK-107A < PK-107B
          const parseSpk = s => {
            const m = s.match(/[-](\d+)([A-Za-z]?)/);
            return m ? [parseInt(m[1], 10), (m[2] || '').toUpperCase()] : [99999, ''];
          };
          const [nA, sA] = parseSpk(valA);
          const [nB, sB] = parseSpk(valB);
          if (nA !== nB) return sortAsc ? nA - nB : nB - nA;
          return sortAsc ? sA.localeCompare(sB) : sB.localeCompare(sA);
        } else if (tipe === 'date') {
          // Format dd/mm/yyyy atau dd Mon yyyy
          const parseDate = s => {
            const m = s.match(/(\d{2})[\/\s](\w+)[\/\s](\d{4})/);
            return m ? new Date(`${m[3]}-${m[2]}-${m[1]}`) : new Date(s);
          };
          return sortAsc
            ? parseDate(valA) - parseDate(valB)
            : parseDate(valB) - parseDate(valA);
        } else {
          // Text
          return sortAsc
            ? valA.localeCompare(valB, 'id')
            : valB.localeCompare(valA, 'id');
        }
      });

      // Kembalikan ke DOM
      rows.forEach(r => tbody.appendChild(r));
    });
  });
}

// ── SEARCH PER KOLOM ─────────────────────────────────────────────
// Panggil: initSearchRow('id-tabel')
// Akan menambahkan baris input pencarian tepat di bawah baris header
function initSearchRow(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const thead = table.querySelector('thead');
  const tbody = table.querySelector('tbody');
  if (!thead || !tbody) return;

  const headerRow = thead.querySelector('tr');
  const ths       = Array.from(headerRow.querySelectorAll('th'));

  // Buat baris pencarian
  const searchRow = document.createElement('tr');
  searchRow.className = 'search-row';

  ths.forEach((th, idx) => {
    const td = document.createElement('td');
    td.style.padding = '4px 4px';
    td.style.background = '#F0F4FF';

    // Kolom aksi (data-sort tidak ada atau lebar tetap) → skip
    if (!th.dataset.sort || th.style.width) {
      td.innerHTML = '';
    } else {
      const inp = document.createElement('input');
      inp.type        = 'text';
      inp.placeholder = '🔍 ' + th.textContent.replace(/[↕↑↓]/g, '').trim();
      inp.className   = 'form-control form-control-sm search-input';
      inp.style.cssText = 'font-size:11px;height:28px;border:1px solid #C7D7F5;';
      inp.dataset.col = idx;

      inp.addEventListener('input', () => filterTable(tableId));
      td.appendChild(inp);
    }
    searchRow.appendChild(td);
  });

  thead.appendChild(searchRow);

  // Tambah tombol reset di atas tabel
  const wrapper = table.closest('.table-responsive') || table.parentElement;
  const resetDiv = document.createElement('div');
  resetDiv.style.cssText = 'text-align:right;margin-bottom:4px;';
  resetDiv.innerHTML =
    '<button type="button" class="btn btn-outline-secondary btn-sm py-0 px-2" ' +
    'style="font-size:11px;" onclick="resetSearch(\'' + tableId + '\')">' +
    '<i class="bi bi-x-circle me-1"></i>Reset Pencarian</button>';
  wrapper.parentElement.insertBefore(resetDiv, wrapper);
}

function filterTable(tableId) {
  const table   = document.getElementById(tableId);
  const inputs  = table.querySelectorAll('.search-input');
  const filters = Array.from(inputs).map(inp => ({
    col: parseInt(inp.dataset.col),
    val: inp.value.toLowerCase().trim()
  })).filter(f => f.val !== '');

  const rows = table.querySelectorAll('tbody tr:not(.no-sort)');
  let visible = 0;

  rows.forEach(row => {
    const tds = row.querySelectorAll('td');
    const show = filters.every(f => {
      const td = tds[f.col];
      if (!td) return true;
      const text = (td.dataset.val ?? td.textContent).toLowerCase();
      return text.includes(f.val);
    });
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  });

  // Update badge jumlah jika ada
  const badge = document.querySelector('[data-count-badge="' + tableId + '"]');
  if (badge) badge.textContent = visible;
}

function resetSearch(tableId) {
  const table = document.getElementById(tableId);
  table.querySelectorAll('.search-input').forEach(inp => inp.value = '');
  filterTable(tableId);
}
