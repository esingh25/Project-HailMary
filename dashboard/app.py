"""Streamlit management dashboard (DESIGN.md §5 Phase 5).

Panels: (a) ingestion health, (b) query traces, (c) cache stats, (d) cost,
(e) controls. Reads Postgres/Redis directly; never mutates report content.

Run with: uv run streamlit run dashboard/app.py

Not automatically tested (PLAN.md's stated testing strategy excludes
Streamlit visuals) — dashboard/queries.py's data-fetching functions are
unit-tested instead; this script is a thin rendering layer over them.
"""

import asyncio

import streamlit as st

from dashboard.queries import (
    get_cache_stats,
    get_ingestion_health,
    get_odds_budget,
    get_query_trace,
)
from hailmary.clients.postgres import get_pg_connection
from hailmary.config import get_settings

st.set_page_config(page_title="HailMaryRAG Dashboard", layout="wide")
st.title("HailMaryRAG — Management Dashboard")

settings = get_settings()

if settings.replay_mode:
    st.info("REPLAY MODE — reading fixture-derived data, no live feeds.")


@st.cache_resource
def _pg_connection():
    return asyncio.new_event_loop().run_until_complete(get_pg_connection(settings))


pg = _pg_connection()

tab_ingestion, tab_traces, tab_cache, tab_cost, tab_controls = st.tabs(
    ["Ingestion Health", "Query Traces", "Cache Stats", "Cost", "Controls"]
)

with tab_ingestion:
    st.subheader("Last run per source")
    health = asyncio.run(get_ingestion_health(pg))
    if health:
        st.table(health)
    else:
        st.info("No ingestion_log rows yet — run the ingestion worker first.")

with tab_traces:
    st.subheader("Query event timeline")
    query_id = st.text_input("Query ID")
    if query_id:
        trace = asyncio.run(get_query_trace(pg, query_id))
        if trace:
            st.table(trace)
        else:
            st.info("No events found for that query_id.")

with tab_cache:
    st.subheader("Semantic cache")
    stats = asyncio.run(get_cache_stats(pg))
    col1, col2, col3 = st.columns(3)
    col1.metric("Total entries", stats["total"])
    col2.metric("Hit rate", f"{stats['hit_rate']:.0%}")
    col3.metric("Avg age (s)", f"{stats['avg_age_seconds']:.0f}")

with tab_cost:
    st.subheader("Cost & budget")
    budget = asyncio.run(get_odds_budget(pg))
    if budget:
        st.metric(
            "Odds API calls remaining",
            budget["remaining"],
            help=f"{budget['calls_used']}/{budget['calls_limit']} used this period",
        )
    else:
        st.info("No Odds API budget row yet.")
    st.caption(
        f"Per-query cap: ${settings.cost.per_query_usd_cap:.2f} | "
        f"Per-day cap: ${settings.cost.per_day_usd_cap:.2f}"
    )

with tab_controls:
    st.subheader("Controls")
    st.toggle(
        "Replay mode",
        value=settings.replay_mode,
        disabled=True,
        help="Set via the REPLAY_MODE env var — not live-togglable in this MVP.",
    )
    if st.button("Trigger manual ingestion (replay)"):
        st.info(
            "Wired to ingestion.scheduler.run_replay_ingestion_pass in a full "
            "deployment; not executed from this button in the MVP dashboard."
        )
    st.text_input(
        "Tighten odds cadence for game (game_id)",
        disabled=True,
        help="Not yet wired — M8 live mode.",
    )
