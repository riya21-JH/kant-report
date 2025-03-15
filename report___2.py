import streamlit as st
import psycopg2
import pandas as pd
import datetime
import base64
import os
from dotenv import load_dotenv
import re
from concurrent.futures import ThreadPoolExecutor

# st.set_page_config(layout="wide")

st.markdown("""
    <style>
        .block-container {
            padding-top: 30px; 
        }
    </style>
""", unsafe_allow_html=True)


st.markdown(
    """
    <style>
        div[data-testid="stButton"] button {
            padding: 1px 5px !important; /* Adjust padding as needed */
            font-size: 30px !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


st.markdown(
    """
    <style>
        /* Reduce spacing between rows of images */
        div[data-testid="stImage"] {
            margin-bottom: 0px !important;
            padding-bottom: 0px !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

load_dotenv()

# Database connection details
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_PORT = os.getenv("DB_PORT")



# Function to connect to PostgreSQL
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        st.error(f"Database connection failed: {e}")
        return None

# Fetch school IDs for a specific date
@st.cache_resource
def get_school_ids_for_date(selected_date):
    conn = get_db_connection()
    if conn:
        try:
            query = """
                SELECT DISTINCT "School ID" FROM kant.form_response_data 
                WHERE DATE("Timestamp") = %s
                ORDER BY "School ID"
            """
            cursor = conn.cursor()
            cursor.execute(query, (selected_date,))
            school_ids = [row[0] for row in cursor.fetchall()]
            cursor.close()
            conn.close()

            with ThreadPoolExecutor() as executor:
                school_data = {sid: fetch_data(sid, selected_date) for sid in school_ids}
            # priority_scores = {sid: calculate_school_priority(school_data[sid]) for sid in school_ids}
            priority_scores = {sid: list(calculate_school_priority(school_data[sid]).values())[0] for sid in school_ids}


            sorted_school_ids = sorted(school_ids, key=lambda sid: priority_scores.get(sid, float('inf')))

            return sorted_school_ids

            # return school_ids
        except Exception as e:
            st.error(f"Error fetching School IDs: {e}")
            return []
    return []



# Fetch data for a specific school ID and date
@st.cache_resource
def fetch_data(school_id, selected_date):
    conn = get_db_connection()
    if conn:
        try:
            query = """
                SELECT * FROM kant.form_response_data 
                WHERE "School ID" = %s AND DATE("Timestamp") = %s
                ORDER BY "Timestamp" 
            """
            df = pd.read_sql(query, conn, params=(school_id, selected_date))
            conn.close()

            df['Timestamp'] = pd.to_datetime(df['Timestamp'])  # Convert to datetime if needed
            df = df.sort_values(by='Timestamp', ascending=True)  # Ensure sorting
            df = df.drop_duplicates(subset=['School ID', 'Class', 'Section'], keep='first')
            return df
        
        except Exception as e:
            st.error(f"Error fetching data: {e}")
            return pd.DataFrame()
    return pd.DataFrame()


def calculate_school_priority(df):
    """ Categorizes school IDs into different lists based on image processing """
    prev_is_green = False
    prev_is_orange = False
    prev_timestamp = None
    prev_uploaded_by = None

    priority_scores = {}

    for _, row in df.iterrows():
        school_id = row['School ID']
        image_path = row['Class_pic']
        uploaded_by = row['uploaded_by']
        timestamp = row['Timestamp']
    

        if not os.path.exists(image_path):
            continue  # Skip if image does not exist

        filename = os.path.basename(image_path)
        file_size = round(os.path.getsize(image_path)/1024, 2)
        file_date = extract_date_from_filename(filename)
        db_timestamp = datetime.strptime(str(timestamp), "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")


        if prev_timestamp:
            time_diff = (timestamp - prev_timestamp).total_seconds() / 60  # Convert to minutes
        else:
            time_diff = None

        is_green = False
        is_orange = False
        priority = float('inf')


        if file_date and db_timestamp and file_date != db_timestamp:
            priority = min(priority, 1)
        
        elif "Screenshot" in filename:
            priority = min(priority, 2)

        elif file_size == 0:
            priority = min(priority, 3)
        
        else:
            is_orange = True




        # RULE 2 : for live images
        # difference between timestamps < 10
        # same uploaded by value


        if "image - " in filename or re.search(r'\d{25,}', filename):
            is_green = True


            if prev_is_green and time_diff is not None and time_diff < 10:
                priority = min(priority, 4)


            elif uploaded_by == prev_uploaded_by:
                priority = min(priority, 5)



        
        # RULE 3: for uploaded pictures
        # same uploaded by for > 1 image
        # time diff < 10


        if prev_is_orange and is_orange:
            if uploaded_by == prev_uploaded_by:
                priority = min(priority, 6)


            elif time_diff is not None and time_diff < 10:
                priority = min(priority, 7)

            
        if priority == float('inf'):
                priority = 8

        priority_scores[school_id] = priority

                
        prev_timestamp = timestamp
        prev_is_green = is_green  # Store `is_green` for the next iteration
        prev_is_orange = is_orange
        prev_uploaded_by = uploaded_by

    
    return priority_scores
        

def get_base64_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode()


def check_misreporting(row):
    class_str = str(row["Class"]).strip()
    class_list = [int(cls.strip()) for cls in class_str.split(",") if cls.strip().isdigit()]

    if not class_list:
        return False, "Invalid Class Data", []

    films = []
    for film_field in ["Film 1", "Film 2", "Film 3"]:
        film_value = row.get(film_field, None)
        if pd.isna(film_value):
            films.append(0)
        else:
            try:
                films.append(int(film_value))
            except ValueError:
                films.append(0)

    issues_dict = {
        "too_old": [],
        "higher_class": [],
        "duplicate": False
    }

    misreported_films = []  # Store films that are misreported

    if len([f for f in films if f != 0]) == 3 and len(set(films)) < 3:
        issues_dict["duplicate"] = True

    for film in films:
        if film == 0:
            continue
        film_class = film // 10

        valid_for_any_class = any(
            (film_class == cls or (cls - film_class <= 2 and film_class <= cls))
            for cls in class_list
        )

        if not valid_for_any_class:
            # misreported_films.append(film)  # Store misreported films
            
            # if film_class - max(class_list) > 1:
            if any(film_class - cls > 1 for cls in class_list):
                issues_dict["higher_class"].append(film)
                misreported_films.append(film)

            if any(cls - film_class > 2 for cls in class_list):
                issues_dict["too_old"].append(film)
                misreported_films.append(film)

    issues = []

    if issues_dict["duplicate"]:
        issues.append("Duplicate films detected")
    
    if issues_dict["too_old"]:
        issues.append(f"Film {', '.join(map(str, issues_dict['too_old']))} too old for this class.")

    if issues_dict["higher_class"]:
        issues.append(f"Film {', '.join(map(str, issues_dict['higher_class']))} too high for this class")

    if issues:
        return False, issues, misreported_films  # Returning misreported films
    return True, "", []


def add_to_suspect_list(row, issues):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # Create table if it does not exist
            create_table_query = """
            CREATE TABLE IF NOT EXISTS kant.suspect_list 
            (LIKE kant.form_response_data INCLUDING DEFAULTS INCLUDING CONSTRAINTS);
            """
            cursor.execute(create_table_query)

            # Add Issues column if it does not exist
            add_issues_column_query = """
            ALTER TABLE kant.suspect_list ADD COLUMN IF NOT EXISTS "Issues" TEXT;
            """
            cursor.execute(add_issues_column_query)

            # Insert the record into suspect_list with issues column
            insert_query = f"""
            INSERT INTO kant.suspect_list ({', '.join(f'"{col}"' for col in row.index)}, "Issues") 
            VALUES ({', '.join(['%s'] * len(row))}, %s)
            """
            cursor.execute(insert_query, tuple(row) + (", ".join(issues) if issues else "",))

            # Remove duplicate records, keeping only the latest Timestamp per School ID
            remove_duplicates_query = """
            DELETE FROM kant.suspect_list
            WHERE ctid NOT IN (
                SELECT DISTINCT ON ("School ID", "Timestamp") ctid
                FROM kant.suspect_list
                ORDER BY "School ID", "Timestamp" DESC
            );
            """
            cursor.execute(remove_duplicates_query)

            conn.commit()
            cursor.close()
            st.toast("Record added to suspect list successfully!", icon="✅")

        except Exception as e:
            st.error(f"Error adding record to suspect list: {e}")
        finally:
            conn.close()


from datetime import datetime

# def remove_from_suspect_list(school_id, timestamp):
    # conn = get_db_connection()
    # if conn:
    #     try:
    #         cursor = conn.cursor()

    #         # Ensure timestamp is a datetime object (convert if it's a string)
    #         if isinstance(timestamp, str):
    #             timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")

    #         delete_query = """
    #         DELETE FROM kant.suspect_list 
    #         WHERE "School ID" = %s AND "Timestamp" = %s::timestamp;
    #         """
    #         cursor.execute(delete_query, (school_id, timestamp))

    #         conn.commit()
    #         cursor.close()
    #         st.toast("Record removed from suspect list successfully!", icon="❌")

    #     except Exception as e:
    #         st.error(f"Error removing record from suspect list: {e}")
    #     finally:
    #         conn.close()


def remove_from_suspect_list(school_id, timestamp):
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()

            # Ensure timestamp is a string (if it's a datetime object, convert it to string)
            if isinstance(timestamp, datetime):
                timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")

            delete_query = """
            DELETE FROM kant.suspect_list 
            WHERE "School ID" = %s AND "Timestamp" = %s;
            """
            cursor.execute(delete_query, (school_id, timestamp))

            conn.commit()
            cursor.close()
            st.toast("Record removed from suspect list successfully!", icon="❌")

        except Exception as e:
            st.error(f"Error removing record from suspect list: {e}")
        finally:
            conn.close()



# Fetch School Name based on School ID
def get_school_name(school_id):
    conn = get_db_connection()
    if conn:
        try:
            query = """
                SELECT "SCHOOL" FROM kant."doe_school_list" 
                WHERE "SCHOOL ID" = %s
            """

            cursor = conn.cursor()
            cursor.execute(query, (school_id,))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            return result[0] if result else "Unknown School"
        except Exception as e:
            st.error(f"Error fetching School Name: {e}")
            return "Unknown School"
    return "Unknown School"




from datetime import datetime

def extract_date_from_filename(basename):
    patterns = [
        r'^(\d{8})_\d{6}',        # Matches: "20250305_170517 - Usha Kumari.jpg"
        r'^IMG_(\d{8})_\d{6}',    # Matches: "IMG_20250305_144929 - Ravi Gujjar.jpg"
        r'^IMG(\d{14})',          # Matches: "IMG20250305141842 - R. Sanwat.jpg"
        r'^(\d{8})\s-\s',         # Matches: "20250219 - Seema Gaur.jpg"
        r'^(\d{8})'               # NEW: Matches "20250305 followed by anything - name.jpg"
    ]

    for pattern in patterns:
        match = re.search(pattern, basename)
        if match:
            date_str = match.group(1)

            try:
                if len(date_str) == 8:  # YYYYMMDD format
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                elif len(date_str) == 14:  # YYYYMMDDHHMMSS format
                    file_date = datetime.strptime(date_str[:8], "%Y%m%d")

                return file_date.strftime("%Y-%m-%d")  # Format as M/D/YYYY
            
            except ValueError:
                return None  # Ignore invalid dates

    return None  # No date found




# # Streamlit UI
# st.title("📊 Kant Daily Report")

# # Date Picker for selecting date
# selected_date = st.date_input("Select Date")


def show():

    if "page" not in st.session_state:
        st.session_state.page = "home"  # Default page

    if st.session_state.page == "report":
        if st.button("⬅ Back to Home"):
            st.session_state.page = "home"
            st.rerun()  # Refresh page to reflect the change


    # col1, col2 = st.columns([3, 1])  # Adjust column widths as needed

    # with col1:
    #     st.title("📊 Kant Daily Report")

    # with col2:
    selected_date = st.session_state.get("selected_date", None)


    # Initializing session state for navigation buttons
    if 'last_selected_date' not in st.session_state:
        st.session_state['last_selected_date'] = selected_date
    if 'current_index' not in st.session_state:
        st.session_state['current_index'] = 0

    # Reset index when a new date is selected
    if selected_date != st.session_state['last_selected_date']:
        st.session_state['current_index'] = 0
        st.session_state['last_selected_date'] = selected_date

    # Fetch school IDs for the selected date
    if selected_date:
        school_ids = get_school_ids_for_date(selected_date)

        if school_ids:




            current_index = st.session_state['current_index']
            total_schools = len(school_ids)
            current_school_id = school_ids[current_index]
            school_name = get_school_name(current_school_id)

            # Layout: School ID text first, then navigation buttons on the same line
            col1, col2, col3, col4, col5 = st.columns([5, 1, 1, 1, 1])

            with col1:
                st.write(f"##### School ID: {current_school_id} | School: {school_name}")

            with col2:
                if st.button("PREV", key="prev") and st.session_state['current_index'] > 0:
                    st.session_state['current_index'] -= 1
                    st.rerun()

            with col3:
                if st.button("NEXT", key="next") and st.session_state['current_index'] < len(school_ids) - 1:
                    st.session_state['current_index'] += 1
                    st.rerun()

            with col4:
                st.write(f"**{current_index + 1} / {total_schools}**")

            with col5:
                st.write(f"***{selected_date}***")

            # Fetch and display data for the current school ID
            data = fetch_data(current_school_id, selected_date)



            # col1, col2, col3 = st.columns([2, 2, 2])

            # with col1:
            #     if st.button("Previous") and st.session_state['current_index'] > 0:
            #         st.session_state['current_index'] -= 1

            # with col2:
            #     if st.button("Next") and st.session_state['current_index'] < len(school_ids) - 1:
            #         st.session_state['current_index'] += 1

            # with col3:
            # # Display the counter: Current School ID and Total School IDs
            #     current_index = st.session_state['current_index']
            #     total_schools = len(school_ids)
            #     print(f"total_schools: {total_schools}")
            #     st.write(f"{current_index + 1} / {total_schools}")

            # # Fetch and display data for the current school ID
            # current_school_id = school_ids[current_index]
            # data = fetch_data(current_school_id, selected_date)


            if not data.empty:
                class_sections = ", ".join(f"{row['Class']}{row['Section']}" for _, row in data.iterrows())

                # Fetch School Name
                school_name = get_school_name(current_school_id)

                # Display School Name instead of just School ID
                # st.write(f"##### School ID: {current_school_id} | School: {school_name}")


                cols = st.columns(4)  # Adjust the number based on how many images per row you want
                
                prev_timestamp = None
                prev_is_green = False  # Track if the previous image had a green border
                prev_uploaded_by = None  # To track the "uploaded by" field of the previous row
                prev_is_orange = False

                for index, (i, row) in enumerate(data.iterrows()):
                    image_path = row["Class_pic"]
                    image_path = os.path.abspath(os.path.normpath(image_path.strip()))

                    if os.path.exists(image_path):
                        base64_image = get_base64_image(image_path)  # comment this for st.image
                        file_size = round(os.path.getsize(image_path) / 1024, 2)
                        # print(file_size)

                        is_valid, issues, misreported_films = check_misreporting(row)

                        issue_message = ", ".join(issues) if not is_valid else "No issues"
                        basename = os.path.basename(image_path)
                        # print(basename)

                        file_date = extract_date_from_filename(basename)
                        db_timestamp = datetime.strptime(str(row['Timestamp']), "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")

                        is_green = False
                        is_orange = False

                        if "image - " in basename or re.search(r'\d{25,}', basename):
                            border_style = "border: 5px solid #32CD32; border-radius: 8px"
                            is_green = True

                        elif "Screenshot" in basename or (file_date and db_timestamp and file_date != db_timestamp) or file_size == 0:
                            border_style = "border: 5px solid red; border-radius: 8px"
                        
                        else:
                            border_style = "border: 5px solid orange; border-radius: 8px"
                            is_orange = True

                        col_index = index % 4  # Ensures wrapping after 3 images
                        with cols[col_index]:  # Uses a proper grid layout

                            st.markdown(
                                f"""
                                <div style="padding: 0px; {border_style}; text-align: center; display: inline-block;">
                                <img src="data:image/jpeg;base64,{base64_image}" width="300" height="200" 
                                style="object-fit: cover; border-radius: 4px; display: block">
                                </div>
                                """, unsafe_allow_html=True)

                            timestamp = row['Timestamp'].to_pydatetime()  # Convert to Python datetime object
                            time_diff = None
                            time_diff_style = ""
                            style=""

                            if prev_timestamp is not None:
                                time_diff = round((timestamp - prev_timestamp).total_seconds() / 60, 2)
                                time_diff_text = f"{time_diff}"
                            else:
                                time_diff_text = ""

                                            
                            if prev_is_green and is_green:
                                if time_diff is not None and time_diff < 10:
                                    time_diff_style = "color: red;"
                                
                                elif row["uploaded_by"] == prev_uploaded_by:
                                    style = "color: red;" 


                            if prev_is_orange and is_orange:
                                if time_diff is not None and time_diff < 10:
                                    time_diff_style = "color: red;"

                                if time_diff is not None and time_diff < 10 or row["uploaded_by"] == prev_uploaded_by:
                                    style = "color: red;"


                            films = [row['Film 1'], row['Film 2'], row['Film 3']]
                            formatted_films = [
                                f'<span style="color: red;"><b>{film}</b></span>' if film in misreported_films else str(film)
                                for film in films
                            ]
                            film_display = ", ".join(formatted_films)

                            # st.markdown(f"""
                            #     <div style="width: 300px; display: flex; justify-content: space-between; margin-top: 5px; gap: 10px">
                            #         <p style="margin: 0; font-size: 14px;">{timestamp.strftime("%H:%M:%S")}</p>
                            #         <p style="margin: 0; font-size: 14px;  margin-right: 15px; {time_diff_style}"><b>{time_diff_text}</b></p>
                            #     </div>
                            #     <p style="margin-bottom: -2px;"><b>Class:</b> {row['Class']}{row['Section']} &nbsp;&nbsp;&nbsp&nbsp&nbsp&nbsp; {film_display}</p>
                            #     <p style="margin-bottom: -2px;"><b>Uploaded By: </b> <span style = "{style}">{row['uploaded_by']}</span></p>
                            # """, unsafe_allow_html=True)



                            st.markdown(f"""
                        <div style="width: 300px; display: flex; justify-content: space-between; margin-top: 5px; gap: 10px">
                            <p style="margin: 0; font-size: 14px;">{timestamp.strftime("%H:%M:%S")}</p>
                            <p style="margin: 0; font-size: 14px; margin-right: 15px; {time_diff_style} line-height: 1.2;">
                                <b>{time_diff_text}</b>
                            </p>
                        </div>
                        <p style="margin: 0; font-size: 14px; line-height: 1.2;"><b>Class:</b> {row['Class']}{row['Section']} &nbsp;&nbsp;&nbsp; {film_display}</p>
                        <p style="margin: 0; font-size: 14px; line-height: 1.2;"><b>Uploaded By:</b> <span style="{style}">{row['uploaded_by']}</span></p>
                    """, unsafe_allow_html=True)
                            
                            btn1, btn2 = st.columns([1, 1])
                            with btn1:           
                                if st.button(f"ADD", key=f"suspect_{index}", help="Add to suspect list"):
                                    add_to_suspect_list(row, issues)

                            with btn2:
                                if st.button("REM", key=f"rem_{index}", help="Remove from suspect list"):
                                    remove_from_suspect_list(current_school_id, timestamp)

                            st.write("")

                        # ✅ Update previous values for next iteration
                        prev_timestamp = timestamp
                        prev_is_green = is_green  # Store `is_green` for the next iteration
                        prev_uploaded_by = row["uploaded_by"]
                        prev_is_orange = is_orange
                

                    else:
                        st.warning(f"Image not found: {image_path}")
            else:
                st.warning("No data found for the selected criteria.")
        else: 
            st.warning("No school data found for the selected date.")
    else:
        st.error("Please select a date.")