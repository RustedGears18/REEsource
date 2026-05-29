import streamlit as st
from PIL import Image

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="REEsource | Mineral Data Pipeline",
    page_icon="📈", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- HEADER SECTION ---
st.title("REEsource")
st.markdown("#### *Unearthing tomorrow's critical mineral supply.*")

# --- SIDEBAR CONTROLS ---
with st.sidebar:
    # Safely load and display the logo from the assets folder
    try:
        logo = Image.open("assets/REEsource brand light.png") # Update this filename to match your actual image
        st.image(logo, use_container_width=True)
    except FileNotFoundError:
        st.warning("Logo image not found in assets folder.")

    st.header("Pipeline Parameters")
    
    # State selection
    selected_state = st.selectbox("Select Target State", ["Colorado", "Wyoming", "Nevada", "Texas"])
    
    st.divider()
    
    # Synthetic data governance
    st.subheader("Data Governance")
    include_synthetic = st.toggle("Include Synthetic Baselines", value=False, help="Integrate generated data (Gaussian Copulas) where physical assays are missing.")
    
    st.divider()
    
    # Cache management
    st.button("Refresh State Data", type="primary", use_container_width=True)

# --- MAIN DASHBOARD LAYOUT ---
# ... (Keep the rest of your layout code identical below this point)