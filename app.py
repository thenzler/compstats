"""Streamlit dashboard — comp win rates by map & tier."""
import streamlit as st
import pandas as pd
import analyse

st.set_page_config(page_title="CompStats", layout="wide")
st.title("Valorant Comp Stats")

# ── Sidebar filters ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    tiers = st.multiselect("Tier", ["T1", "T2", "T3", "GC"],
                           default=["T1", "T2", "T3", "GC"])

    import db
    con = db.connect()
    maps_raw = con.execute("SELECT DISTINCT map_name FROM map_results ORDER BY map_name").fetchall()
    map_options = ["All"] + [r["map_name"] for r in maps_raw]
    map_filter = st.selectbox("Map", map_options)
    map_name = None if map_filter == "All" else map_filter

    min_sample = st.slider("Min sample size", 5, 100, 20)

# ── Comp win rates ────────────────────────────────────────────────────────────
st.subheader("Composition win rates")

rows = analyse.comp_winrates(map_name=map_name, tiers=tiers or None)
df = pd.DataFrame(rows)

if df.empty:
    st.info("No data yet — run the scraper first.")
else:
    df = df[df["total"] >= min_sample]
    if map_name:
        df = df.drop(columns=["map"])

    st.dataframe(
        df.sort_values("win_pct", ascending=False)
          .style.background_gradient(subset=["win_pct"], cmap="RdYlGn", vmin=30, vmax=70)
          .format({"win_pct": "{:.1f}%"}),
        use_container_width=True, hide_index=True
    )

# ── Agent pick/win rates ──────────────────────────────────────────────────────
st.subheader("Agent pick & win rates")

agent_rows = analyse.agent_pickrates(map_name=map_name, tiers=tiers or None)
adf = pd.DataFrame(agent_rows)

if not adf.empty:
    adf = adf[adf["picks"] >= min_sample // 5]
    if map_name:
        adf = adf.drop(columns=["map"])

    col1, col2 = st.columns(2)
    with col1:
        st.caption("By pick rate")
        st.dataframe(
            adf.sort_values("picks", ascending=False).head(20)
               .style.format({"win_pct": "{:.1f}%"}),
            use_container_width=True, hide_index=True
        )
    with col2:
        st.caption("By win rate (min sample)")
        st.dataframe(
            adf[adf["picks"] >= min_sample // 3]
               .sort_values("win_pct", ascending=False).head(20)
               .style.format({"win_pct": "{:.1f}%"}),
            use_container_width=True, hide_index=True
        )

# ── DB stats ──────────────────────────────────────────────────────────────────
with st.expander("Database stats"):
    n_matches = con.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    n_maps    = con.execute("SELECT COUNT(*) FROM map_results").fetchone()[0]
    tier_counts = con.execute("SELECT tier, COUNT(*) as n FROM matches GROUP BY tier").fetchall()
    st.write(f"**{n_matches}** matches · **{n_maps}** map results")
    st.dataframe(pd.DataFrame([dict(r) for r in tier_counts]), hide_index=True)
