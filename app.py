"""장보기 알림메모 — streamlit run app.py

GitHub에 app.py와 requirements.txt 업로드 → Streamlit Community Cloud 배포.
QR은 배포 URL을 연다. 알림은 화면 내 구매 안내이며 푸시 알림은 아니다.
데이터: SQLite. Community Cloud의 재시작/재배포 시 로컬 DB가 유실될 수 있다.
영구 보관이 필요하면 외부 DB로 교체해야 한다. 아래 설정에서 CSV 백업 가능.
같은 목록 URL/QR을 아는 사람은 목록을 조회·수정할 수 있다(로그인 없음).
선택사항: Streamlit Secrets에 APP_URL = "https://your-app.streamlit.app" 설정.
"""
from __future__ import annotations

import csv
import io
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import qrcode
import streamlit as st

st.set_page_config(page_title="장보기 메모", page_icon="🛒", layout="centered", initial_sidebar_state="collapsed")
CATEGORIES = ["🥬 야채", "🍎 과일", "🥩 정육·계란", "🐟 수산", "🥛 유제품", "🍚 쌀·곡물", "🧊 냉동·간편식", "🍪 간식·음료", "🧴 생활용품", "📦 기타"]
PRIORITIES = {1: "🔴 1 · 꼭 구매", 2: "🟡 2 · 가격 보고", 3: "🟢 3 · 저렴할 때"}
DB_PATH = os.environ.get("SHOPPING_DB_PATH", "shopping_memo.sqlite3")


def connect():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY, list_id TEXT NOT NULL, category TEXT NOT NULL,
            name TEXT NOT NULL, priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 3),
            ceiling INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'memo', quantity REAL, unit TEXT,
            unit_price INTEGER, total INTEGER, created TEXT NOT NULL, bought TEXT)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_items_list ON items(list_id, status)")


def rows(list_id, status=None):
    with connect() as con:
        if status:
            return con.execute("SELECT * FROM items WHERE list_id=? AND status=? ORDER BY priority,created", (list_id, status)).fetchall()
        return con.execute("SELECT * FROM items WHERE list_id=? ORDER BY created", (list_id,)).fetchall()


def add_item(list_id, category, name, priority, ceiling, note):
    with connect() as con:
        con.execute("""INSERT INTO items
            (id,list_id,category,name,priority,ceiling,note,created)
            VALUES(?,?,?,?,?,?,?,?)""", (uuid.uuid4().hex, list_id, category, name, priority, ceiling, note, datetime.now(timezone.utc).isoformat()))


def purchase(list_id, item_id, quantity, unit, price, price_mode):
    q = Decimal(str(quantity))
    p = Decimal(str(price))
    total = int((q * p if price_mode == "개당 가격" else p).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    unit_price = int((p if price_mode == "개당 가격" else p / q).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    with connect() as con:
        cursor = con.execute("""UPDATE items SET status='cart',quantity=?,unit=?,unit_price=?,total=?,bought=?
            WHERE id=? AND list_id=? AND status='memo'""", (float(q), unit, unit_price, total, datetime.now(timezone.utc).isoformat(), item_id, list_id))
        return cursor.rowcount == 1


def move_back(list_id, item_id):
    with connect() as con:
        con.execute("""UPDATE items SET status='memo',quantity=NULL,unit=NULL,unit_price=NULL,total=NULL,bought=NULL
            WHERE id=? AND list_id=? AND status='cart'""", (item_id, list_id))


def delete_memo(list_id, item_id):
    with connect() as con:
        con.execute("DELETE FROM items WHERE id=? AND list_id=? AND status='memo'", (item_id, list_id))


def build_url(base, token):
    parts = urlsplit(base.strip())
    if parts.scheme not in ("https", "http") or not parts.netloc or parts.username or parts.password:
        raise ValueError("https://로 시작하는 배포 주소를 입력하세요.")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "list"]
    query.append(("list", token))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def csv_data(data):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["상품", "카테고리", "중요도", "희망단가", "메모", "상태", "수량", "단위", "단가(원,반올림)", "결제금액(원)", "구매시각(UTC)"])
    for r in data:
        # Neutralize spreadsheet formulas in user-entered text.
        safe = lambda v: "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
        writer.writerow([safe(r[k]) for k in ["name", "category", "priority", "ceiling", "note", "status", "quantity", "unit", "unit_price", "total", "bought"]])
    return out.getvalue().encode("utf-8-sig")


def main():
    init_db()
    token = str(st.query_params.get("list", ""))
    try:
        token = uuid.UUID(token).hex
    except (ValueError, TypeError, AttributeError):
        token = uuid.uuid4().hex
    if st.query_params.get("list") != token:
        st.query_params["list"] = token

    st.markdown("""<style>
    .block-container {max-width:620px;padding:0.65rem 0.8rem 1rem;}
    [data-testid="stHeader"] {height:0;background:transparent;}
    [data-testid="stToolbar"] {display:none;}
    .stApp {background:#f7faf8;}
    h3 {font-size:1.12rem!important;padding:0!important;margin:0!important;}
    [data-testid="stVerticalBlock"] {gap:0.42rem;}
    [data-testid="stHorizontalBlock"] {flex-wrap:nowrap!important;gap:0.5rem;}
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {min-width:0!important;}
    div[data-testid="stMetric"] {background:#e9f3ed;border-radius:14px;padding:0.45rem 0.65rem;}
    [data-testid="stMetricValue"] {font-size:1.35rem;}
    [data-testid="stMetricLabel"] {font-size:0.78rem;}
    [data-testid="stCaptionContainer"] p {font-size:0.76rem;margin:0;}
    div[data-testid="stPopoverBody"] {max-height:80dvh;overflow-y:auto;}
    .stButton button, [data-testid="stPopover"] button {min-height:2.25rem;}
    @media(max-width:400px){.block-container{padding:0.4rem 0.55rem;} }
    </style>""", unsafe_allow_html=True)

    memos = rows(token, "memo")
    cart = rows(token, "cart")
    total = sum(r["total"] or 0 for r in cart)
    st.markdown("### 🛒 장보기 알림메모")
    a, b = st.columns(2)
    a.metric("남은 메모", f"{len(memos)}개")
    b.metric("현재 카트 합계", f"{total:,}원")

    left, right = st.columns([1, 1])
    with left:
        with st.popover("＋ 상품 추가", use_container_width=True):
            with st.form("add", clear_on_submit=True):
                category = st.selectbox("카테고리", CATEGORIES)
                name = st.text_input("상품명", max_chars=60, placeholder="예: 방울토마토 500g")
                priority = st.selectbox("중요도", [1, 2, 3], format_func=PRIORITIES.get, index=1)
                ceiling = st.number_input("희망 최대 단가(원) · 0이면 미설정", min_value=0, max_value=100000000, step=100, value=0)
                note = st.text_input("짧은 메모(선택)", placeholder="예: 비싸면 패스 / 1+1 확인", max_chars=100)
                submitted = st.form_submit_button("메모에 추가", use_container_width=True, type="primary")
            if submitted:
                if not name.strip():
                    st.error("상품명을 입력하세요.")
                else:
                    add_item(token, category, name.strip(), priority, int(ceiling), note.strip())
                    st.rerun()
    with right:
        with st.popover("QR · 백업", use_container_width=True):
            st.caption("같은 QR은 같은 목록을 엽니다. 링크를 아는 사람은 수정할 수 있으니 공개 게시하지 마세요.")
            try:
                default_url = st.secrets.get("APP_URL", "")
            except Exception:
                default_url = ""
            base = st.text_input("배포된 앱 주소", value=default_url, placeholder="https://내앱.streamlit.app", key="base_url")
            if base:
                try:
                    url = build_url(base, token)
                    buffer = io.BytesIO()
                    qrcode.make(url).save(buffer, format="PNG")
                    st.image(buffer.getvalue(), width=190)
                    st.link_button("이 목록 열기", url)
                    st.download_button("QR 이미지 저장", buffer.getvalue(), "shopping_qr.png", "image/png")
                except ValueError as exc:
                    st.warning(str(exc))
            st.download_button("전체 내역 CSV 백업", csv_data(rows(token)), "shopping_backup.csv", "text/csv")
            st.caption("목록은 주소에 저장된 식별자로 구분됩니다. 일반 앱 주소만 열면 새 목록이 만들어집니다. 사용 중인 목록 주소를 북마크하세요.")
            st.caption("Cloud 재시작·재배포 시 DB가 유실될 수 있습니다. 장기 보관용이라면 외부 DB 연동이 필요합니다.")
            if st.button("다른 기기 변경사항 새로고침", use_container_width=True):
                st.rerun()

    st.caption("🔴 1 꼭 구매 · 🟡 2 가격 보고 · 🟢 3 저렴할 때")
    selected = st.selectbox("살 물건", options=[r["id"] for r in memos],
        format_func=lambda ident: next(f'{PRIORITIES[r["priority"]].split()[0]} {r["name"]} · {r["category"]}' for r in memos if r["id"] == ident),
        index=0 if memos else None, placeholder="상품 추가 버튼으로 메모를 등록하세요.")
    if selected:
        item = next(r for r in memos if r["id"] == selected)
        limit_text = f'희망 단가 {item["ceiling"]:,}원' if item["ceiling"] else "희망 단가 미설정"
        st.caption(f'{limit_text} · {item["note"] or "등록된 추가 메모 없음"}')
        if item["priority"] == 1:
            st.caption("🔴 꼭 필요한 상품입니다. 가격과 대체 상품을 확인하세요.")
        else:
            st.caption("💡 비싸다면 아래 ‘오늘 패스’를 누르세요. 메모는 그대로 남습니다.")
        buy_col, skip_col, del_col = st.columns([2, 1.3, 1])
        with buy_col:
            with st.popover("🛒 카트에 담기", use_container_width=True):
                st.write(f'**{item["name"]}**')
                # No form here: price preview and warnings update as the user types.
                qty = st.number_input("구매 수량", min_value=0.01, max_value=100000.0, value=1.0, step=1.0, key=f"qty_{selected}")
                unit = st.selectbox("수량 단위", ["개", "팩", "봉", "병", "kg", "g", "묶음"], key=f"unit_{selected}")
                mode = st.radio("가격 입력 방식", ["개당 가격", "이 상품 전체 금액"], horizontal=True, key=f"mode_{selected}")
                price = st.number_input("가격(원)", min_value=0, max_value=100000000, value=0, step=100, key=f"price_{selected}")
                estimated = int((Decimal(str(qty)) * Decimal(price) if mode == "개당 가격" else Decimal(price)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                effective_unit = Decimal(price) if mode == "개당 가격" else Decimal(price) / Decimal(str(qty))
                st.write(f"이 상품 **{estimated:,}원** → 카트 **{total + estimated:,}원**")
                over = item["ceiling"] > 0 and effective_unit > item["ceiling"]
                if over:
                    st.warning("희망 최대 단가를 넘었습니다. 수량 단위가 희망 단가 기준과 같은지도 확인하세요.")
                if item["priority"] > 1:
                    st.caption("가격이 부담되면 이 창을 닫고 오늘 패스하세요.")
                confirmed = True
                if over or price == 0:
                    confirmed = st.checkbox("가격을 확인했고 이 금액으로 담겠습니다.", key=f"confirm_{selected}_{price}_{qty}_{mode}")
                if st.button("구매금액 기록하고 담기", type="primary", use_container_width=True, disabled=not confirmed):
                    purchase(token, selected, qty, unit, price, mode)
                    st.rerun()
        with skip_col:
            if st.button("오늘 패스", use_container_width=True):
                st.toast("이번에는 구매하지 않습니다. 메모는 그대로 보관됩니다.", icon="💡")
        with del_col:
            with st.popover("삭제", use_container_width=True):
                st.caption("구매가 아닌 메모 취소입니다. 구매했다면 카트에 담기를 사용하세요.")
                if st.button("메모 삭제 확인", key=f"delete_{selected}"):
                    delete_memo(token, selected)
                    st.rerun()

    chosen_cart = st.selectbox("담은 물건 · 금액 확인 / 되돌리기", options=[r["id"] for r in cart],
        format_func=lambda ident: next(f'{r["name"]} · {r["quantity"]:g}{r["unit"]} · {r["total"]:,}원' for r in cart if r["id"] == ident),
        index=0 if cart else None, placeholder="아직 카트가 비어 있어요.")
    if chosen_cart:
        if st.button("↩ 선택 상품을 메모로 되돌리기", use_container_width=True):
            move_back(token, chosen_cart)
            st.rerun()
    st.caption("메모 → 수량·가격 입력 → 카트 합산 | QR은 ‘QR · 백업’에서")


if __name__ == "__main__":
    main()
