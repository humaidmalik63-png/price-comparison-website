"""PriceWise AI: Main Streamlit Application Entrypoint.
Academic Project - Price Comparison Website with Real Deal Detector.
Phase 7: User Accounts, Wishlist & Personalization.
"""

from pathlib import Path
import streamlit as st
from src.config import (
    APP_NAME,
    APP_TAGLINE,
    APP_VERSION,
    DATABASE_PATH,
    DEMO_BADGE_LABEL,
    DEMO_USER_EMAIL,
    DEMO_USER_PASSWORD,
    validate_session_secret_configuration,
)
from src.database.connection import migrate_db
from src.database.seed import seed_database
from src.ui.styles import CUSTOM_CSS
from src.ui.components import render_demo_banner
from src.ui.views.home_view import render_home_view
from src.ui.views.comparison_view import render_comparison_view
from src.ui.views.advisor_view import render_advisor_view
from src.ui.views.wishlist_view import render_wishlist_view
from src.ui.views.tracking_view import render_tracking_view
from src.ui.views.preferences_view import render_preferences_view
from src.ui.views.about_view import render_about_view
from src.services.auth_service import authenticate_user, register_user
from src.services.wishlist_service import get_wishlist_count
from src.services.price_tracking_service import get_alert_history

# Phase 14 Stage 2.5 (FIX 1): refuse to run when the session signing secret
# is not configured in a secured environment (production / staging). In
# development an ephemeral per-process secret is used instead.
validate_session_secret_configuration()

# Streamlit Page Configuration
st.set_page_config(
    page_title=f"{APP_NAME} - Indian Beauty & Skincare Intelligence",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject Modern Dashboard Styles
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def ensure_database_ready():
    """Ensure SQLite database is created, migrated, and seeded with demo data."""
    db_file = Path(DATABASE_PATH)
    if not db_file.exists():
        seed_database(force=True, seed_demo_user=True)
    else:
        migrate_db()


ensure_database_ready()

# Initialize Session State
if "current_view" not in st.session_state:
    st.session_state["current_view"] = "home"

if "selected_product_id" not in st.session_state:
    st.session_state["selected_product_id"] = None

if "authenticated_user" not in st.session_state:
    st.session_state["authenticated_user"] = None


# Sidebar Navigation & Controls
with st.sidebar:
    st.markdown(
        f"""
        <div style="padding: 10px 0 20px 0;">
            <div style="font-size: 1.45rem; font-weight: 800; color: #302724; display: flex; align-items: center; gap: 8px;">
                ✨ {APP_NAME}
            </div>
            <div style="font-size: 0.76rem; color: #78665f; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 2px;">
                Indian Beauty Intelligence
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### Navigation")

    nav_options = {
        "home": "🛍️ Product Catalog",
        "advisor": "🧭 Smart Purchase Advisor",
        "comparison": "📊 Store Comparison",
        "wishlist": "💖 My Wishlist",
        "tracking": "🔔 Price Tracker",
        "preferences": "⚙️ Shopping Preferences",
        "about": "ℹ️ Project & Methodology",
    }

    # Ensure view matches current option
    if st.session_state["current_view"] not in nav_options:
        st.session_state["current_view"] = "home"

    current_idx = list(nav_options.keys()).index(st.session_state["current_view"])

    selected_nav = st.radio(
        "Navigate",
        options=list(nav_options.keys()),
        format_func=lambda k: nav_options[k],
        index=current_idx,
        label_visibility="collapsed",
        key="nav_radio",
    )

    if selected_nav != st.session_state["current_view"]:
        st.session_state["current_view"] = selected_nav
        st.rerun()

    # User Account Section in Sidebar
    st.markdown("---")
    st.markdown("### 👤 User Account")
    user = st.session_state.get("authenticated_user")

    if user:
        wish_count = get_wishlist_count(user.id)
        unread_alerts_count = len(get_alert_history(user_id=user.id, unread_only=True))
        st.markdown(
            f"""
            <div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                <div style="font-size: 0.88rem; font-weight: 700; color: #0f172a;">
                    {user.full_name or 'Member'}
                </div>
                <div style="font-size: 0.75rem; color: #64748b; margin-bottom: 8px;">
                    {user.email}
                </div>
                <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                    <span style="background: #fdf2f8; color: #db2777; font-size: 0.72rem; font-weight: 600; padding: 2px 6px; border-radius: 6px;">💖 {wish_count} Saved</span>
                    <span style="background: #eff6ff; color: #2563eb; font-size: 0.72rem; font-weight: 600; padding: 2px 6px; border-radius: 6px;">🔔 {unread_alerts_count} Alerts</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("🚪 Sign Out", key="sidebar_sign_out_btn", use_container_width=True):
            st.session_state["authenticated_user"] = None
            st.session_state.pop("sidebar_login_pass", None)
            st.toast("Signed out successfully.")
            st.rerun()
    else:
        with st.expander("🔐 Sign In / Register", expanded=False):
            auth_mode = st.radio(
                "Mode",
                ["Sign In", "Create Account"],
                label_visibility="collapsed",
                horizontal=True,
                key="auth_tab_radio",
            )
            if auth_mode == "Sign In":
                st.markdown(
                    f"""
                    <div style="font-size: 0.72rem; color: #475569; background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 6px; padding: 6px 8px; margin-bottom: 8px;">
                        <strong>Demo Login:</strong><br/>
                        <code>{DEMO_USER_EMAIL}</code> / <code>{DEMO_USER_PASSWORD}</code>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("⚡ Quick Fill Demo Login", key="btn_quick_demo_login", use_container_width=True):
                    auth_user, auth_msg = authenticate_user(DEMO_USER_EMAIL, DEMO_USER_PASSWORD)
                    if auth_user:
                        st.session_state["authenticated_user"] = auth_user
                        st.toast("Signed in as Demo User!")
                        st.rerun()
                    else:
                        st.info("Demo user not initialized. Click 'Reset / Re-seed Demo DB' below.")

                login_email = st.text_input("Email", key="sidebar_login_email", placeholder="you@example.com")
                login_pass = st.text_input("Password", type="password", key="sidebar_login_pass")
                if st.button("Sign In", key="sidebar_btn_login", use_container_width=True, type="primary"):
                    auth_user, auth_msg = authenticate_user(login_email, login_pass)
                    if auth_user:
                        st.session_state["authenticated_user"] = auth_user
                        st.toast(f"Welcome back, {auth_user.full_name or auth_user.email}!")
                        st.rerun()
                    else:
                        st.error(auth_msg)
            else:
                reg_name = st.text_input("Full Name (Optional)", key="sidebar_reg_name", placeholder="Alex Smith")
                reg_email = st.text_input("Email", key="sidebar_reg_email", placeholder="you@example.com")
                reg_pass = st.text_input("Password", type="password", key="sidebar_reg_pass")
                if st.button("Register", key="sidebar_btn_register", use_container_width=True, type="primary"):
                    ok, reg_msg, new_user = register_user(
                        email=reg_email,
                        password=reg_pass,
                        display_name=reg_name.strip() if reg_name else "Shopper",
                    )
                    if ok and new_user:
                        st.session_state["authenticated_user"] = new_user
                        st.toast("Account created successfully!")
                        st.rerun()
                    else:
                        st.error(reg_msg)

    st.markdown("---")

    # React Modern Frontend Portal
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #FAF7F2 0%, #F5EAEB 100%); border: 1px solid #EED4D8; border-radius: 8px; padding: 12px; margin-bottom: 16px;">
            <div style="font-size: 0.72rem; font-weight: 700; color: #4A1D2F; text-transform: uppercase; letter-spacing: 0.05em;">
                ✨ Editorial Frontend
            </div>
            <div style="font-size: 0.8rem; color: #574d49; margin-top: 4px; margin-bottom: 8px;">
                Experience the high-fashion React 19 UI with luxury typography & dupe comparisons.
            </div>
            <a href="http://localhost:5173" target="_blank" style="display: block; text-align: center; background: #4A1D2F; color: #FAF7F2; padding: 6px 12px; border-radius: 6px; font-size: 0.78rem; font-weight: 700; text-decoration: none;">
                Open PriceWise Beauty UI ↗
            </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Demo Environment Management
    st.markdown(
        f"""
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 16px;">
            <div style="font-size: 0.72rem; font-weight: 700; color: #f59e0b; text-transform: uppercase; letter-spacing: 0.05em;">
                Academic Dataset
            </div>
            <div style="font-size: 0.8rem; color: #475569; margin-top: 4px;">
                Preloaded with 11 products, 5 demo stores, and 90-day timestamped price observation trails.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("🔄 Reset / Re-seed Demo DB", use_container_width=True):
        seed_database(force=True, seed_demo_user=True)
        st.success("Database re-seeded with demo data.")
        st.rerun()

    st.markdown(
        f"""
        <div style="font-size: 0.72rem; color: #94a3b8; text-align: center; margin-top: 30px;">
            {APP_NAME} v{APP_VERSION}<br/>Academic Prototype Final Release (Phase 8)
        </div>
        """,
        unsafe_allow_html=True,
    )


# Top Demo Banner (Global)
render_demo_banner()

# Main View Dispatcher
if st.session_state["current_view"] == "home":
    render_home_view()
elif st.session_state["current_view"] == "advisor":
    render_advisor_view()
elif st.session_state["current_view"] == "comparison":
    render_comparison_view()
elif st.session_state["current_view"] == "wishlist":
    render_wishlist_view()
elif st.session_state["current_view"] == "tracking":
    render_tracking_view()
elif st.session_state["current_view"] == "preferences":
    render_preferences_view()
elif st.session_state["current_view"] == "about":
    render_about_view()
