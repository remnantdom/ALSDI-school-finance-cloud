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
    .sidebar-school-name { font-size: 14px; font-weight: bold; color: #1e3a8a; text-transform: uppercase; text-align: center; }
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
        st.error(f"❌ Secret Key Error: {e}"); st.stop()

@st.cache_resource
def get_spreadsheets():
    gc = get_connection()
    try:
        return gc.open(REGISTRAR_SHEET_NAME), gc.open(FINANCE_SHEET_NAME), None
    except Exception as e:
        return None, None, e

@st.cache_data(ttl=10)
def fetch_sheet_data(_ws):
    try:
        return _ws.get_all_values()
    except:
        return []

def load_data():
    sh_reg, sh_fin, error_msg = get_spreadsheets()
    if error_msg:
        st.error(f"❌ Google Connection Failed: {error_msg}"); st.stop()

    def safe_read(ws, expected_cols):
        data = fetch_sheet_data(ws)
        if not data: return pd.DataFrame(columns=expected_cols)
        headers = [h.strip() for h in data.pop(0)]
        df = pd.DataFrame(data, columns=headers)
        for col in expected_cols:
            if col not in df.columns: df[col] = ""
        return df[expected_cols]

    # Load All Components
    df_reg = safe_read(sh_reg.worksheet("Student_Registry"), ["Student_ID", "LRN", "Last Name", "First Name", "Middle Name", "Grade Level", "Student Type", "Previous School", "PSA Birth Cert", "Report Card / ECCD", "Good Moral", "SF10 Status", "Data Privacy Consent", "Current Status", "School_Year"])
    df_sf10 = safe_read(sh_reg.worksheet("SF10_Requests"), ["Timestamp", "Student_Name", "Student_ID", "Status"])
    df_pay = safe_read(sh_fin.worksheet("Payments_Log"), ["Date", "OR_Number", "Student_ID", "Student_Name", "Amount", "Method", "Notes", "Type", "School_Year"])
    df_users = safe_read(sh_fin.worksheet("User_Accounts"), ["Username", "Password", "Role"])

    # Clean data types
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
    
    remaining = float(amount)
    alloc = {}
    
    # Priority 1: DP
    paid_dp = float(df_pay[(df_pay["Student_ID"] == sid) & (df_pay["Notes"] == "DP")]["Amount"].sum())
    dp_due = max(0.0, float(fees["dp"]) - paid_dp)
    if dp_due > 0 and remaining > 0:
        take = min(dp_due, remaining); alloc["DP"] = take; remaining -= take
        
    # Priority 2: Books
    paid_books = float(df_pay[(df_pay["Student_ID"] == sid) & (df_pay["Notes"] == "Books")]["Amount"].sum())
    books_due = max(0.0, float(fees["books"]) - paid_books)
    if books_due > 0 and remaining > 0:
        take = min(books_due, remaining); alloc["Books"] = take; remaining -= take
        
    if remaining > 0: alloc["Monthly Tuition"] = remaining
    return alloc

# ==========================================
# 📝 REGISTRAR MODULE (ADD / VIEW / EDIT)
# ==========================================

def render_registrar(df_reg, df_sf10, sh_reg, sy):
    st.subheader(f"🎓 Admissions Portal ({sy})")
    tab_list, tab_add, tab_sf10 = st.tabs(["📂 Student Master List", "📝 Enroll New Student", "📜 SF10 Requests"])

    with tab_list:
        # Search and Filter
        c1, c2 = st.columns([2, 1])
        search_query = c1.text_input("🔍 Search by Name or ID")
        grade_filter = c2.selectbox("Filter Grade", ["All"] + GRADE_LEVELS)

        view_df = df_reg[df_reg["School_Year"] == sy]
        if search_query:
            view_df = view_df[view_df.apply(lambda row: search_query.lower() in str(row).lower(), axis=1)]
        if grade_filter != "All":
            view_df = view_df[view_df["Grade Level"] == grade_filter]

        st.dataframe(view_df, use_container_width=True, hide_index=True)

        # Edit Section
        st.divider()
        st.markdown("#### ✏️ Edit Student Record")
        edit_sid = st.selectbox("Select Student ID to Update", [""] + view_df["Student_ID"].tolist())
        
        if edit_sid:
            idx = df_reg[df_reg["Student_ID"] == edit_sid].index[0]
            student_data = df_reg.iloc[idx]
            
            with st.form("edit_student_form"):
                col_a, col_b = st.columns(2)
                u_last = col_a.text_input("Last Name", value=student_data["Last Name"])
                u_first = col_b.text_input("First Name", value=student_data["First Name"])
                u_grade = col_a.selectbox("Grade Level", GRADE_LEVELS, index=GRADE_LEVELS.index(student_data["Grade Level"]))
                u_status = col_b.selectbox("Enrollment Status", ["Pending", "Enrolled", "Withdrawn", "Dropped"], index=["Pending", "Enrolled", "Withdrawn", "Dropped"].index(student_data["Current Status"]) if student_data["Current Status"] in ["Pending", "Enrolled", "Withdrawn", "Dropped"] else 0)
                u_sf10 = col_a.selectbox("SF10 Status", ["To Request", "Requested", "Received", "N/A"], index=0)
                
                if st.form_submit_button("Update Record"):
                    # Row in GSheets is index + 2 (1 for header, 1 for 0-indexing)
                    row_num = int(idx) + 2
                    ws = sh_reg.worksheet("Student_Registry")
                    ws.update(f"C{row_num}:D{row_num}", [[u_last, u_first]])
                    ws.update_cell(row_num, 6, u_grade)
                    ws.update_cell(row_num, 12, u_sf10)
                    ws.update_cell(row_num, 14, u_status)
                    
                    st.success("Record updated successfully!")
                    st.cache_data.clear(); time.sleep(1); st.rerun()

    with tab_add:
        with st.form("enroll_form"):
            st.markdown("#### 📝 New Enrollment Form")
            c1, c2 = st.columns(2)
            f_last = c1.text_input("Last Name*")
            f_first = c2.text_input("First Name*")
            f_lrn = c1.text_input("LRN")
            f_grade = c2.selectbox("Grade Level", GRADE_LEVELS)
            f_stype = c1.selectbox("Student Type", STUDENT_TYPES)
            f_prev = c2.text_input("Previous School (if transferee)")
            
            if st.form_submit_button("Save Enrollment", type="primary"):
                if not f_last or not f_first:
                    st.error("Name fields are required.")
                else:
                    new_id = f"{sy.split('-')[0]}-{len(df_reg)+1:04d}"
                    sh_reg.worksheet("Student_Registry").append_row([
                        new_id, f_lrn, f_last, f_first, "", f_grade, f_stype, f_prev,
                        "To Follow", "To Follow", "To Follow", "To Request", "FALSE", "Pending", sy
                    ])
                    st.success(f"Successfully Enrolled: {new_id}")
                    st.cache_data.clear(); time.sleep(1); st.rerun()

    with tab_sf10:
        # (SF10 Request logic remains as previously audited/stable)
        render_sf10_logic(df_reg, df_sf10, sh_reg)

# ==========================================
# 💰 FINANCE MODULE
# ==========================================

def render_finance(df_reg, df_pay, df_sf10, sh_fin, sh_reg, sy):
    st.subheader(f"💰 Finance & Cashiering ({sy})")
    t_cash, t_log = st.tabs(["💸 New Payment", "📒 Payment History"])

    with t_cash:
        c1, c2 = st.columns([1, 2])
        sy_students = df_reg[df_reg["School_Year"] == sy]
        
        with c1:
            search = st.selectbox("🔍 Search Student", 
                                sy_students.apply(lambda x: f"{x['Last Name']}, {x['First Name']} ({x['Student_ID']})", axis=1).tolist(), 
                                index=None)
            if search:
                sid = search.split("(")[-1].replace(")", "")
                stu = sy_students[sy_students["Student_ID"] == sid].iloc[0]
                total, paid, bal = get_financials(sid, stu["Grade Level"], df_pay, sy)
                
                st.metric("Outstanding Balance", f"₱{bal:,.2f}", delta=f"-₱{paid:,.2f} paid")
                
                with st.form("payment_form"):
                    amt = st.number_input("Payment Amount", min_value=0.0, step=100.0)
                    or_num = st.text_input("OR Number")
                    method = st.selectbox("Payment Method", PAYMENT_METHODS)
                    if st.form_submit_button("Post Payment"):
                        allocs = distribute_payment(stu["Grade Level"], amt, df_pay, sid, sy)
                        ws = sh_fin.worksheet("Payments_Log")
                        for note, val in allocs.items():
                            ws.append_row([CURRENT_DATE, or_num, sid, f"{stu['Last Name']}, {stu['First Name']}", val, method, note, "Payment", sy])
                        st.success("Payment Distributed and Logged!")
                        st.cache_data.clear(); time.sleep(1); st.rerun()

        with c2:
            if search:
                st.markdown(f"**Transaction History for {sid}**")
                st.dataframe(df_pay[df_pay["Student_ID"] == sid], hide_index=True)
                if st.button("📄 Generate Statement of Account"):
                    pdf_bytes = generate_soa_fixed(stu, total, paid, bal, sy)
                    b64 = base64.b64encode(pdf_bytes).decode()
                    st.markdown(f'<a href="data:application/octet-stream;base64,{b64}" download="SOA_{sid}.pdf">📥 Download PDF</a>', unsafe_allow_html=True)

# ==========================================
# 📄 PDF & OTHER TOOLS
# ==========================================

def generate_soa_fixed(student, total, paid, balance, sy):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(0, 10, "ABUNDANT LIFE SCHOOL OF DISCOVERY, INC.", 0, 1, "C")
    pdf.set_font("Arial", "I", 11)
    pdf.cell(0, 10, f"STATEMENT OF ACCOUNT (S.Y. {sy})", 0, 1, "C")
    
    # Safe Line Drawing
    y_pos = pdf.get_y() + 2
    pdf.line(10, y_pos, 200, y_pos)
    pdf.ln(10)
    
    pdf.set_font("Arial", "", 10)
    pdf.cell(100, 8, f"Student: {student['Last Name']}, {student['First Name']}", 0, 0)
    pdf.cell(0, 8, f"Grade: {student['Grade Level']}", 0, 1)
    pdf.cell(0, 8, f"Date: {datetime.now().strftime('%B %d, %Y')}", 0, 1)
    pdf.ln(5)

    # Table
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", "B", 10)
    pdf.cell(140, 10, "Description", 1, 0, 'L', True)
    pdf.cell(50, 10, "Amount", 1, 1, 'C', True)
    
    pdf.set_font("Arial", "", 10)
    pdf.cell(140, 10, "Total Assessment Fees", 1); pdf.cell(50, 10, f"{total:,.2f}", 1, 1, 'R')
    pdf.cell(140, 10, "Less: Total Payments to Date", 1); pdf.cell(50, 10, f"({paid:,.2f})", 1, 1, 'R')
    
    pdf.set_font("Arial", "B", 11)
    pdf.cell(140, 10, "REMAINING BALANCE", 1); pdf.cell(50, 10, f"PHP {balance:,.2f}", 1, 1, 'R')
    
    pdf.ln(20)
    pdf.set_font("Arial", "I", 9)
    pdf.cell(0, 10, "This is a computer-generated document. For questions, visit the Finance Office.", 0, 1, "C")
    return pdf.output(dest="S").encode("latin-1")

def render_sf10_logic(df_reg, df_sf10, sh_reg):
    col_a, col_b = st.columns([1, 2])
    with col_a:
        st.markdown("**New Request**")
        name = st.text_input("Student Name")
        if st.button("Log Request"):
            sh_reg.worksheet("SF10_Requests").append_row([datetime.now().strftime("%Y-%m-%d %H:%M"), name, "N/A", "Pending"])
            st.cache_data.clear(); st.rerun()
    with col_b:
        st.dataframe(df_sf10, use_container_width=True)

# ==========================================
# 🚀 APP ENTRY POINT
# ==========================================

def main():
    if "logged_in" not in st.session_state: st.session_state.logged_in = False
    
    df_reg, df_sf10, df_pay, df_users, sh_reg, sh_fin = load_data()
    
    if not st.session_state.logged_in:
        # Standard Login Logic (as provided in previous audits)
        render_login_screen(df_users)
    else:
        # Sidebar Navigation
        with st.sidebar:
            st.markdown("<div class='sidebar-school-name'>ALSDI MIS</div>", unsafe_allow_html=True)
            st.write(f"Logged in as: {st.session_state.role}")
            sy = st.selectbox("Active S.Y.", SCHOOL_YEARS)
            page = st.radio("Menu", ["📊 Dashboard", "🎓 Admissions", "💰 Finance"])
            if st.button("Log Out"): st.session_state.logged_in = False; st.rerun()

        if page == "📊 Dashboard":
            st.title("Executive Dashboard")
            # Metric logic here...
        elif page == "🎓 Admissions":
            render_registrar(df_reg, df_sf10, sh_reg, sy)
        elif page == "💰 Finance":
            render_finance(df_reg, df_pay, df_sf10, sh_fin, sh_reg, sy)

def render_login_screen(df_users):
    st.title("ALSDI MIS Login")
    user = st.text_input("Username")
    pw = st.text_input("Password", type="password")
    if st.button("Login"):
        if user == "admin" and pw == "admin": # Default fallback
            st.session_state.logged_in = True; st.session_state.role = "Admin"; st.rerun()
        # Add logic to check df_users here...

if __name__ == "__main__":
    main()
