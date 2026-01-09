import streamlit as st
import pandas as pd
import gspread
import time

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Abundant Life Registrar", 
    page_icon="🎓", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CONFIGURATION CONSTANTS ---
# Must match your Google Sheet "Setup_Data" exactly
GRADE_LEVELS = [
    "Pre-K", "Kinder", "Grade 1", "Grade 2", "Grade 3", "Grade 4",
    "Grade 5", "Grade 6", "Grade 7", "Grade 8", "Grade 9", "Grade 10",
    "Grade 11", "Grade 12", "SPED"
]
STUDENT_TYPES = ["New Student", "Old / Continuing", "Transferee", "Returnee"]
DOC_STATUS_OPTS = ["Submitted", "To Follow", "On Process", "Not Applicable"]
SF10_STATUS_OPTS = ["To Request", "Request Sent", "2nd Follow-up", "Received", "Not Applicable"]

# --- GOOGLE DRIVE CONNECTION ---
@st.cache_resource
def get_connection():
    # Connects using the secret key stored in Streamlit Cloud
    return gspread.service_account_from_dict(st.secrets["gcp_service_account"])

def load_data(sheet_name):
    gc = get_connection()
    sh = gc.open(sheet_name)
    worksheet = sh.worksheet("Student_Registry")
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    
    # Force Student_ID and LRN to be strings (text) so they don't get treated as numbers
    if not df.empty:
        df['Student_ID'] = df['Student_ID'].astype(str)
        df['LRN'] = df['LRN'].astype(str)
    return df, worksheet

# --- MAIN APPLICATION ---
# REPLACE THIS WITH YOUR EXACT GOOGLE SHEET NAME
sheet_name_input = "Registrar 2025-2026" 

# SIDEBAR NAVIGATION
with st.sidebar:
    st.title("🎓 Registrar OS")
    st.caption("Abundant Life School of Discovery")
    st.divider()
    
    menu = st.radio(
        "Navigation", 
        ["👁️ View Profile", "📝 Enroll Student", "✏️ Update Record"],
        label_visibility="collapsed"
    )
    
    st.divider()
    st.info(f"Database: {sheet_name_input}")

try:
    df, ws = load_data(sheet_name_input)

    # ==========================================
    # MODE 1: VIEW PROFILE (Flexible Search)
    # ==========================================
    if menu == "👁️ View Profile":
        st.header("Student Profile Viewer")
        
        # SEARCH LOGIC: Combine Name + LRN + ID into one string
        search_list = df.apply(
            lambda x: f"{x['Last Name']}, {x['First Name']} | LRN: {x['LRN']} (ID: {x['Student_ID']})", 
            axis=1
        ).tolist()

        search_choice = st.selectbox("🔍 Find Student", search_list, placeholder="Type Name, LRN, or ID...", index=None)

        if search_choice:
            # Extract ID from the end of the string: "... (ID: 2026-001)"
            selected_id = search_choice.split("(ID: ")[-1].replace(")", "")
            student = df[df['Student_ID'] == selected_id].iloc[0]

            # VISUAL CARD
            with st.container(border=True):
                # Row 1: Header
                top_c1, top_c2, top_c3 = st.columns([2, 1, 1])
                with top_c1:
                    st.subheader(f"{student['Last Name']}, {student['First Name']} {student['Middle Name']}")
                    st.caption(f"LRN: {student['LRN']}")
                with top_c2:
                    st.metric("Grade", student['Grade Level'])
                with top_c3:
                    # Status Badge
                    if "Approved" in str(student['Current Status']):
                        st.success(f"✅ {student['Current Status']}")
                    else:
                        st.warning(f"⚠️ {student['Current Status']}")

                st.divider()

                # Row 2: Details
                d_c1, d_c2 = st.columns(2)
                with d_c1:
                    st.markdown("### 👤 **Student Details**")
                    st.text_input("Student Type", value=student['Student Type'], disabled=True)
                    st.text_input("Previous School", value=student['Previous School'], disabled=True)

                with d_c2:
                    st.markdown("### 📂 **Requirements**")
                    
                    def stat_badge(label, status):
                        color = "🟢" if status in ["Submitted", "Received"] else "🔴" if status == "To Follow" else "🟡"
                        st.markdown(f"{color} **{label}:** {status}")

                    stat_badge("PSA Birth Cert", student['PSA Birth Cert'])
                    stat_badge("Report Card", student['Report Card / ECCD'])
                    stat_badge("Good Moral", student['Good Moral'])
                    stat_badge("SF10 Status", student['SF10 Status'])
                    
                    p_icon = "✅" if str(student['Data Privacy Consent']).upper() == "TRUE" else "❌"
                    st.markdown(f"{p_icon} **Data Privacy Consent**")

    # ==========================================
    # MODE 2: ENROLL STUDENT (With Safety Guards)
    # ==========================================
    elif menu == "📝 Enroll Student":
        st.header("New Enrollment")
        st.caption("Please fill out all fields carefully. ID will be auto-generated.")

        with st.form("enroll_form", clear_on_submit=True):
            st.markdown("##### 1. Student Identity")
            c1, c2, c3 = st.columns(3)
            last_name = c1.text_input("Last Name")
            first_name = c2.text_input("First Name")
            middle_name = c3.text_input("Middle Name")
            
            st.markdown("##### 2. Academic Info")
            c4, c5, c6 = st.columns(3)
            lrn_input = c4.text_input("LRN (Leave blank for Pre-K if none)")
            grade_level = c5.selectbox("Grade Level", GRADE_LEVELS)
            student_type = c6.selectbox("Student Type", STUDENT_TYPES)

            # Hidden checklist to keep UI clean
            with st.expander("📂 Document Checklist (Click to Expand)", expanded=True):
                d1, d2, d3, d4 = st.columns(4)
                psa_stat = d1.selectbox("PSA Birth Cert", DOC_STATUS_OPTS)
                card_stat = d2.selectbox("Report Card", DOC_STATUS_OPTS)
                moral_stat = d3.selectbox("Good Moral", DOC_STATUS_OPTS)
                prev_school = d4.text_input("Previous School (Required for Transferees)")
                
                st.divider()
                sf10_stat = st.selectbox("SF10 Status", SF10_STATUS_OPTS)
                privacy_consent = st.checkbox("✅ I certify that the Data Privacy Consent is signed.")

            submit_btn = st.form_submit_button("💾 Save to Database", type="primary")

            if submit_btn:
                # --- GUARDRAIL 1: CLEANUP & CHECK ---
                clean_lrn = lrn_input.strip()
                
                # Check for Duplicate LRN (Only if LRN is not empty)
                lrn_exists = False
                if clean_lrn != "":
                    if clean_lrn in df['LRN'].astype(str).values:
                        lrn_exists = True

                # --- GUARDRAIL 2: BLOCKERS ---
                if student_type == "Transferee" and prev_school.strip() == "":
                    st.error("⛔ BLOCKER: Previous School is required for Transferees.")
                
                elif not last_name or not first_name:
                    st.error("⛔ BLOCKER: Last Name and First Name are required.")
                
                elif lrn_exists:
                    st.error(f"⛔ DUPLICATE DETECTED: The LRN '{clean_lrn}' is already registered in the system!")
                    st.warning("Please search for this student in 'View Profile' instead of creating a duplicate record.")

                else:
                    # ✅ ALL CLEAR - PROCEED TO SAVE
                    next_id = len(df) + 1
                    new_id = f"2026-{next_id:04d}"
                    
                    current_status = "Approved for Assessment" if privacy_consent else "Pending Consent"

                    # Prepare Row
                    row_data = [
                        new_id, clean_lrn, last_name, first_name, middle_name, grade_level,
                        student_type, prev_school, psa_stat, card_stat, moral_stat,
                        sf10_stat, "TRUE" if privacy_consent else "FALSE", current_status
                    ]
                    
                    # Send to Google Sheets
                    ws.append_row(row_data)
                    
                    st.toast(f"🎉 Student {first_name} enrolled! ID: {new_id}", icon="✅")
                    time.sleep(1) # Allow toast to display
                    st.cache_data.clear() # Refresh data

    # ==========================================
    # MODE 3: UPDATE RECORD (Edit Mode)
    # ==========================================
    elif menu == "✏️ Update Record":
        st.header("Update Records")
        st.warning("You are in Edit Mode. Changes are permanent.")

        # Updated Search Logic here too
        search_list = df.apply(
            lambda x: f"{x['Last Name']}, {x['First Name']} | LRN: {x['LRN']} (ID: {x['Student_ID']})", 
            axis=1
        ).tolist()
        
        search_choice = st.selectbox("Select Student to Edit", search_list, index=None)
        
        if search_choice:
            selected_id = search_choice.split("(ID: ")[-1].replace(")", "")
            student_data = df[df['Student_ID'] == selected_id].iloc[0]
            
            st.divider()
            
            with st.form("edit_form"):
                st.caption(f"Editing: {student_data['Last Name']}, {student_data['First Name']}")
                
                # Locked vs Editable Columns
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.markdown("#### 🔒 Locked Info")
                    st.text_input("Student ID", value=student_data['Student_ID'], disabled=True)
                    st.text_input("Last Name", value=student_data['Last Name'], disabled=True)
                
                with c2:
                    st.markdown("#### ✏️ Editable Info")
                    ec1, ec2 = st.columns(2)
                    # Helper to safely find list index
                    def get_index(options, value):
                        return options.index(value) if value in options else 0

                    edit_grade = ec1.selectbox("Grade Level", GRADE_LEVELS, index=get_index(GRADE_LEVELS, student_data['Grade Level']))
                    edit_type = ec2.selectbox("Student Type", STUDENT_TYPES, index=get_index(STUDENT_TYPES, student_data['Student Type']))
                    edit_prev = st.text_input("Previous School", value=student_data['Previous School'])

                st.divider()
                st.markdown("#### 📂 Document Status")
                d1, d2, d3, d4 = st.columns(4)
                edit_psa = d1.selectbox("PSA", DOC_STATUS_OPTS, index=get_index(DOC_STATUS_OPTS, student_data['PSA Birth Cert']))
                edit_card = d2.selectbox("Report Card", DOC_STATUS_OPTS, index=get_index(DOC_STATUS_OPTS, student_data['Report Card / ECCD']))
                edit_moral = d3.selectbox("Good Moral", DOC_STATUS_OPTS, index=get_index(DOC_STATUS_OPTS, student_data['Good Moral']))
                edit_sf10 = d4.selectbox("SF10", SF10_STATUS_OPTS, index=get_index(SF10_STATUS_OPTS, student_data['SF10 Status']))
                
                # Checkbox Logic
                is_checked = True if str(student_data['Data Privacy Consent']).upper() == "TRUE" else False
                edit_privacy = st.toggle("Data Privacy Consent Signed", value=is_checked)

                update_btn = st.form_submit_button("🔄 Update Record", type="primary")
                
                if update_btn:
                    if edit_type == "Transferee" and edit_prev.strip() == "":
                        st.error("Previous School is missing for Transferee.")
                    else:
                        # Find Row in Sheet
                        row_idx = df[df['Student_ID'] == selected_id].index[0] + 2
                        
                        calc_status = "Approved for Assessment" if edit_privacy else "Pending Consent"
                        
                        # Reconstruct Row
                        updated_row = [
                            student_data['Student_ID'], student_data['LRN'], student_data['Last Name'],
                            student_data['First Name'], student_data['Middle Name'], edit_grade,
                            edit_type, edit_prev, edit_psa, edit_card, edit_moral, edit_sf10,
                            "TRUE" if edit_privacy else "FALSE", calc_status
                        ]
                        
                        # Update Sheet
                        cell_range = f"A{row_idx}:N{row_idx}"
                        ws.update(range_name=cell_range, values=[updated_row])
                        
                        st.toast("✅ Record Updated Successfully!")
                        time.sleep(1)
                        st.cache_data.clear()

except Exception as e:
    st.error(f"Connection Error: {e}")
    st.info("Please check if your Google Sheet name is correct and shared with the service account.")