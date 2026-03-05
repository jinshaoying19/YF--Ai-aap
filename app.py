import streamlit as st
import easyocr
from PIL import Image
import pandas as pd
import sqlite3
import io
from datetime import datetime
import json

st.set_page_config(page_title="发票AI系统", layout="wide")
st.title("🧾 全团队发票AI自动填充系统（V251101官方模板）")
st.caption("多人同时使用 · 所有发票自动入库 · 一键下载全公司总表")

# ====================== 数据库 ======================
conn = sqlite3.connect('invoices.db', check_same_thread=False)
conn.execute('''CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    buyer_name TEXT,
    buyer_tax TEXT,
    total_amount REAL,
    details TEXT,           -- JSON
    excel_name TEXT
)''')
conn.commit()

# ====================== OCR ======================
@st.cache_resource
def get_reader():
    return easyocr.Reader(['ch_sim', 'en'], gpu=False)
reader = get_reader()

def ocr(img_bytes):
    img = Image.open(io.BytesIO(img_bytes))
    return "\n".join(reader.readtext(img, detail=0))

# ====================== Session ======================
if 'items' not in st.session_state:
    st.session_state.items = []
if 'buyer' not in st.session_state:
    st.session_state.buyer = {"name": "", "tax": "", "addr": "", "phone": "", "email": ""}

# ====================== 主界面 ======================
col1, col2 = st.columns(2)
with col1:
    st.subheader("1. 发票抬头截图（含税号）")
    file1 = st.file_uploader("上传", type=["png","jpg","jpeg"], key="f1")
    if file1: st.image(file1, width=350)

with col2:
    st.subheader("2. 订单明细截图")
    file2 = st.file_uploader("上传", type=["png","jpg","jpeg"], key="f2")
    if file2: st.image(file2, width=350)

if st.button("🚀 开始AI识别", type="primary"):
    if file1 and file2:
        with st.spinner("正在识别..."):
            text1 = ocr(file1.getvalue())
            text2 = ocr(file2.getvalue())
        
        # 提取抬头
        import re
        name = re.search(r'名称[:：\s]*([^\n]+)', text1) or re.search(r'([^\n]+)税号', text1)
        tax = re.search(r'纳税人识别号[:：\s]*([0-9A-Z]{15,20})', text1)
        
        st.session_state.buyer = {
            "name": name.group(1).strip() if name else "",
            "tax": tax.group(1).strip() if tax else "",
            "addr": "", "phone": "", "email": ""
        }
        
        # 解析明细
        st.session_state.items = []
        for line in text2.split('\n'):
            if re.search(r'[\u4e00-\u9fa5]', line):
                name_m = re.search(r'([\u4e00-\u9fa5]+)', line)
                qty_m = re.search(r'(\d+)', line)
                price_m = re.search(r'(\d+\.?\d*)', line)
                if name_m:
                    st.session_state.items.append({
                        "name": name_m.group(1),
                        "qty": float(qty_m.group(1)) if qty_m else 1,
                        "price": float(price_m.group(1)) if price_m else 0,
                        "spec": "", "unit": "件"
                    })
        st.success("识别完成！")

# ====================== 编辑 ======================
if st.session_state.items:
    st.subheader("编辑发票")
    b = st.session_state.buyer
    st.session_state.buyer["name"] = st.text_input("购买方名称", b["name"])
    st.session_state.buyer["tax"] = st.text_input("纳税人识别号", b["tax"])
    st.session_state.buyer["addr"] = st.text_input("地址", b["addr"])
    st.session_state.buyer["phone"] = st.text_input("电话", b["phone"])
    st.session_state.buyer["email"] = st.text_input("邮箱", b["email"])

    df = pd.DataFrame(st.session_state.items)
    edited = st.data_editor(df, num_rows="dynamic", use_container_width=True)
    st.session_state.items = edited.to_dict('records')

    total = sum(i.get("qty",0)*i.get("price",0) for i in st.session_state.items)
    st.info(f"总金额：{total:.2f} 元")

    if st.button("📥 生成官方模板并下载", type="primary"):
        # 生成单张Excel（和之前一样）
        # ...（省略，保持不变）

        # ====================== 存入数据库 ======================
        conn.execute("""
            INSERT INTO history (timestamp, buyer_name, buyer_tax, total_amount, details, excel_name)
            VALUES (?,?,?,?,?,?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            st.session_state.buyer["name"],
            st.session_state.buyer["tax"],
            total,
            json.dumps(st.session_state.items),
            f"发票_{st.session_state.buyer['name']}_{datetime.now().strftime('%Y%m%d%H%M')}.xlsx"
        ))
        conn.commit()

        # 下载后清空
        st.session_state.items = []
        st.session_state.buyer = {"name": "", "tax": "", "addr": "", "phone": "", "email": ""}
        st.rerun()

# ====================== 全团队总表下载 ======================
st.divider()
st.subheader("📊 全团队发票汇总（所有人可见）")

df_all = pd.read_sql("""
    SELECT id, timestamp, buyer_name, buyer_tax, total_amount, excel_name 
    FROM history ORDER BY id DESC
""", conn)

st.dataframe(df_all, use_container_width=True)

if st.button("📥 下载【全公司所有发票总表.xlsx】（包含所有明细）"):
    # 生成汇总Excel
    writer = pd.ExcelWriter("全团队发票总表.xlsx", engine='openpyxl')

    # Sheet1：基本信息汇总
    df_all.to_excel(writer, sheet_name="发票基本信息", index=False)

    # Sheet2：所有明细展开
    details_list = []
    for _, row in df_all.iterrows():
        try:
            items = json.loads(row['details'] if row['details'] else '[]')
            for item in items:
                details_list.append({
                    "发票ID": row['id'],
                    "时间": row['timestamp'],
                    "购买方": row['buyer_name'],
                    "税号": row['buyer_tax'],
                    "商品名称": item.get('name'),
                    "数量": item.get('qty'),
                    "单价": item.get('price'),
                    "金额": item.get('qty') * item.get('price')
                })
        except:
            pass
    
    pd.DataFrame(details_list).to_excel(writer, sheet_name="所有明细", index=False)
    writer.close()

    with open("全团队发票总表.xlsx", "rb") as f:
        st.download_button(
            label="💾 点击下载全团队总表",
            data=f.read(),
            file_name=f"全团队发票总表_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )