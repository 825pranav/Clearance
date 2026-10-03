"""One-page Streamlit dashboard: request counts, the request table, an audit trail and the latest eval scores.

Run with: streamlit run dashboard/app.py
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402

st.set_page_config(page_title="Clearance", layout="wide")
st.title("Clearance")
st.caption("Access requests filed by the agent. The agent files and routes requests; it never grants access.")

requests = pd.DataFrame(db.list_requests())

if requests.empty:
    st.info("No requests yet. Run `make chat` or message the Slack bot to file one.")
else:
    by_status, by_risk = st.columns(2)
    by_status.subheader("By status")
    by_status.bar_chart(requests["status"].value_counts())
    by_risk.subheader("By risk tier")
    by_risk.bar_chart(requests["risk_tier"].value_counts())

    st.subheader("Requests")
    requests["approvers"] = requests["approvers"].apply(lambda a: ", ".join(f"{x['role']}: {x['email']}" for x in a))
    st.dataframe(
        requests[["id", "created_at", "employee_name", "system_key", "access_level", "risk_tier", "status",
                  "approvers", "gitlab_issue_url"]],
        column_config={"gitlab_issue_url": st.column_config.LinkColumn("Issue")},
        hide_index=True, use_container_width=True,
    )

    st.subheader("Audit trail")
    request_id = st.selectbox("Request", requests["id"].tolist())
    trail = pd.DataFrame(db.audit_for(int(request_id)))
    if not trail.empty:
        trail["detail"] = trail["detail"].apply(json.dumps)
    st.dataframe(trail, hide_index=True, use_container_width=True)

st.subheader("Latest eval scores")
results_path = ROOT / "evals" / "results.json"
if not results_path.exists():
    st.info("No eval results yet. Run `make eval`.")
else:
    results = json.loads(results_path.read_text(encoding="utf-8"))
    cols = st.columns(4)
    if "main" in results:
        main = results["main"]
        cols[0].metric(f"Main suite ({main['model']})", f"{main['passed']}/{main['total']}")
        cols[1].metric("Safety violations", main["safety_violations"])
    if "adversarial" in results:
        adv = results["adversarial"]
        cols[2].metric("Adversarial harm", f"{adv['harm']}/{adv['total']}", help=f"Fooled in {adv['fooled']}/{adv['total']}")
    if "retrieval" in results:
        cols[3].metric("Retrieval top-3", f"{results['retrieval']['hits']}/{results['retrieval']['total']}")
    if "main" in results:
        st.dataframe(pd.DataFrame([{"category": c, **v} for c, v in results["main"]["by_category"].items()]),
                     hide_index=True)
