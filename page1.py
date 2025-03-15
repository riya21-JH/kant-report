# import streamlit as st

# # st.set_page_config(layout="centered")

# # Initialize session state for navigation
# if "page" not in st.session_state:
#     st.session_state.page = "home"

# # Function to change page
# def navigate_to(page):
#     st.session_state.page = page
#     st.rerun()  # Ensure UI updates after page change

# # Display content based on selected page
# if st.session_state.page == "home":
#     st.title("📊 Kant Daily Report")

#     # Date Picker for selecting date
#     selected_date = st.date_input("Select Date")

#     # Update page when button is clicked
#     if st.button("Go"):
#         navigate_to("report___2")

# elif st.session_state.page == "report___2":
#     # Redirect to report___2.py
#     import report___2
#     report___2.show()

#     # Add a "Back" button to return to home
#     if st.button("Back"):
#         navigate_to("home")



import streamlit as st

st.set_page_config(layout="wide")

# Initialize session state for navigation
if "page" not in st.session_state:
    st.session_state.page = "home"

# Initialize session state for selected date
if "selected_date" not in st.session_state:
    st.session_state.selected_date = None

# Function to change page
def navigate_to(page):
    st.session_state.page = page
    st.rerun()  # Ensure UI updates after page change

# Display content based on selected page
if st.session_state.page == "home":
    st.title("📊 Kant Daily Report")

    # Date Picker for selecting date
    selected_date = st.date_input("Select Date")  # User selects a date
    st.session_state.selected_date = selected_date  # Store selected date in session state

    # Update page when button is clicked
    if st.button("Go"):
        navigate_to("report___2")

elif st.session_state.page == "report___2":
    # Redirect to report___2.py
    import report___2
    report___2.show()

    # Add a "Back" button to return to home
    if st.button("Back"):
        navigate_to("home")
