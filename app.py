import streamlit as st
import pandas as pd
import gspread
import time
from fpdf import FPDF
import base64
from datetime import datetime

# --- PAGE CONFIG ---
st.set_page_config(
    page_title="ALSDI MIS",
    page_icon="🏫",
    layout="wide"
)

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
REGISTRAR_SHEET_NAME = "Registrar 2025-2026"
FINANCE_SHEET_NAME = "Finance 2025-2026"

# SYSTEM SETTINGS
SCHOOL_YEARS = ["2025-2026", "2026-2027", "2027-2028"]
CURRENT_DATE = datetime.now().strftime('%Y-%m-%d')

# Fee breakdown per grade (DP, Monthly, Books). Total will be computed.
FEE_STRUCTURE = {
    "Pre-K": {"dp": 9000, "monthly": 1175, "books": 4500},
    "Kinder": {"dp": 10500, "monthly": 1175, "books": 4500},
    "Grade 1": {"dp": 9500, "monthly": 1275, "books": 5230},
    "Grade 2": {"dp": 9500, "monthly": 1275, "books": 5230},
    "Grade 3": {"dp": 9500, "monthly": 1275, "books": 5230},
    "Grade 4": {"dp": 9500, "monthly": 1375, "books": 6430},
    "Grade 5": {"dp": 9500, "monthly": 1375, "books": 6430},
    "Grade 6": {"dp": 11500, "monthly": 1375, "books": 6430},
    "Grade 7": {"dp": 10000, "monthly": 1475, "books": 6430},
    "Grade 8": {"dp": 10000, "monthly": 1475, "books": 6430},
    "Grade 9": {"dp": 10000, "monthly": 1475, "books": 6430},
    "Grade 10": {"dp": 11500, "monthly": 1475, "books": 6430},
}

# Monthly is Jun-Mar = 10 months
MONTHLY_MONTHS = 10

GRADE_LEVELS = list(FEE_STRUCTURE.keys())
STUDENT_TYPES = ["New Student", "Old / Continuing", "Transferee", "Returnee"]
PAYMENT_METHODS = ["Cash", "GCash", "Bank Transfer", "Check"]

# --- UI STYLING ---
st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; }
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #eaeaea;
    }
    .sidebar-school-name {
        font-size: 14px;
        font-weight: bold;
        color: #1e3a8a;
        text-transform: uppercase;
        margin-bottom: 0px;
        line-height: 1.2;
    }
    .sidebar-system-name {
        font-size: 12px;
        color: #64748b;
        margin-top: 5px;
        font-style: italic;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔌 DATABASE CONNECTION & CACHING (DEBUG MODE)
# ==========================================

@st.cache_resource
def get_connection():
    try:
        return gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    except Exception as e:
        st.error(f"❌ Secret Key Error: {e}")
        st.stop()

@st.cache_resource
def get_spreadsheets():
    gc = get_connection()
    try:
        sh_reg = gc.open(REGISTRAR_SHEET_NAME)
        sh_fin = gc.open(FINANCE_SHEET_NAME)
        return sh_reg, sh_fin, None
    except Exception as e:
        return None, None, e

@st.cache_data(ttl=5)
def fetch_sheet_data(_ws):
    try:
        return _ws.get_all_values()
    except Exception:
        return []

def load_data():
    sh_reg, sh_fin, error_msg = get_spreadsheets()

    if error_msg:
        st.error(f"❌ Google Connection Failed: {error_msg}")
        st.stop()

    if not sh_reg or not sh_fin:
        st.error("❌ Critical: Unknown connection error.")
        st.stop()

    def safe_read(ws, expected_cols=None):
        data = fetch_sheet_data(ws)

        if not data:
            return pd.DataFrame(columns=expected_cols if expected_cols else [])

        raw_headers = data.pop(0)
        headers = [h.strip() for h in raw_headers]
        df = pd.DataFrame(data, columns=headers)

        df = df.loc[:, [c for c in df.columns if c]]

        if expected_cols:
            for col in expected_cols:
                if col not in df.columns:
                    match = next((h for h in df.columns if h.lower() == col.lower()), None)
                    if match:
                        df.rename(columns={match: col}, inplace=True)
                    else:
                        df[col] = ""
        return df

    # --- REGISTRAR DATA ---
    try:
        ws_reg = sh_reg.worksheet("Student_Registry")
    except Exception:
        st.error("❌ 'Student_Registry' tab missing.")
        st.stop()

    cols_reg = [
        "Student_ID", "LRN", "Last Name", "First Name", "Middle Name", "Grade Level",
        "Student Type", "Previous School", "PSA Birth Cert", "Report Card / ECCD",
        "Good Moral", "SF10 Status", "Data Privacy Consent", "Current Status", "School_Year"
    ]
    df_reg = safe_read(ws_reg, cols_reg)
    if not df_reg.empty:
        df_reg["Student_ID"] = df_reg["Student_ID"].astype(str)
        if "School_Year" in df_reg.columns:
            df_reg["School_Year"] = df_reg["School_Year"].replace("", "2025-2026")
        else:
            df_reg["School_Year"] = "2025-2026"

    # --- SF10 DATA ---
    try:
        ws_sf10 = sh_reg.worksheet("SF10_Requests")
    except Exception:
        ws_sf10 = sh_reg.add_worksheet("SF10_Requests", 1000, 4)
        ws_sf10.append_row(["Timestamp", "Student_Name", "Student_ID", "Status"])
        st.cache_data.clear()

    df_sf10 = safe_read(ws_sf10, ["Timestamp", "Student_Name", "Student_ID", "Status"])

    # --- FINANCE DATA ---
    try:
        ws_pay = sh_fin.worksheet("Payments_Log")
    except Exception:
        ws_pay = sh_fin.add_worksheet("Payments_Log", 1000, 9)
        ws_pay.append_row([
            "Date", "OR_Number", "Student_ID", "Student_Name",
            "Amount", "Method", "Notes", "Type", "School_Year"
        ])
        st.cache_data.clear()

    cols_pay = [
        "Date", "OR_Number", "Student_ID", "Student_Name",
        "Amount", "Method", "Notes", "Type", "School_Year"
    ]
    df_pay = safe_read(ws_pay, cols_pay)
    if not df_pay.empty:
        df_pay["Student_ID"] = df_pay["Student_ID"].astype(str)
        df_pay["Amount"] = pd.to_numeric(df_pay["Amount"], errors="coerce").fillna(0)
        if "School_Year" in df_pay.columns:
            df_pay["School_Year"] = df_pay["School_Year"].replace("", "2025-2026")

    # --- USERS ---
    try:
        ws_users = sh_fin.worksheet("User_Accounts")
    except Exception:
        ws_users = sh_fin.add_worksheet("User_Accounts", 100, 3)
        ws_users.append_row(["Username", "Password", "Role"])
        st.cache_data.clear()

    if len(fetch_sheet_data(ws_users)) <= 1:
        seeds = [
            ["alsdiregistrar", "alsdi2006", "Registrar"],
            ["alsdifinance", "alsdi2006", "Finance"],
            ["alsdiadmin", "alsdi2006", "Admin"]
        ]
        for s in seeds:
            ws_users.append_row(s)
        st.cache_data.clear()

    all_users = fetch_sheet_data(ws_users)
    if all_users:
        headers = all_users.pop(0)
        df_users = pd.DataFrame(all_users, columns=headers)
    else:
        df_users = pd.DataFrame()

    return df_reg, df_sf10, df_pay, df_users, sh_reg, sh_fin

# ==========================================
# --- LOGIC HELPERS ---
# ==========================================

def compute_total_fee(grade):
    fees = FEE_STRUCTURE.get(grade)
    if not fees:
        return 0
    return float(fees["dp"]) + float(fees["books"]) + float(fees["monthly"]) * float(MONTHLY_MONTHS)

def paid_by_category(df_pay, sid, sy, category):
    if df_pay.empty:
        return 0.0
    mask = (
        (df_pay["Student_ID"] == sid) &
        (df_pay["School_Year"] == sy) &
        (df_pay["Notes"] == category)
    )
    return float(df_pay.loc[mask, "Amount"].sum())

def distribute_payment(grade, amount, df_pay, sid, sy):
    fees = FEE_STRUCTURE.get(grade)
    if not fees:
        return {"Tuition Payment": float(amount)}

    remaining = float(amount)
    allocation = {}

    # Already paid
    paid_dp = paid_by_category(df_pay, sid, sy, "DP")
    paid_books = paid_by_category(df_pay, sid, sy, "Books")

    dp_due = float(fees["dp"]) - paid_dp
    if dp_due > 0 and remaining > 0:
        take = min(dp_due, remaining)
        allocation["DP"] = take
        remaining -= take

    books_due = float(fees["books"]) - paid_books
    if books_due > 0 and remaining > 0:
        take = min(books_due, remaining)
        allocation["Books"] = take
        remaining -= take

    if remaining > 0:
        allocation["Monthly Tuition"] = remaining

    return allocation

def get_financials(sid, grade, df_pay, sy):
    total_fee = compute_total_fee(grade)
    paid = 0.0
    if not df_pay.empty:
        mask = (df_pay["Student_ID"] == sid) & (df_pay["School_Year"] == sy)
        paid = float(df_pay.loc[mask, "Amount"].sum())
    return total_fee, paid, total_fee - paid

# ==========================================
# --- PDF GENERATOR ---
# ==========================================

def generate_soa(student, total, paid, balance, history_df, sy):
    pdf = FPDF()
    pdf.add_page()

    # Header
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "ABUNDANT LIFE SCHOOL OF DISCOVERY, INC.", 0, 1, "C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 5, "Management Information System", 0, 1, "C")
    pdf.ln(5)

    # Title
    pdf.set_font("Arial", "I", 11)
    pdf.cell(0, 10, f"STATEMENT OF ACCOUNT (S.Y. {sy})", 0, 1, "C")

    # Line safely below current Y
    y = pdf.get_y()
    pdf.line(10, y, 200, y)
    pdf.ln(10)

    # Student details
    pdf.set_font("Arial", "B", 10)
    pdf.cell(30, 8, "Student:", 0, 0)
    pdf.set_font("Arial", "", 10)
    pdf.cell(100, 8, f"{student['Last Name']}, {student['First Name']}", 0, 0)

    pdf.set_font("Arial", "B", 10)
    pdf.cell(20, 8, "Grade:", 0, 0)
    pdf.set_font("Arial", "", 10)
    pdf.cell(30, 8, str(student["Grade Level"]), 0, 1)

    gen_date = datetime.now().strftime("%B %d, %Y")
    pdf.cell(130, 8, "", 0, 0)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(20, 8, "Date:", 0, 0)
    pdf.set_font("Arial", "", 10)
    pdf.cell(30, 8, gen_date, 0, 1)

    pdf.ln(5)

    # Financial Summary
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 8, "FINANCIAL SUMMARY", 1, 1, "L", fill=True)

    pdf.set_font("Arial", "", 10)
    pdf.cell(140, 8, "Total School Fees", 1, 0)
    pdf.cell(50, 8, f"{total:,.2f}", 1, 1, "R")

    pdf.cell(140, 8, "Less: Total Payments", 1, 0)
    pdf.cell(50, 8, f"({paid:,.2f})", 1, 1, "R")

    pdf.set_font("Arial", "B", 10)
    pdf.cell(140, 8, "REMAINING BALANCE", 1, 0)
    pdf.cell(50, 8, f"{balance:,.2f}", 1, 1, "R")

    pdf.ln(20)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 10, "For any queries regarding this statement, please see the Accounting Officer", 0, 1, "C")

    return pdf.output(dest="S").encode("latin-1")

# ==========================================
# 📱 MODULE RENDERERS
# ==========================================

def render_dashboard(df_reg, df_pay, sy):
    st.markdown(f"### 📊 Executive Dashboard • {sy}")
    st.divider()

    sy_reg = df_reg[df_reg["School_Year"] == sy] if not df_reg.empty and "School_Year" in df_reg.columns else pd.DataFrame()
    sy_pay = df_pay[df_pay["School_Year"] == sy] if not df_pay.empty and "School_Year" in df_pay.columns else pd.DataFrame()

    total_students = len(sy_reg)
    total_collections = float(sy_pay["Amount"].sum()) if not sy_pay.empty else 0.0
    expected_rev = 0.0
    if not sy_reg.empty:
        expected_rev = sum([compute_total_fee(g) for g in sy_reg["Grade Level"]])
    receivables = expected_rev - total_collections

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Enrolled", total_students)
    k2.metric("Collections", f"₱{total_collections/1000:,.1f}K")
    k3.metric("Receivables", f"₱{receivables/1000:,.1f}K", delta_color="inverse")

    transferees = len(sy_reg[sy_reg["Student Type"] == "Transferee"]) if not sy_reg.empty and "Student Type" in sy_reg.columns else 0
    k4.metric("Transferees", transferees)

    st.markdown("<br>", unsafe_allow_html=True)

    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown("##### 📈 Enrollment by Grade")
        if not sy_reg.empty:
            st.bar_chart(sy_reg["Grade Level"].value_counts(), color="#4CAF50")
    with c2:
        st.markdown("##### 🕒 Recent Transactions")
        if not sy_pay.empty:
            st.dataframe(sy_pay[["Date", "Student_Name", "Amount", "Notes"]].tail(8), hide_index=True, use_container_width=True)

def render_registrar(df_reg, df_sf10, sh_reg, sy):
    st.subheader(f"🎓 Admissions ({sy})")

    sy_reg = df_reg[df_reg["School_Year"] == sy] if not df_reg.empty and "School_Year" in df_reg.columns else pd.DataFrame()

    t1, t2, t3 = st.tabs(["📝 Enroll Student", "📂 Master List", "📜 SF10 Requests"])

    with t1:
        with st.form("enroll_form"):
            c1, c2 = st.columns(2)
            last = c1.text_input("Last Name")
            first = c2.text_input("First Name")
            lrn = c1.text_input("LRN (Optional)")
            grade = c2.selectbox("Grade Level", GRADE_LEVELS)
            stype = c1.selectbox("Student Type", STUDENT_TYPES)
            prev = c2.text_input("Previous School")

            if st.form_submit_button("💾 Save Student", type="primary"):
                if stype == "Transferee" and not prev:
                    st.error("Previous School is required for Transferees.")
                else:
                    nid = f"{sy.split('-')[0]}-{len(sy_reg)+1:04d}"
                    sh_reg.worksheet("Student_Registry").append_row([
                        nid, lrn, last, first, "", grade, stype, prev,
                        "To Follow", "To Follow", "To Follow", "To Request", "FALSE", "Pending", sy
                    ])
                    st.toast(f"Student Enrolled: {nid}", icon="✅")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()

  with t2:
        st.markdown("### ✏️ Edit Student Records")

        edited_df = st.data_editor(
            sy_reg,
            use_container_width=True,
            num_rows="dynamic",
            disabled=["Student_ID", "School_Year"]
        )

        if st.button("💾 Save Changes", type="primary"):
            ws = sh_reg.worksheet("Student_Registry")

            ws.batch_clear(["A2:Z"])

            ws.append_rows(
                edited_df.astype(str).values.tolist(),
                value_input_option="USER_ENTERED"
            )

            st.success("Student records updated successfully.")
            st.cache_data.clear()
            st.rerun()


    with t3:
        col_req, col_list = st.columns([1, 2])
        with col_req:
            st.markdown("#### Create Request")
            req_type = st.radio("Request Type", ["Current Student", "Walk-in / Alumni"], horizontal=True)

            name_to_log = ""
            id_to_log = "WALK-IN"

            if req_type == "Current Student":
                all_students_list = df_reg.apply(
                    lambda x: f"{x['Last Name']}, {x['First Name']} ({x['Student_ID']})",
                    axis=1
                ).tolist()
                search_sf10 = st.selectbox("Select Student", all_students_list, index=None)
                if search_sf10:
                    sid = search_sf10.split("(")[-1].replace(")", "")
                    stu_row = df_reg[df_reg["Student_ID"] == sid].iloc[0]
                    name_to_log = f"{stu_row['Last Name']}, {stu_row['First Name']}"
                    id_to_log = sid
            else:
                st.info("Input details for student not in database.")
                m_last = st.text_input("Last Name (Manual)")
                m_first = st.text_input("First Name (Manual)")
                if m_last and m_first:
                    name_to_log = f"{m_last}, {m_first}"

            if st.button("➕ Generate Request", type="primary"):
                if name_to_log:
                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    sh_reg.worksheet("SF10_Requests").append_row([
                        ts, name_to_log, id_to_log, "Pending Payment"
                    ])
                    st.success(f"Request Logged for {name_to_log}!")
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Please provide student details.")

        with col_list:
            st.markdown("#### Request Log")
            if not df_sf10.empty:
                st.dataframe(
                    df_sf10.sort_values(by="Timestamp", ascending=False),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No requests found.")

def render_finance(df_reg, df_pay, df_sf10, sh_fin, sh_reg, sy):
    st.subheader(f"💰 Finance Portal ({sy})")

    sy_reg = df_reg[df_reg["School_Year"] == sy] if not df_reg.empty and "School_Year" in df_reg.columns else pd.DataFrame()
    sy_pay = df_pay[df_pay["School_Year"] == sy] if not df_pay.empty and "School_Year" in df_pay.columns else pd.DataFrame()

    t_cashier, t_docs, t_ledger = st.tabs(["💸 Cashiering", "📜 Document Fees (SF10)", "📒 Transaction Log"])

    with t_cashier:
        c1, c2 = st.columns([1, 2])
        with c1:
            search = st.selectbox(
                "🔍 Find Student",
                sy_reg.apply(lambda x: f"{x['Last Name']}, {x['First Name']} ({x['Student_ID']})", axis=1).tolist(),
                index=None
            )
            if search:
                sid = search.split("(")[-1].replace(")", "")
                stu = sy_reg[sy_reg["Student_ID"] == sid].iloc[0]
                fee, paid, bal = get_financials(sid, stu["Grade Level"], df_pay, sy)

                st.info(f"Selected: **{stu['Last Name']}, {stu['First Name']}**")
                st.metric("Tuition Balance", f"₱{bal:,.2f}")

                with st.form("pay_tuition"):
                    amt = st.number_input("Amount (₱)", min_value=1.0)
                    or_n = st.text_input("OR Number")
                    meth = st.selectbox("Method", PAYMENT_METHODS)

                    submitted = st.form_submit_button("Process Tuition Payment", type="primary")
                    if submitted:
                        allocations = distribute_payment(stu["Grade Level"], amt, df_pay, sid, sy)
                        ws = sh_fin.worksheet("Payments_Log")

                        for category, value in allocations.items():
                            ws.append_row([
                                CURRENT_DATE,
                                or_n,
                                sid,
                                f"{stu['Last Name']}, {stu['First Name']}",
                                float(value),
                                meth,
                                category,
                                "Payment",
                                sy
                            ])

                        st.success("Payment recorded & auto-distributed!")
                        st.cache_data.clear()
                        time.sleep(1)
                        st.rerun()

                if st.button("📄 Download SOA PDF"):
                    mask = (sy_pay["Student_ID"] == sid)
                    hist = sy_pay[mask]
                    pdf_bytes = generate_soa(stu, fee, paid, bal, hist, sy)
                    b64 = base64.b64encode(pdf_bytes).decode()
                    href = f'<a href="data:application/octet-stream;base64,{b64}" download="SOA_{sid}.pdf">📥 Download PDF</a>'
                    st.markdown(href, unsafe_allow_html=True)

    with t_docs:
        st.markdown("#### Pending Document Requests")
        pending_sf10 = df_sf10[df_sf10["Status"] == "Pending Payment"] if not df_sf10.empty else pd.DataFrame()

        if not pending_sf10.empty:
            for i, row in pending_sf10.iterrows():
                label = f"📄 {row['Student_Name']} (ID: {row['Student_ID']})"
                with st.expander(label):
                    st.caption(f"Requested: {row['Timestamp']}")
                    with st.form(f"pay_doc_{i}"):
                        c_a, c_b = st.columns(2)
                        doc_fee = c_a.number_input("SF10 Fee", value=150.0)
                        or_doc = c_b.text_input("OR Number", key=f"or_{i}")
                        if st.form_submit_button("Process Payment & Release"):
                            sh_fin.worksheet("Payments_Log").append_row([
                                CURRENT_DATE, or_doc, str(row["Student_ID"]), row["Student_Name"],
                                float(doc_fee), "Cash", "SF10 Request Fee", "Document Fee", sy
                            ])
                            sh_reg.worksheet("SF10_Requests").append_row([
                                datetime.now().strftime("%Y-%m-%d"), row["Student_Name"], str(row["Student_ID"]), "PAID / RELEASED"
                            ])
                            st.success("Payment Taken & Status Updated!")
                            st.cache_data.clear()
                            time.sleep(1)
                            st.rerun()
        else:
            st.info("No pending requests.")

        st.divider()
        st.markdown("#### Request History")
        st.dataframe(df_sf10, use_container_width=True)

    with t_ledger:
        st.dataframe(sy_pay, use_container_width=True)

def render_admin(df_users, sh_fin):
    st.subheader("🛡️ User Administration")
    st.dataframe(df_users, use_container_width=True)
    with st.form("add_user"):
        c1, c2, c3 = st.columns(3)
        u = c1.text_input("User")
        p = c2.text_input("Pass")
        r = c3.selectbox("Role", ["Registrar", "Finance", "Teacher", "HR"])
        if st.form_submit_button("Create"):
            if not df_users.empty and u in df_users["Username"].values:
                st.error("Exists")
            else:
                sh_fin.worksheet("User_Accounts").append_row([u, p, r])
                st.success("Created")
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()

# ==========================================
# 🚀 MAIN APP EXECUTION
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.sy = SCHOOL_YEARS[0]

# 1. LOAD DATA
try:
    df_reg, df_sf10, df_pay, df_users, sh_reg, sh_fin = load_data()
except Exception as e:
    st.error(f"Connection Error: {e}")
    st.stop()

# 2. LOGIN
if not st.session_state.logged_in:
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("""
            <div style='text-align: center; margin-bottom: 30px;'>
                <h2 style='color: #1e3a8a; margin-bottom: 5px;'>ABUNDANT LIFE SCHOOL OF DISCOVERY, INC.</h2>
                <h5 style='color: #64748b;'>Management Information System</h5>
            </div>
        """, unsafe_allow_html=True)

        with st.form("login"):
            user = st.text_input("Username")
            pwd = st.text_input("Password", type="password")
            sy_sel = st.selectbox("School Year", SCHOOL_YEARS)
            if st.form_submit_button("Login", type="primary", use_container_width=True):
                role = None
                if user == st.secrets["auth"]["username"] and pwd == st.secrets["auth"]["password"]:
                    role = "Admin"
                elif not df_users.empty:
                    rec = df_users[df_users["Username"] == user]
                    if not rec.empty and str(rec.iloc[0]["Password"]) == pwd:
                        role = rec.iloc[0]["Role"]

                if role:
                    st.session_state.logged_in = True
                    st.session_state.role = role
                    st.session_state.sy = sy_sel
                    st.rerun()
                else:
                    st.error("Invalid Credentials")

# 3. DASHBOARD
else:
    role = st.session_state.role
    sy = st.session_state.sy

    with st.sidebar:
        st.markdown("""
            <div style='text-align: center; padding-bottom: 20px;'>
                <div class='sidebar-school-name'>ABUNDANT LIFE SCHOOL<br>OF DISCOVERY, INC.</div>
                <div class='sidebar-system-name'>Management Information System</div>
            </div>
        """, unsafe_allow_html=True)

        st.caption(f"User: {role}")
        new_sy = st.selectbox("SY", SCHOOL_YEARS, index=SCHOOL_YEARS.index(sy))
        if new_sy != sy:
            st.session_state.sy = new_sy
            st.rerun()
        st.divider()

        menu_opts = ["📊 Dashboard"]
        if role in ["Registrar", "Admin"]:
            menu_opts.append("🎓 Admissions")
        if role in ["Finance", "Admin"]:
            menu_opts.append("💰 Finance")
        if role == "Admin":
            menu_opts.append("🛡️ User Admin")

        sel = st.radio("Menu", menu_opts, label_visibility="collapsed")
        st.divider()
        if st.button("Log Out"):
            st.session_state.logged_in = False
            st.rerun()

    if sel == "📊 Dashboard":
        render_dashboard(df_reg, df_pay, sy)
    elif sel == "🎓 Admissions":
        render_registrar(df_reg, df_sf10, sh_reg, sy)
    elif sel == "💰 Finance":
        render_finance(df_reg, df_pay, df_sf10, sh_fin, sh_reg, sy)
    elif sel == "🛡️ User Admin":
        render_admin(df_users, sh_fin)



