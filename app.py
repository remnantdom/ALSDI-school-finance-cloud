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
# ⚙️ CONFIGURATION & FEE CONSTANTS
# ==========================================
REGISTRAR_SHEET_NAME = "Registrar 2025-2026"
FINANCE_SHEET_NAME = "Finance 2025-2026"

SCHOOL_YEARS = ["2025-2026", "2026-2027", "2027-2028"]
CURRENT_DATE = datetime.now().strftime('%Y-%m-%d')

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
MONTHLY_MONTHS = 10
GRADE_LEVELS = list(FEE_STRUCTURE.keys())
STUDENT_TYPES = ["New Student", "Old / Continuing", "Transferee", "Returnee"]
PAYMENT_METHODS = ["Cash", "GCash", "Bank Transfer", "Check"]

# --- UI STYLING ---
st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; }
    div[data-testid="stMetric"] { background-color: #ffffff; border: 1px solid #e0e0e0; padding: 15px; border-radius: 8px; }
    .sidebar-school-name { font-size: 14px; font-weight: bold; color: #1e3a8a; text-transform: uppercase; text-align: center; line-height: 1.2; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔌 DATABASE CONNECTION & CACHING
# ==========================================

@st.cache_resource
def get_connection():
    try:
        return gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    except Exception as e:
        st.error(f"❌ GCP Secret Error: {e}"); st.stop()

@st.cache_resource
def get_spreadsheets():
    gc = get_connection()
    try:
        return gc.open(REGISTRAR_SHEET_NAME), gc.open(FINANCE_SHEET_NAME), None
    except Exception as e:
        return None, None, e

@st.cache_data(ttl=60) # Increased TTL to 60s to prevent API Quota crashes
def fetch_sheet_data(_ws):
    try:
        return _ws.get_all_values()
    except:
        return []

def load_data():
    sh_reg, sh_fin, error_msg = get_spreadsheets()
    if error_msg:
        st.error(f"❌ Connection Failed: {error_msg}"); st.stop()

    def safe_read(ws, expected_cols):
        data = fetch_sheet_data(ws)
        if not data: return pd.DataFrame(columns=expected_cols)
        headers = [h.strip() for h in data.pop(0)]
        df = pd.DataFrame(data, columns=headers)
        for col in expected_cols:
            if col not in df.columns: df[col] = ""
        return df[expected_cols]

    # Load Worksheets
    try:
        ws_reg = sh_reg.worksheet("Student_Registry")
        ws_sf10 = sh_reg.worksheet("SF10_Requests")
        ws_pay = sh_fin.worksheet("Payments_Log")
        ws_users = sh_fin.worksheet("User_Accounts")
    except Exception as e:
        st.error(f"❌ Missing Tabs in Google Sheets: {e}")
        st.stop()

    df_reg = safe_read(ws_reg, ["Student_ID", "LRN", "Last Name", "First Name", "Middle Name", "Grade Level", "Student Type", "Previous School", "PSA Birth Cert", "Report Card / ECCD", "Good Moral", "SF10 Status", "Data Privacy Consent", "Current Status", "School_Year"])
    df_sf10 = safe_read(ws_sf10, ["Timestamp", "Student_Name", "Student_ID", "Status"])
    df_pay = safe_read(ws_pay, ["Date", "OR_Number", "Student_ID", "Student_Name", "Amount", "Method", "Notes", "Type", "School_Year"])
    df_users = safe_read(ws_users, ["Username", "Password", "Role"])

    df_pay["Amount"] = pd.to_numeric(df_pay["Amount"], errors="coerce").fillna(0.0)
    df_reg["Student_ID"] = df_reg["Student_ID"].astype(str)
    
    return df_reg, df_sf10, df_pay, df_users, sh_reg, sh_fin

# ==========================================
# 📈 LOGIC HELPERS
# ==========================================

def compute_total_fee(grade):
    fees = FEE_STRUCTURE.get(grade.strip())
    if not fees: return 0.0
    return float(fees["dp"]) + float(fees["books"]) + (float(fees["monthly"]) * MONTHLY_MONTHS)

def get_financials(sid, grade, df_pay, sy):
    total_fee = compute_total_fee(grade)
    paid = float(df_pay[(df_pay["Student_ID"] == sid) & (df_pay["School_Year"] == sy)]["Amount"].sum())
    return round(total_fee, 2), round(paid, 2), round(total_fee - paid, 2)

def distribute_payment(grade, amount, df_pay, sid, sy):
    fees = FEE_STRUCTURE.get(grade.strip())
    if not fees: return {"Tuition Payment": float(amount)}
    remaining = float(amount); alloc = {}
    
    # Priority 1: DP
    paid_dp = float(df_pay[(df_pay["Student_ID"] == sid) & (df_pay["Notes"] == "DP") & (df_pay["School_Year"] == sy)]["Amount"].sum())
    dp_due = max(0.0, float(fees["dp"]) - paid_dp)
    if dp_due > 0 and remaining > 0:
        take = min(dp_due, remaining); alloc["DP"] = take; remaining -= take
        
    # Priority 2: Books
    paid_books = float(df_pay[(df_pay["Student_ID"] == sid) & (df_pay["Notes"] == "Books") & (df_pay["School_Year"] == sy)]["Amount"].sum())
    books_due = max(0.0, float(fees["books"]) - paid_books)
    if books_due > 0 and remaining > 0:
        take = min(books_due, remaining); alloc["Books"] = take; remaining -= take
        
    if remaining > 0: alloc["Monthly Tuition"] = remaining
    return alloc

# ==========================================
# 📊 MODULE: DASHBOARD
# ==========================================

def render_dashboard(df_reg, df_pay, sy):
    st.title(f"📊 ALSDI Dashboard • {sy}")
    sy_reg = df_reg[df_reg["School_Year"] == sy]
    sy_pay = df_pay[df_pay["School_Year"] == sy]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Students", len(sy_reg))
    c2.metric("Total Collections", f"₱{sy_pay['Amount'].sum():,.0f}")
    
    expected = sum([compute_total_fee(g) for g in sy_reg["Grade Level"]])
    receivables = expected - sy_pay['Amount'].sum()
    c3.metric("Receivables", f"₱{receivables:,.0f}")
    
    # Check if column exists to avoid error
    req_count = 0
    if "SF10 Status" in sy_reg.columns:
        req_count = len(sy_reg[sy_reg["SF10 Status"] == "Requested"])
    c4.metric("Registrar Requests", req_count)

    st.divider()
    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.subheader("Enrollment by Grade")
        if not sy_reg.empty:
            st.bar_chart(sy_reg["Grade Level"].value_counts())
    with col_b:
        st.subheader("Recent Payments")
        if not sy_pay.empty:
            st.dataframe(sy_pay[["Date", "Student_Name", "Amount"]].tail(5), hide_index=True)

# ==========================================
# 🎓 MODULE: REGISTRAR (VIEW / EDIT / ADD)
# ==========================================

def render_registrar(df_reg, df_sf10, sh_reg, sy):
    st.subheader(f"🎓 Admissions Portal ({sy})")
    t_list, t_add, t_sf10 = st.tabs(["📂 Master List & Edit", "📝 New Enrollment", "📜 Document Requests"])

    with t_list:
        c1, c2 = st.columns([2, 1])
        search = c1.text_input("🔍 Search Student Name")
        view_df = df_reg[df_reg["School_Year"] == sy]
        if search:
            view_df = view_df[view_df["Last Name"].str.contains(search, case=False, na=False) | view_df["First Name"].str.contains(search, case=False, na=False)]
        
        st.dataframe(view_df, use_container_width=True, hide_index=True)
        
        st.divider()
        st.markdown("### ✏️ Edit Student Record")
        # Ensure we filter list correctly
        valid_ids = view_df["Student_ID"].unique().tolist()
        selected_sid = st.selectbox("Select ID to Update", [""] + valid_ids)
        
        if selected_sid:
            # Get the exact row index from the ORIGINAL dataframe to match Google Sheets row number
            idx = df_reg[df_reg["Student_ID"] == selected_sid].index[0]
            stu = df_reg.iloc[idx]
            
            with st.form("edit_student"):
                ca, cb = st.columns(2)
                u_ln = ca.text_input("Last Name", value=stu["Last Name"])
                u_fn = cb.text_input("First Name", value=stu["First Name"])
                u_gr = ca.selectbox("Grade", GRADE_LEVELS, index=GRADE_LEVELS.index(stu["Grade Level"]) if stu["Grade Level"] in GRADE_LEVELS else 0)
                
                status_opts = ["Pending", "Enrolled", "Withdrawn"]
                curr_stat = stu["Current Status"] if stu["Current Status"] in status_opts else "Pending"
                u_st = cb.selectbox("Status", status_opts, index=status_opts.index(curr_stat))
                
                if st.form_submit_button("Save Changes"):
                    ws = sh_reg.worksheet("Student_Registry")
                    row = int(idx) + 2 # +2 because 1 for header, 1 for 0-index
                    ws.update(f"C{row}:D{row}", [[u_ln, u_fn]])
                    ws.update_cell(row, 6, u_gr)
                    ws.update_cell(row, 14, u_st)
                    st.success("Updated!"); st.cache_data.clear(); time.sleep(1); st.rerun()

    with t_add:
        with st.form("new_student"):
            st.markdown("#### 📝 Student Enrollment Form")
            ca, cb = st.columns(2)
            ln = ca.text_input("Last Name*")
            fn = cb.text_input("First Name*")
            lrn = ca.text_input("LRN")
            gr = cb.selectbox("Grade", GRADE_LEVELS)
            typ = ca.selectbox("Type", STUDENT_TYPES)
            
            if st.form_submit_button("Enroll Student"):
                nid = f"{sy[:4]}-{len(df_reg)+1:04d}"
                sh_reg.worksheet("Student_Registry").append_row([nid, lrn, ln, fn, "", gr, typ, "", "To Follow", "To Follow", "To Follow", "To Request", "FALSE", "Pending", sy])
                st.success(f"Enrolled {nid}"); st.cache_data.clear(); time.sleep(1); st.rerun()

    with t_sf10:
        st.dataframe(df_sf10, use_container_width=True)

# ==========================================
# 💰 MODULE: FINANCE
# ==========================================

def render_finance(df_reg, df_pay, df_sf10, sh_fin, sh_reg, sy):
    st.subheader(f"💰 Finance & Cashiering ({sy})")
    sy_reg = df_reg[df_reg["School_Year"] == sy]
    
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("### 💸 New Payment")
        choice = st.selectbox("Search Student", sy_reg.apply(lambda x: f"{x['Last Name']}, {x['First Name']} ({x['Student_ID']})", axis=1).tolist(), index=None)
        if choice:
            sid = choice.split("(")[-1].replace(")", "")
            stu = sy_reg[sy_reg["Student_ID"] == sid].iloc[0]
            total, paid, bal = get_financials(sid, stu["Grade Level"], df_pay, sy)
            
            st.info(f"**Balance:** ₱{bal:,.2f}")
            with st.form("cashier_form"):
                amt = st.number_input("Amount Paid", min_value=0.0)
                orn = st.text_input("OR Number")
                met = st.selectbox("Method", PAYMENT_METHODS)
                if st.form_submit_button("Post Transaction"):
                    allocs = distribute_payment(stu["Grade Level"], amt, df_pay, sid, sy)
                    ws = sh_fin.worksheet("Payments_Log")
                    for note, val in allocs.items():
                        ws.append_row([CURRENT_DATE, orn, sid, f"{stu['Last Name']}, {stu['First Name']}", val, met, note, "Payment", sy])
                    st.success("Posted!"); st.cache_data.clear(); time.sleep(1); st.rerun()

    with c2:
        if choice:
            st.markdown(f"### 📄 Statements")
            if st.button("Generate SOA PDF"):
                pdf = generate_soa_fixed(stu, total, paid, bal, sy)
                b64 = base64.b64encode(pdf).decode()
                st.markdown(f'<a href="data:application/octet-stream;base64,{b64}" download="SOA_{sid}.pdf">📥 Download Statement</a>', unsafe_allow_html=True)
            st.divider()
            st.markdown("### 📒 Payment History")
            st.dataframe(df_pay[df_pay["Student_ID"] == sid], hide_index=True)

# ==========================================
# 📄 PDF GENERATOR
# ==========================================

def generate_soa_fixed(student, total, paid, balance, sy):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "ABUNDANT LIFE SCHOOL OF DISCOVERY, INC.", 0, 1, "C")
    pdf.set_font("Arial", "I", 11)
    pdf.cell(0, 10, f"STATEMENT OF ACCOUNT (S.Y. {sy})", 0, 1, "C")
    
    # Safe Line Drawing (Below text)
    y = pdf.get_y() + 2
    pdf.line(10, y, 200, y)
    pdf.ln(10)
    
    pdf.set_font("Arial", "", 10)
    pdf.cell(100, 8, f"Student: {student['Last Name']}, {student['First Name']}", 0, 0)
    pdf.cell(0, 8, f"Grade: {student['Grade Level']}", 0, 1)
    pdf.cell(0, 8, f"Date: {datetime.now().strftime('%B %d, %Y')}", 0, 1)
    pdf.ln(5)

    pdf.set_fill_color(240, 240, 240); pdf.set_font("Arial", "B", 10)
    pdf.cell(140, 10, "Description", 1, 0, 'L', True); pdf.cell(50, 10, "Amount", 1, 1, 'C', True)
    
    pdf.set_font("Arial", "", 10)
    pdf.cell(140, 10, "Total School Fees", 1); pdf.cell(50, 10, f"{total:,.2f}", 1, 1, 'R')
    pdf.cell(140, 10, "Less: Payments", 1); pdf.cell(50, 10, f"({paid:,.2f})", 1, 1, 'R')
    pdf.set_font("Arial", "B", 11)
    pdf.cell(140, 10, "REMAINING BALANCE", 1); pdf.cell(50, 10, f"PHP {balance:,.2f}", 1, 1, 'R')
    
    # Footer Note
    pdf.ln(20)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(0, 10, "For any queries regarding this statement, please see the Accounting Officer", 0, 1, "C")
    
    return pdf.output(dest="S").encode("latin-1")

# ==========================================
# 🚀 AUTH & ENTRY POINT
# ==========================================

def main():
    if "logged_in" not in st.session_state: st.session_state.logged_in = False
    
    try:
        df_reg, df_sf10, df_pay, df_users, sh_reg, sh_fin = load_data()
    except Exception as e:
        st.error(f"System Error: {e}"); return

    if not st.session_state.logged_in:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            st.markdown("<h2 style='text-align:center;'>ALSDI MIS LOGIN</h2>", unsafe_allow_html=True)
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                sy = st.selectbox("School Year", SCHOOL_YEARS)
                if st.form_submit_button("Login", use_container_width=True):
                    # Check Secrets First
                    if u == st.secrets["auth"]["username"] and p == st.secrets["auth"]["password"]:
                        st.session_state.logged_in = True; st.session_state.role = "Admin"; st.session_state.sy = sy; st.rerun()
                    # Check DB Users Second
                    elif not df_users.empty:
                        row = df_users[df_users["Username"] == u]
                        if not row.empty and str(row.iloc[0]["Password"]) == p:
                            st.session_state.logged_in = True; st.session_state.role = row.iloc[0]["Role"]; st.session_state.sy = sy; st.rerun()
                        else: st.error("Invalid Credentials")
                    else: st.error("No users in DB")
    else:
        with st.sidebar:
            st.markdown(f"<div class='sidebar-school-name'>ALSDI MIS<br><small>{st.session_state.sy}</small></div>", unsafe_allow_html=True)
            st.divider()
            menu = ["📊 Dashboard"]
            if st.session_state.role in ["Registrar", "Admin"]: menu.append("🎓 Admissions")
            if st.session_state.role in ["Finance", "Admin"]: menu.append("💰 Finance")
            page = st.radio("Navigation", menu)
            if st.button("Logout"): st.session_state.logged_in = False; st.rerun()

        if page == "📊 Dashboard": render_dashboard(df_reg, df_pay, st.session_state.sy)
        elif page == "🎓 Admissions": render_registrar(df_reg, df_sf10, sh_reg, st.session_state.sy)
        elif page == "💰 Finance": render_finance(df_reg, df_pay, df_sf10, sh_fin, sh_reg, st.session_state.sy)

if __name__ == "__main__":
    main()
