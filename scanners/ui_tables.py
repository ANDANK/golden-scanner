# scanners/ui_tables.py — shared UI-only helper for the interactive app: a
# self-contained, click-to-sort HTML table used by the track-record tables.
#
# Rendered via st.components.v1.html (NOT st.markdown) -- Streamlit strips /
# doesn't reliably execute <script> tags injected through st.markdown, so a
# real click-to-sort interaction needs the genuine sandboxed iframe that
# components.html provides instead. Each call gets its own isolated iframe
# (separate `window`), so the embedded JS below can use plain global names
# without worrying about collisions between multiple sortable tables on the
# same page.

from __future__ import annotations
import html as _html

from config import GOLD, BG_PANEL, BORDER_COLOR, TEXT_PRIMARY, TEXT_MUTED


def sortable_table_html(
    columns: list[dict],
    rows: list[list[tuple[str, object]]],
    *,
    default_sort_idx: int | None = None,
    default_desc: bool = True,
    max_height: int = 420,
) -> str:
    """Build a standalone HTML document with a click-to-sort <table>.

    columns: [{"label": str, "type": "num" | "str"}, ...]
    rows: one list per row, each entry a (display_html, sort_value) tuple
          aligned to `columns` — display_html is already-formatted HTML
          (colored spans etc, rendered as-is), sort_value is the raw
          number/string/date-string the column sorts by.
    default_sort_idx: column index to sort by on first render (None = keep
        the given row order until the user clicks a header).
    """
    thead_cells = []
    for i, col in enumerate(columns):
        label = _html.escape(str(col["label"]))
        col_type = "num" if col.get("type") == "num" else "str"
        thead_cells.append(
            f'<th data-type="{col_type}" onclick="sortTable({i})">'
            f'{label} <span class="arrow">⇅</span></th>'
        )
    thead_html = "<tr>" + "".join(thead_cells) + "</tr>"

    body_rows = []
    for row in rows:
        cells = []
        for display_html, sort_value in row:
            v = _html.escape(str(sort_value), quote=True)
            cells.append(f'<td data-v="{v}">{display_html}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    tbody_html = "".join(body_rows)

    init_sort = (
        f"sortTable({default_sort_idx}, {'true' if default_desc else 'false'});"
        if default_sort_idx is not None else ""
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; background:{BG_PANEL}; font-family:Arial,sans-serif; }}
  .wrap {{ max-height:{max_height}px; overflow:auto; border:1px solid {BORDER_COLOR}; border-radius:10px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{
    position:sticky; top:0; background:{BG_PANEL}; color:{TEXT_MUTED}; font-size:10px;
    font-weight:700; text-transform:uppercase; letter-spacing:0.5px; text-align:left;
    padding:8px 10px; border-bottom:1.5px solid {BORDER_COLOR}; cursor:pointer;
    user-select:none; white-space:nowrap;
  }}
  th:hover {{ color:{GOLD}; }}
  th.active {{ color:{GOLD}; }}
  th .arrow {{ opacity:0.55; margin-left:3px; font-size:9px; }}
  th.active .arrow {{ opacity:1; }}
  td {{ padding:7px 10px; border-top:1px solid {BORDER_COLOR}; font-size:12.5px; color:{TEXT_PRIMARY};
        white-space:nowrap; }}
  tr:hover td {{ background:rgba(255,255,255,0.03); }}
</style></head>
<body>
<div class="wrap"><table id="tbl">
  <thead>{thead_html}</thead>
  <tbody>{tbody_html}</tbody>
</table></div>
<script>
let sortState = {{col: -1, desc: true}};
function sortTable(idx, forceDesc) {{
  const table = document.getElementById('tbl');
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const th = table.tHead.rows[0].cells[idx];
  const type = th.getAttribute('data-type');
  if (forceDesc !== undefined) {{
    sortState.col = idx; sortState.desc = forceDesc;
  }} else if (sortState.col === idx) {{
    sortState.desc = !sortState.desc;
  }} else {{
    sortState.col = idx; sortState.desc = true;
  }}
  rows.sort((a, b) => {{
    let av = a.cells[idx].getAttribute('data-v');
    let bv = b.cells[idx].getAttribute('data-v');
    if (type === 'num') {{
      av = parseFloat(av); bv = parseFloat(bv);
      if (isNaN(av)) av = -Infinity;
      if (isNaN(bv)) bv = -Infinity;
    }}
    if (av < bv) return sortState.desc ? 1 : -1;
    if (av > bv) return sortState.desc ? -1 : 1;
    return 0;
  }});
  rows.forEach(r => tbody.appendChild(r));
  Array.from(table.tHead.rows[0].cells).forEach((c, i) => {{
    c.classList.toggle('active', i === idx);
    const arrow = c.querySelector('.arrow');
    if (arrow) arrow.textContent = i === idx ? (sortState.desc ? '▼' : '▲') : '⇅';
  }});
}}
{init_sort}
</script>
</body></html>"""
