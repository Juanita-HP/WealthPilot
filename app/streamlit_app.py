"""WealthPilot - quick demo interface (Streamlit).

Run:  streamlit run app/streamlit_app.py
Simulation only: no real transactions, not financial advice.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wealthpilot import advocate, data, goals as gl, lab, metrics, profile as pf, risks, strategist  # noqa: E402
from wealthpilot import news, ticker as tk, time_machine as tm, whatif  # noqa: E402

st.set_page_config(page_title="WealthPilot", page_icon="🧭", layout="wide")

QUESTION_FR = {
    "horizon": "Quand aurez-vous besoin de la majeure partie de cet argent ?",
    "income_stability": "Votre revenu est-il stable ?",
    "emergency_fund": "Combien de mois de dépenses avez-vous de côté pour les imprévus ?",
    "wealth_share": "Quelle part de votre épargne totale ce placement représente-t-il ?",
    "dependents": "D'autres personnes dépendent-elles de votre revenu ?",
    "drop_reaction": "Vos placements perdent 20 % en quelques mois. Que faites-vous ?",
    "range_choice": "Quelle fourchette de résultats sur un an accepteriez-vous ?",
    "goal": "Quel est votre objectif principal ?",
    "experience": "Votre expérience en placement ?",
    "return_expectation": "Quel rendement annuel moyen espérez-vous ?",
}
RISK_FR = {"market": "Marché", "credit": "Crédit", "liquidity": "Liquidité", "currency": "Devise",
           "concentration": "Concentration", "inflation": "Inflation"}
LEVEL_COLOR = {"low": "🟢", "moderate": "🟡", "high": "🔴"}
PERSONAS = {
    "— Mes réponses —": None,
    "Amira (26 ans, risque élevé)": (dict(horizon="gt15", income_stability="stable", emergency_fund="3to6",
                                          wealth_share="25to50", dependents="none", drop_reaction="buy_more",
                                          range_choice="D", goal="max_growth", experience="intermediate",
                                          return_expectation="7to10"),
                                     dict(crypto="open", region="global", themes=["Information Technology"])),
    "Mateo (41 ans, modéré, ESG)": (dict(horizon="5to10", income_stability="stable", emergency_fund="3to6",
                                         wealth_share="25to50", dependents="some", drop_reaction="hold",
                                         range_choice="B", goal="balanced", experience="intermediate",
                                         return_expectation="5to7"),
                                    dict(esg="exclude", values=["no_fossil_fuels"])),
    "Robert (59 ans, prudent)": (dict(horizon="3to5", income_stability="stable", emergency_fund="gt6",
                                      wealth_share="50to75", dependents="none", drop_reaction="hold",
                                      range_choice="C", goal="preserve", experience="advanced",
                                      return_expectation="5to7"), {}),
}


@st.cache_data(show_spinner=False)
def load():
    px = data.load_prices_cad()
    vol = risks.average_dollar_volume(data.load_prices("close"), data.load_prices("volume"))
    return px, data.load_prices(), data.load_universe(), vol


@st.cache_data(show_spinner=False)
def cpi():
    try:
        return data.load_macro_history("V41690973", point_in_time=False)
    except FileNotFoundError:
        return None


px_cad, px_local, universe, dollar_vol = load()
pct = lambda x: "—" if x is None else f"{x:.1%}"  # noqa: E731

st.title("🧭 WealthPilot")
st.caption("Simulation éducative (Datathon PolyFinances 2026). Aucune transaction réelle, pas un conseil financier. "
           "Chaque chiffre vient d'un calcul vérifiable sur des données publiques.")

tabs = st.tabs(["1 · Profil", "2 · Objectifs", "3 · Machine à remonter le temps", "4 · Titre", "5 · Labo",
                "6 · Avocat du diable"])

# ----------------------------------------------------------------------------- 1. profile
with tabs[0]:
    left, right = st.columns([3, 2])
    with left:
        persona = st.selectbox("Partir d'un persona du cas", list(PERSONAS))
        preset, preset_prefs = PERSONAS[persona] or ({}, {})
        answers = {}
        with st.expander("Questionnaire (10 questions)", expanded=persona == "— Mes réponses —"):
            for q in pf.QUESTIONS:
                codes = [o.code for o in q.options]
                default = codes.index(preset[q.id]) if q.id in preset else len(codes) // 2
                answers[q.id] = st.radio(QUESTION_FR[q.id], codes, index=default, horizontal=True,
                                         format_func=lambda c, q=q: q.option(c).label, key=f"q_{q.id}_{persona}")
        with st.expander("Préférences (appliquées à l'intérieur des contraintes)", expanded=False):
            c1, c2 = st.columns(2)
            esg = c1.selectbox("ESG", ["none", "prefer", "exclude"], index=["none", "prefer", "exclude"].index(
                preset_prefs.get("esg", "none")), key=f"esg_{persona}")
            crypto = c2.selectbox("Crypto", ["no", "small", "open"], index=["no", "small", "open"].index(
                preset_prefs.get("crypto", "no")), key=f"cr_{persona}")
            region = c1.selectbox("Région", list(pf.REGION_HOME_SHARE), index=list(pf.REGION_HOME_SHARE).index(
                preset_prefs.get("region", "balanced")), key=f"rg_{persona}")
            values = c2.multiselect("Valeurs", list(pf.VALUES), default=preset_prefs.get("values", []), key=f"v_{persona}")
            simplicity = c1.checkbox("Je préfère peu de fonds, simples", key=f"s_{persona}")
            themes = c2.multiselect("Thèmes d'intérêt", ["Information Technology"],
                                    default=preset_prefs.get("themes", []), key=f"t_{persona}")
    prefs = pf.Preferences(esg=esg, crypto=crypto, region=region, values=tuple(values), simplicity=simplicity,
                           themes=tuple(themes))
    profile = pf.build_profile(answers, prefs)
    st.session_state["profile"] = profile
    with right:
        card = pf.level_card(profile.level)
        st.subheader(f"{card['fr']} · {card['score_10']}/10")
        st.progress(card["score_10"] / 10)
        st.write(f"Pour : {card['for']}. Actions : **{card['stocks']}**, crypto max **{card['max_crypto']:.0%}**, "
                 f"un titre max **{card['max_single_security']:.1%}**.")
        a, b = st.columns(2)
        a.metric("Capacité de risque", f"{profile.capacity:.0f}/100", help="Objective : horizon, revenu, coussin, part du patrimoine, personnes à charge")
        b.metric("Tolérance au risque", f"{profile.tolerance:.0f}/100", help="Psychologique : réaction à une baisse, fourchette acceptée, objectif")
        st.caption("Le niveau suit la plus basse des deux.")
        for f in profile.flags:
            (st.warning if f.severity == "warning" else st.info)(f.message)
        tips = whatif.profile_tipping_points(profile)
        if tips:
            st.markdown("**Ce qui changerait votre niveau**")
            for t in tips:
                st.write("• " + t.condition + " → " + t.effect)
        lower = st.select_slider("Choisir un niveau plus prudent (jamais plus risqué)",
                                 options=list(range(1, profile.level + 1)), value=profile.level)
        if lower != profile.level:
            profile, msg = pf.choose_level(profile, lower)
            st.session_state["profile"] = profile
            st.success(f"Niveau appliqué : {pf.level_card(lower)['fr']}")

profile = st.session_state["profile"]

# ----------------------------------------------------------------------------- 2. goals
with tabs[1]:
    st.markdown("Un portefeuille, plusieurs objectifs : **chaque objectif a son horizon**, donc son propre "
                "sous-portefeuille et son compte suggéré.")
    default_goals = pd.DataFrame([
        {"name": "Coussin d'urgence", "type": "emergency_fund", "horizon_years": 0.0, "target_amount": 15000.0,
         "current_amount": 15000.0, "monthly_contribution": 0.0},
        {"name": "Mise de fonds", "type": "home_purchase", "horizon_years": 4.0, "target_amount": 60000.0,
         "current_amount": 30000.0, "monthly_contribution": 500.0},
        {"name": "Retraite", "type": "retirement", "horizon_years": 25.0, "target_amount": 800000.0,
         "current_amount": 90000.0, "monthly_contribution": 600.0},
    ])
    edited = st.data_editor(default_goals, num_rows="dynamic", width="stretch", column_config={
        "type": st.column_config.SelectboxColumn("type", options=list(gl.GOAL_TYPES))})
    specs = [gl.GoalSpec(r["name"], r["type"], float(r["horizon_years"]), float(r["target_amount"]),
                         float(r["current_amount"]), float(r["monthly_contribution"]))
             for _, r in edited.dropna(subset=["name", "type"]).iterrows()]
    if specs:
        plan = gl.plan(profile, specs, px_cad)
        st.session_state["plan"] = plan
        cols = st.columns(len(plan.goals))
        for col, g in zip(cols, plan.goals):
            with col:
                st.markdown(f"### {g.goal.name}")
                st.caption(f"{g.level_name} · horizon {g.goal.horizon_years:g} an(s)")
                st.write(f"**Compte suggéré :** {g.account}")
                st.caption(g.account_why)
                fig = go.Figure(go.Pie(labels=list(g.weights), values=list(g.weights.values()), hole=0.55))
                fig.update_layout(height=220, margin=dict(t=0, b=0, l=0, r=0), showlegend=False)
                st.plotly_chart(fig, width="stretch", key=f"pie_{g.goal.name}")
                ga = g.goal_analysis
                ok = ga["reachable"]
                st.write(("✅ Atteignable" if ok else "⚠️ Pas atteignable tel quel") +
                         f" : besoin {pct(ga['required_return'])}/an, hypothèse {pct(ga['assumed_return'])}/an")
                if not ok and "monthly_contribution_needed" in ga:
                    st.caption(f"Épargne requise : {ga['monthly_contribution_needed']:,.0f} $/mois (sans prendre plus de risque)")
                with st.expander("Pourquoi"):
                    st.write(g.why_level)
                    for r in g.reasons:
                        st.write(f"• **{r['ticker']} {r['weight']:.0%}** — {r['reason']}")
                    for c in whatif.goal_conditions(profile, g.goal):
                        st.caption(f"{c.condition} → {c.effect}")
        st.markdown("#### Portefeuille combiné et ses risques")
        rm = risks.risk_map(plan.total_weights, universe, px_cad, dollar_vol, expected_nominal=profile.expected["net"])
        rcols = st.columns(len(rm))
        for c, r in zip(rcols, rm):
            c.metric(f"{LEVEL_COLOR[r.level]} {RISK_FR[r.kind]}", r.level)
            c.caption(r.reason)

# ----------------------------------------------------------------------------- 3. time machine
with tabs[2]:
    plan = st.session_state.get("plan")
    weights = plan.total_weights if plan else strategist.policy_allocation(profile, px_cad).weights
    amount = st.number_input("Montant fictif ($ CAD)", 1000, 10_000_000, int(plan.total_amount) if plan else 100_000, step=5000)
    r = tm.replay(weights, px_cad, profile, float(amount), cpi_index=cpi())
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=r.path.index, y=r.path["value"], name="Valeur ($)"))
    if "value_real" in r.path:
        fig.add_trace(go.Scatter(x=r.path.index, y=r.path["value_real"], name="Valeur après inflation", line=dict(dash="dot")))
    d = r.worst_drawdown
    fig.add_vrect(x0=d["peak_date"], x1=d["trough_date"], fillcolor="red", opacity=0.08, line_width=0)
    fig.update_layout(height=380, margin=dict(t=10, b=10), legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valeur finale", f"{r.final_value:,.0f} $")
    c2.metric("Après inflation", f"{r.final_value_real:,.0f} $" if r.final_value_real else "—")
    c3.metric("Pire baisse", f"{d['drawdown']:.1%}", f"-{d['dollars_lost']:,.0f} $", delta_color="inverse")
    c4.metric("Pire 12 mois", pct(r.worst_12_months["return"]), f"accepté : -{r.accepted_loss:.0%}", delta_color="off")
    st.info("**" + r.question + "**")
    hold = st.radio("Auriez-vous tenu ?", ["Oui", "Non"], horizontal=True, index=0)
    if hold == "Non":
        new = pf.build_profile(tm.revise_tolerance(profile.answers, False), profile.preferences)
        st.warning(f"Votre tolérance réelle semble plus basse que déclarée : niveau révisé "
                   f"{pf.level_card(new.level)['fr']} ({new.level}/5).")
    st.markdown("#### Scénarios hypothétiques (pas des prévisions)")
    st.dataframe(pd.DataFrame([{"Scénario": s["label"], "Effet": f"{s['portfolio_return']:.1%}",
                                "En $": f"{s['dollars']:,.0f}", "Base": s["basis"]}
                               for s in (tm.shock(weights, universe, float(amount), k) for k in tm.SHOCKS)]),
                 hide_index=True, width="stretch")

# ----------------------------------------------------------------------------- 4. ticker dashboard
with tabs[3]:
    c1, c2, c3 = st.columns([2, 2, 1])
    symbol = c1.text_input("Rechercher un titre", "NVDA").strip().upper()
    tf = c2.radio("Période", list(tk.TIMEFRAMES), index=5, horizontal=True)
    live = c3.toggle("Données Yahoo en direct", value=False, help="Sinon : jeu de données des organisateurs (31 actifs, sans états financiers)")
    source = tk.YFinanceSource() if live else tk.StarterSource()
    try:
        o = tk.overview(symbol, source, profile=profile, portfolio=(st.session_state.get("plan").total_weights
                                                                    if st.session_state.get("plan") else None),
                        universe=universe, prices_cad=px_cad)
        ch = tk.chart(source, symbol, tf)
        idn = o["identity"]
        st.subheader(f"{idn['name'] or symbol} ({symbol}) · {idn.get('sector') or ''} · {idn.get('currency') or ''}")
        cf = go.Figure(go.Scatter(x=[p["t"] for p in ch["points"]], y=[p["close"] for p in ch["points"]], fill="tozeroy"))
        cf.update_layout(height=300, margin=dict(t=10, b=10), yaxis=dict(rangemode="normal"))
        st.plotly_chart(cf, width="stretch")
        m = st.columns(6)
        for col, k in zip(m, ["1M", "YTD", "1Y", "3Y", "5Y"]):
            col.metric(k, pct(o["returns"][k]["value"]), help=o["returns"][k]["detail"])
        m[5].metric("Pire baisse", pct(o["risk"]["max_drawdown"]["value"]), help=o["risk"]["max_drawdown"]["detail"])
        g, f = o["growth_score"], o["fit_score"]
        a, b = st.columns(2)
        with a:
            st.markdown(f"#### Croissance mesurée : {g['score'] if g['score'] is not None else '—'} · {g['label']}")
            for x in g["factors"]:
                st.write(f"• {x['name']}: {x['value'] if x['value'] is None else round(x['value'], 3)} "
                         f"→ {'—' if x['score'] is None else round(x['score'], 2)} · _{x['explanation']}_")
            for n in g["notes"]:
                st.caption(n)
        with b:
            st.markdown(f"#### Adéquation à votre profil : {f['score']} · {f['label']}")
            for x in f["factors"]:
                st.write(f"• {x['name']} → {'—' if x['score'] is None else round(x['score'], 2)} · _{x['explanation']}_")
            for n in f["notes"]:
                st.caption(n)
        with st.expander("Données et provenance"):
            st.json({"fondamentaux": o["fundamentals"], "risque": o["risk"], "données": o["data"]})
        st.markdown("#### Nouvelles récentes : faits ou opinions ?")
        try:
            dg = news.digest(symbol, news.recent_headlines(symbol))
            n1, n2, n3, n4 = st.columns(4)
            n1.metric("Manchettes pertinentes", dg.n)
            n2.metric("Opinions / prévisions", f"{dg.share_predictive:.0%}")
            n3.metric("Sources peu fiables", f"{dg.share_low_trust:.0%}")
            n4.metric("« Hype » (opinions de sources peu fiables)", f"{dg.hype_share:.0%}")
            fa, op = st.columns(2)
            with fa:
                st.markdown("**Faits (sources les plus fiables d'abord)**")
                for x in dg.top_descriptive:
                    st.write(f"• {x['title']} — _{x['publisher']}, confiance {x['trust']:.2f}_")
            with op:
                st.markdown("**Opinions et prévisions**")
                for x in dg.top_predictive:
                    st.write(f"• {x['title']} — _{x['publisher']}, confiance {x['trust']:.2f}_")
            for n_ in dg.notes:
                st.caption(n_)
            st.caption(f"Classificateur : {dg.classifier}. Les nouvelles servent à expliquer, jamais à prédire.")
        except Exception as e:
            st.caption(f"Nouvelles indisponibles : {e}")
    except Exception as e:  # show the problem instead of a stack trace
        st.error(f"{symbol} : {e}")

# ----------------------------------------------------------------------------- 5. strategy lab
with tabs[4]:
    c1, c2 = st.columns(2)
    lsym = c1.selectbox("Titre", sorted(px_local.columns), index=sorted(px_local.columns).index("TSLA"))
    strat = c2.selectbox("Stratégie", [s for s in lab.STRATEGIES if s != "buy_hold"],
                         format_func=lambda s: f"{s} — {lab.STRATEGIES[s].description}")
    res = lab.evaluate(px_local[lsym], strat, lsym, profile=profile, risk_free_annual=0.025)
    st.caption(f"Mode {res.mode} · {res.combinations_tested} combinaisons testées · paramètres {res.params} · "
               f"optimisé avant le {res.split_date}, testé après")
    t = pd.DataFrame({
        "Stratégie (avant)": res.in_sample, "Acheter-conserver (avant)": res.buy_hold_in_sample,
        "Stratégie (après, hors échantillon)": res.out_of_sample, "Acheter-conserver (après)": res.buy_hold_out_of_sample,
    }).loc[["total_return", "cagr", "volatility", "sharpe", "max_drawdown", "trades", "time_invested", "costs_paid"]]
    st.dataframe(t.style.format("{:.3f}"), width="stretch")
    for fnd in res.findings:
        (st.warning if fnd["severity"] == "warning" else st.info)(fnd["message"])
    st.caption("Le labo répond à « qu'est-ce qui se serait passé ? », jamais à « achetez maintenant ».")

# ----------------------------------------------------------------------------- 6. devil's advocate
with tabs[5]:
    st.markdown("Demandez quelque chose ; l'avocat du diable vérifie la cohérence avec votre profil, chiffres à l'appui.")
    c1, c2 = st.columns(2)
    asym = c1.selectbox("Je veux mettre…", sorted(universe.index), index=sorted(universe.index).index("TSLA"), key="adv_sym")
    aw = c2.slider("…cette part de mon portefeuille", 0.01, 0.6, 0.30, 0.01, format="%.2f")
    current = st.session_state.get("plan").total_weights if st.session_state.get("plan") else strategist.policy_allocation(profile, px_cad).weights
    try:
        adv_digest = news.digest(asym, news.recent_headlines(asym)).to_dict()
    except Exception:
        adv_digest = None
    rv = advocate.review_trade(asym, aw, current, profile, px_cad, universe, news_digest=adv_digest)
    st.subheader({"reconsider": "🔴 À reconsidérer", "proceed with care": "🟡 Avec prudence",
                  "no major objection": "🟢 Pas d'objection majeure"}[rv.verdict])
    if rv.before_after:
        b, a = rv.before_after["before"], rv.before_after["after"]
        cmp = pd.DataFrame({"Avant": b, "Après": a}).loc[["cagr", "volatility", "max_drawdown", "sharpe"]]
        st.dataframe(cmp.style.format("{:.3f}"), width="stretch")
        st.caption(f"Historique {rv.before_after['window']}, en CAD.")
    for c in rv.challenges:
        with st.container(border=True):
            st.markdown(f"**{c.bias}** — {c.claim}")
            if c.counterpoint:
                st.write("↔️ Contre-argument : " + c.counterpoint)
            st.write("❓ " + c.question)
    st.divider()
    llm_ready = os.environ.get("WEALTHPILOT_LLM") or os.environ.get("ANTHROPIC_API_KEY")
    st.markdown("#### Conseiller (agents Claude sur Amazon Bedrock)")
    if not llm_ready:
        st.caption("Agents non connectés dans cette démo locale : définir WEALTHPILOT_LLM=bedrock (AWS) ou "
                   "WEALTHPILOT_LLM=anthropic. Les calculs ci-dessus sont les mêmes outils qu'ils appellent.")
    else:
        q = st.chat_input("Posez votre question")
        if q:
            from wealthpilot.agents import Session, ask
            from wealthpilot.agents.llm import from_env
            sess = Session.from_starter()
            sess.profile, sess.portfolio = profile, current
            with st.spinner("Les agents travaillent…"):
                ans = ask(sess, q, from_env())
            st.markdown(ans.text)
            with st.expander("Reçus (trace d'exécution)"):
                st.json([r.to_dict() for r in sess.ledger.receipts])
