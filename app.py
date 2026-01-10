import streamlit as st
import pandas as pd
import gspread
import time
from fpdf import FPDF
import base64
from datetime import datetime

# --------------------------------------------------
# PAGE CONFIG
# --------------------------------------------------
st.set_page_config(
    page_title="ALSDI MIS",
    page_icon="🏫",
    layout="wide"
)

# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------
REGISTRAR_SHEET_NAME = "Registrar 2025-2026"
FINANCE_SHEET_NAME = "Finance 2025-2026"

SCHOOL_YEARS = ["2025-2026", "2026-2027", "2027-2028"]
CURRENT_DATE = datetime.now().strftime("%Y-%m-%d")

MONTHLY_MONTHS = 10

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

GRADE_LEVELS = list(FEE_STRUCTURE.keys())
STUDENT_TYPES = ["New Student", "Old / Continuing", "Transferee", "Returnee"]
PAYMENT_METHODS = ["Cash", "GCash", "Bank Transfer", "Check"]

# --------------------------------------------------
# GOOGLE CONNECTION
# --------------------------------------------------
@st.cache_resource
def get_connection():
    return gspread.service_account_from_dict(st.secrets["gcp_service_account"])

@st.cache_resource
def get_spreadsheets():
    gc = get_connection()
    return gc.open(REGISTRAR_SHEET_NAME), gc.open(FINANCE_SHEET_NAME)

@st.cache_data(ttl=5)
def fetch_sheet(ws):
    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()
    headers = data.pop(0)
    return pd.DataFrame(data, columns=headers)

# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------
def load_data():
    sh_reg, sh_fin = get_spreadsheets()

    ws_reg = sh_reg.worksheet("Student_Registry")
    ws_pay = sh_fin.worksheet("Payments_Log")
    ws_users = sh_fin.worksheet("User_Accounts")

    df_reg = fetch_sheet(ws_reg)
    df_pay = fetch_sheet(ws_pay)
    df_users = fetch_sheet(ws_users)

    if not df_reg.empty:
        df_reg["Student_ID"] = df_reg["Student_ID"].astype(str)
        df_reg["School_Year"] = df_reg["School_Year"].replace("", SCHOOL_YEARS[0])

    if not df_pay.empty:
        df_pay["Amount"] = pd.to_numeric(df_pay["Amount"], errors="coerce").fillna(0)

    return df_reg, df_pay, df_users, sh_reg, sh_fin

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def compute_total_fee(grade):
    f = FEE_STRUCTURE.get(grade)
    if not f:
        return 0
    return f["dp"] + f["books"] + f["monthly"] * MONTHLY_MONTHS

# --------------------------------------------------
# REGISTRAR MODULE (FIXED)
# --------------------------------------------------
def render_registrar(df_reg, sh_reg, sy):
    st.subheader(f"🎓 Admissions ({sy})")
    sy_reg = df_reg[df_reg["School_Year"] == sy]

    t1, t2, t3 = st.tabs(["📝 Enroll Student", "✏️ Edit Students", "📂 Master List"])

    # -----------------------------
    # ADD STUDENT
    # -----------------------------
    with t1:
        with st.form("add_student"):
            c1, c2 = st.columns(2)
            last = c1.text_input("Last Name")
            first = c2.text_input("First Name")
            grade = c1.selectbox("Grade Level", GRADE_LEVELS)
            stype = c2.selectbox("Student Type", STUDENT_TYPES)

            if st.form_submit_button("Save Student"):
                nid = f"{sy.split('-')[0]}-{len(sy_reg)+1:04d}"
                sh_reg.worksheet("Student_Registry").append_row([
                    nid, "", last, first, "", grade, stype, "",
                    "To Follow", "To Follow", "To Follow",
                    "To Request", "FALSE", "Pending", sy
                ])
                st.success("Student added")
                st.cache_data.clear()
                st.rerun()

    # -----------------------------
    # EDIT STUDENTS (FIXED)
    # -----------------------------
    with t2:
        st.markdown("### ✏️ Edit Student Records")

        edited_df = st.data_editor(
            sy_reg,
            disabled=["Student_ID", "School_Year"],
            use_container_width=True
        )

        if st.button("💾 Save Changes"):
            ws = sh_reg.worksheet("Student_Registry")
            ws.batch_clear(["A2:Z"])
            ws.append_rows(
                edited_df.astype(str).values.tolist(),
                value_input_option="USER_ENTERED"
            )
            st.success("Changes saved")
            st.cache_data.clear()
            st.rerun()

    # -----------------------------
    # VIEW ONLY
    # -----------------------------
    with t3:
        st.dataframe(sy_reg, use_container_width=True)

# --------------------------------------------------
# MAIN APP
# --------------------------------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.sy = SCHOOL_YEARS[0]

df_reg, df_pay, df_users, sh_reg, sh_fin = load_data()

if not st.session_state.logged_in:
    st.title("ABUNDANT LIFE SCHOOL OF DISCOVERY, INC.")
    with st.form("login"):
        user = st.text_input("Username")
        pwd = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            st.session_state.logged_in = True
            st.rerun()
else:
    with st.sidebar:
        st.caption("Admissions System")
        st.selectbox("School Year", SCHOOL_YEARS, key="sy")

    render_registrar(df_reg, sh_reg, st.session_state.sy)
