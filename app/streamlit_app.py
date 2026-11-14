"""WealthPilot - demo interface (Streamlit).

Run:  streamlit run app/streamlit_app.py
Simulation only: fictional accounts and amounts, no real transactions, not financial advice.
"""

from __future__ import annotations

import inspect
import os
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wealthpilot import accounts, advocate, data, goals as gl, lab, news, onboarding as ob  # noqa: E402
from wealthpilot import profile as pf, risks, strategist, ticker as tk, time_machine as tm, whatif  # noqa: E402

st.set_page_config(page_title="WealthPilot", page_icon="🧭", layout="wide")


def stretch(fn) -> dict:
    """Full width on old and new Streamlit (width='stretch' is recent; older versions use use_container_width)."""
    ps = inspect.signature(fn).parameters
    if "width" in ps and "int" not in str(ps["width"].annotation):
        return {"width": "stretch"}
    return {"use_container_width": True}


def bordered():
    try:
        return st.container(border=True)
    except TypeError:  # very old Streamlit
        return st.container()


# ----------------------------------------------------------------------------- French labels

FR = {
    "drop_reaction": {"sell_all": "Je vends tout", "sell_some": "Je vends une partie", "hold": "J'attends",
                      "buy_more": "J'investis davantage"},
    "goal": {"preserve": "Préserver mon capital", "income": "Générer un revenu régulier",
             "balanced": "Équilibrer croissance et stabilité", "max_growth": "Maximiser la croissance à long terme"},
    "experience": {"none": "Aucune", "beginner": "Débutant(e)", "intermediate": "Intermédiaire", "advanced": "Avancée"},
    "return_expectation": {"lt3": "Moins de 3 %", "3to5": "3 % à 5 %", "5to7": "5 % à 7 %", "7to10": "7 % à 10 %",
                           "gt10": "Plus de 10 %"},
    "esg": {"none": "Pas de préférence", "prefer": "Je préfère des placements responsables",
            "exclude": "J'exige des placements responsables"},
    "crypto": {"no": "Non", "small": "Un peu", "open": "Oui, si mon profil le permet"},
    "region": {"canada": "Surtout le Canada", "balanced": "Équilibré Canada / États-Unis", "us": "Surtout les États-Unis",
               "global": "Mondial"},
    "goal_type": {"emergency_fund": "Coussin d'urgence", "home_purchase": "Achat d'une première maison",
                  "project": "Projet (voyage, auto, études)", "retirement": "Retraite", "income": "Revenu régulier",
                  "legacy": "Héritage / transmission"},
}
RANGES = {"A": (0.04, -0.02), "B": (0.08, -0.08), "C": (0.14, -0.18), "D": (0.22, -0.32)}
FLAG_FR = {
    "CAPACITY_TOLERANCE_GAP": "Capacité et tolérance ne concordent pas",
    "EMERGENCY_FUND_SHORT": "Coussin d'urgence insuffisant",
    "SAVINGS_OVERCOMMITTED": "Objectifs au-delà de votre capacité d'épargne",
    "HIGH_DEBT": "Dette élevée",
    "EXPECTATION_GAP": "Attente de rendement élevée",
    "ESG_DATA_LIMIT": "Limite des données ESG",
    "CRYPTO_NO_EXPERIENCE": "Crypto désactivée (pas d'expérience)",
    "CRYPTO_NOT_ALLOWED": "Crypto non permise à ce niveau",
    "LEVEL_LOWERED": "Niveau abaissé",
    "HORIZON_CAP": "Niveau plafonné par l'horizon",
    "NO_EMERGENCY_FUND": "Pas de coussin d'urgence",
    "GOAL_NOT_REACHABLE": "Objectif non atteignable tel quel",
}
def risk_text(r) -> str:
    v = r.value
    if r.kind == "market":
        return f"Ce mélange a varié d'environ {v:.0%} par année; les placements peuvent baisser ensemble."
    if r.kind == "credit":
        return f"{v:.0%} en fonds d'obligations, surtout gouvernementales et de bonne qualité : risque réparti."
    if r.kind == "liquidity":
        return f"{v:.0%} en actifs peu échangés ou en crypto (vendre vite à bon prix peut être difficile)."
    if r.kind == "currency":
        return f"{v:.0%} en dollars américains : sa valeur en CAD bouge avec le taux de change."
    if r.kind == "concentration":
        top = r.reason.split(" ")[0]
        return (f"La plus grosse position individuelle ({top}) porte {v:.0%} du risque." if v > 0 else
                "Aucune entreprise seule : le risque est porté par des fonds larges, diversifiés.")
    if r.kind == "inflation":
        return f"Rendement réel supposé d'environ {v:.1%} par an après inflation (hypothèse, pas une prévision)."
    return r.reason


ACCOUNT_FR = {"emergency_fund": "CELI ou compte épargne à intérêt élevé", "home_purchase": "CELIAPP",
              "project": "CELI", "retirement": "REER, puis CELI", "income": "CELI, puis non enregistré",
              "legacy": "Non enregistré ou CELI (voir un planificateur successoral)"}


def horizon_txt(y: float) -> str:
    return "immédiat" if y == 0 else f"{y:g} an(s)"


RISK_FR = {"market": "Marché", "credit": "Crédit", "liquidity": "Liquidité", "currency": "Devise",
           "concentration": "Concentration", "inflation": "Inflation"}
LEVEL_FR = {"low": "faible", "moderate": "modéré", "high": "élevé"}
DOT = {"low": "🟢", "moderate": "🟡", "high": "🔴"}
LEVEL_FOR_FR = {1: "horizons courts, peu de confort avec les variations ou argent requis bientôt",
                2: "approche de la retraite ou horizons moyens, priorité à la stabilité",
                3: "horizons moyens à longs, équilibre entre croissance et stabilité",
                4: "longs horizons et confort avec des baisses temporaires importantes",
                5: "très longs horizons, capacité ET tolérance élevées"}
money = lambda x: f"{x:,.0f} $".replace(",", " ")  # noqa: E731
pct = lambda x: "—" if x is None else f"{x:.1%}"  # noqa: E731


def show_flags(flags):
    for f in flags:
        title = FLAG_FR.get(f.code, f.code)
        (st.warning if f.severity == "warning" else st.info)(f"**{title}** — {f.message}")


# ----------------------------------------------------------------------------- data

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


try:
    px_cad, px_local, universe, dollar_vol = load()
except FileNotFoundError as e:
    st.error(f"Données de départ manquantes. {e}")
    st.stop()

ss = st.session_state
ss.setdefault("user", None)
ss.setdefault("step", 1)
ss.setdefault("draft", None)

# ----------------------------------------------------------------------------- header

h1, h2 = st.columns([5, 1])
h1.title("🧭 WealthPilot")
h1.caption("Simulation éducative (Datathon PolyFinances 2026). Comptes et montants fictifs, aucune transaction réelle, "
           "pas un conseil financier. Chaque chiffre vient d'un calcul vérifiable sur des données publiques.")
if ss.user:
    h2.write(f"👤 **{ss.user}**")
    if h2.button("Se déconnecter"):
        for k in ("user", "draft", "onboarding", "chosen_level"):
            ss.pop(k, None)
        ss.step = 1
        st.rerun()

# ----------------------------------------------------------------------------- authentication

if not ss.user:
    st.info("Créez un compte **fictif** pour la démo. N'utilisez pas un mot de passe réel ni vos vraies données bancaires.")
    login, signup = st.tabs(["Se connecter", "Créer un compte"])
    with login:
        u = st.text_input("Nom d'utilisateur", key="login_user")
        p = st.text_input("Mot de passe", type="password", key="login_pw")
        if st.button("Se connecter", type="primary"):
            if accounts.authenticate(u, p):
                ss.user = u.lower()
                saved = accounts.load_profile(ss.user)
                if saved:
                    ss.onboarding = saved
                st.rerun()
            else:
                st.error("Nom d'utilisateur ou mot de passe incorrect.")
    with signup:
        u2 = st.text_input("Choisissez un nom d'utilisateur", key="su_user")
        p2 = st.text_input("Choisissez un mot de passe (8 caractères ou plus)", type="password", key="su_pw")
        p3 = st.text_input("Confirmez le mot de passe", type="password", key="su_pw2")
        if st.button("Créer mon compte", type="primary"):
            if p2 != p3:
                st.error("Les mots de passe ne correspondent pas.")
            else:
                try:
                    accounts.create_user(u2, p2)
                    ss.user = u2.lower()
                    ss.step = 1
                    st.rerun()
                except accounts.AccountError as e:
                    st.error(str(e))
    st.stop()

# ----------------------------------------------------------------------------- onboarding wizard (first login)

STEPS = ["Vous", "Vos finances", "Vos objectifs", "Votre confort avec le risque", "Expérience et préférences", "Résumé"]


def blank_draft() -> dict:
    return {"financials": dict(age=30, province="QC", employment="salaried", annual_income=70_000.0,
                               monthly_expenses=3_000.0, monthly_savings=500.0, cash_savings=10_000.0,
                               investments=20_000.0, other_assets=0.0, debts=0.0, dependents=0),
            "goals": None,
            "tolerance": dict(drop_reaction="hold", range_choice="B", goal="balanced", experience="beginner",
                              return_expectation="5to7"),
            "preferences": asdict(pf.Preferences())}


def draft_onboarding(d: dict) -> ob.Onboarding:
    fin = ob.Financials(**d["financials"])
    goals = [gl.GoalSpec(**g) for g in (d["goals"] or [asdict(g) for g in ob.suggested_goals(fin)])]
    return ob.Onboarding(fin, goals, d["tolerance"],
                         pf.Preferences(**{k: tuple(v) if isinstance(v, list) else v for k, v in d["preferences"].items()}))


def nav(back=True, next_label="Suivant", valid=True, message=""):
    c1, c2, _ = st.columns([1, 1, 4])
    if back and c1.button("← Retour"):
        ss.step -= 1
        st.rerun()
    if c2.button(next_label, type="primary", disabled=not valid):
        ss.step += 1
        st.rerun()
    if not valid and message:
        st.caption(message)


if not ss.get("onboarding"):
    if ss.draft is None:
        ss.draft = blank_draft()
    d = ss.draft
    f = d["financials"]
    st.subheader(f"Créer votre profil · étape {ss.step} de {len(STEPS)} : {STEPS[ss.step - 1]}")
    st.progress(ss.step / len(STEPS))

    if ss.step == 1:
        st.write("Pour la démo, vous pouvez partir d'un persona du cas :")
        cols = st.columns(len(ob.PERSONAS))
        for c, (name, o) in zip(cols, ob.PERSONAS.items()):
            if c.button(f"Remplir comme {name}"):
                ss.draft = o.to_dict()
                for k in [k for k in ss.keys() if k.split("_")[0] in {"g", "gn", "gh", "gt", "gc", "gm", "th"}]:
                    del ss[k]  # widgets of later steps must pick up the persona's values
                st.rerun()
        a, b = st.columns(2)
        f["age"] = a.number_input("Âge", 18, 100, int(f["age"]))
        f["province"] = b.selectbox("Province", ob.PROVINCES, index=ob.PROVINCES.index(f["province"]))
        emp = list(ob.EMPLOYMENT)
        f["employment"] = a.selectbox("Situation d'emploi", emp, index=emp.index(f["employment"]),
                                      format_func=lambda k: ob.EMPLOYMENT[k][1])
        f["dependents"] = b.number_input("Personnes à votre charge", 0, 10, int(f["dependents"]))
        nav(back=False)

    elif ss.step == 2:
        st.caption("Des montants approximatifs suffisent. Ils mesurent votre **capacité** à absorber une baisse.")
        a, b = st.columns(2)
        f["annual_income"] = float(a.number_input("Revenu annuel brut ($)", 0, 10_000_000, int(f["annual_income"]), step=1000))
        f["monthly_expenses"] = float(b.number_input("Dépenses mensuelles ($)", 0, 1_000_000, int(f["monthly_expenses"]), step=100))
        f["monthly_savings"] = float(a.number_input("Montant que vous pouvez épargner par mois ($)", 0, 1_000_000, int(f["monthly_savings"]), step=50))
        f["cash_savings"] = float(b.number_input("Épargne disponible (compte épargne, CELI liquide) ($)", 0, 100_000_000, int(f["cash_savings"]), step=1000))
        f["investments"] = float(a.number_input("Montant à investir dans la simulation ($)", 0, 100_000_000, int(f["investments"]), step=1000))
        f["other_assets"] = float(b.number_input("Autres actifs, nets d'hypothèque (maison, etc.) ($)", 0, 100_000_000, int(f["other_assets"]), step=1000))
        f["debts"] = float(a.number_input("Dettes hors hypothèque (prêt étudiant, auto, cartes) ($)", 0, 100_000_000, int(f["debts"]), step=1000))
        valid = f["monthly_expenses"] > 0
        if valid:
            fin = ob.Financials(**f)
            m = st.columns(4)
            m[0].metric("Valeur nette", money(fin.net_worth))
            m[1].metric("Coussin", f"{fin.emergency_months:.1f} mois", help="Épargne disponible divisée par les dépenses mensuelles")
            m[2].metric("Taux d'épargne", f"{fin.savings_rate:.0%}")
            m[3].metric("Part investie ici", f"{fin.investable_share:.0%} de vos actifs")
            if fin.monthly_savings > fin.annual_income / 12 - fin.monthly_expenses + 1:
                st.warning("L'épargne indiquée dépasse revenu moins dépenses (avant impôts). Vérifiez les montants.")
        nav(valid=valid, message="Indiquez vos dépenses mensuelles.")

    elif ss.step == 3:
        fin = ob.Financials(**f)
        st.caption("Chaque objectif a **son propre horizon** : il aura son sous-portefeuille et un compte suggéré.")
        current = {g["type"]: g for g in (d["goals"] or [asdict(g) for g in ob.suggested_goals(fin)])}
        new_goals = []
        for gtype, label in FR["goal_type"].items():
            on = st.checkbox(label, value=gtype in current, key=f"g_{gtype}")
            if not on:
                continue
            g = current.get(gtype) or dict(name=label, type=gtype,
                                           horizon_years=0.0 if gtype == "emergency_fund" else (max(1, 65 - fin.age) if gtype == "retirement" else 5.0),
                                           target_amount=fin.emergency_target() if gtype == "emergency_fund" else 50_000.0,
                                           current_amount=0.0, monthly_contribution=0.0)
            with bordered():
                c = st.columns(5)
                g["name"] = c[0].text_input("Nom", g["name"], key=f"gn_{gtype}")
                if gtype == "emergency_fund":
                    g["horizon_years"] = 0.0
                    c[1].write("Horizon : immédiat")
                else:
                    g["horizon_years"] = float(c[1].number_input("Horizon (années)", 0.5, 60.0, float(max(g["horizon_years"], 0.5)), step=0.5, key=f"gh_{gtype}"))
                g["target_amount"] = float(c[2].number_input("Montant visé ($)", 0, 100_000_000, int(g["target_amount"]), step=1000, key=f"gt_{gtype}"))
                g["current_amount"] = float(c[3].number_input("Déjà de côté ($)", 0, 100_000_000, int(g["current_amount"]), step=1000, key=f"gc_{gtype}"))
                g["monthly_contribution"] = float(c[4].number_input("Par mois ($)", 0, 1_000_000, int(g["monthly_contribution"]), step=50, key=f"gm_{gtype}"))
                if gtype == "emergency_fund":
                    st.caption(f"Cible suggérée : {money(fin.emergency_target())} "
                               f"({fin.emergency_target() / fin.monthly_expenses:.0f} mois de dépenses).")
            new_goals.append(g)
        d["goals"] = new_goals
        total = sum(g["monthly_contribution"] for g in new_goals)
        st.write(f"Épargne mensuelle planifiée : **{money(total)}** sur une capacité de **{money(fin.monthly_savings)}**.")
        nav(valid=bool(new_goals), message="Choisissez au moins un objectif.")

    elif ss.step == 4:
        t = d["tolerance"]
        amount = max(f["investments"], 1000.0)
        st.caption("Ces questions mesurent votre **tolérance** : ce que vous vivriez bien, avec vos propres montants.")
        t["drop_reaction"] = st.radio(f"Vos placements de {money(amount)} valent {money(amount * 0.8)} après quelques mois. "
                                      "Que faites-vous ?", list(FR["drop_reaction"]), index=list(FR["drop_reaction"]).index(t["drop_reaction"]),
                                      format_func=FR["drop_reaction"].get)
        t["range_choice"] = st.radio("Sur un an, quelle fourchette de résultats accepteriez-vous ?", list(RANGES),
                                     index=list(RANGES).index(t["range_choice"]),
                                     format_func=lambda k: f"Entre {money(amount * (1 + RANGES[k][1]))} et {money(amount * (1 + RANGES[k][0]))} "
                                                           f"({RANGES[k][1]:+.0%} à {RANGES[k][0]:+.0%})")
        t["goal"] = st.radio("Qu'est-ce qui compte le plus pour vous ?", list(FR["goal"]), index=list(FR["goal"]).index(t["goal"]),
                             format_func=FR["goal"].get)
        t["return_expectation"] = st.radio("Quel rendement annuel moyen espérez-vous ?", list(FR["return_expectation"]),
                                           index=list(FR["return_expectation"]).index(t["return_expectation"]),
                                           format_func=FR["return_expectation"].get, horizontal=True)
        nav()

    elif ss.step == 5:
        t, pr = d["tolerance"], d["preferences"]
        t["experience"] = st.radio("Votre expérience en placement", list(FR["experience"]),
                                   index=list(FR["experience"]).index(t["experience"]), format_func=FR["experience"].get,
                                   horizontal=True)
        st.markdown("**Thèmes qui vous intéressent** (ajoutés en petites positions, à l'intérieur de vos limites)")
        chosen = set(strategist.normalize_themes(pr.get("themes", ())))
        cols = st.columns(3)
        picked = []
        for i, (key, (label, tickers)) in enumerate(strategist.THEMES.items()):
            if cols[i % 3].checkbox(label, value=key in chosen, key=f"th_{key}", help=", ".join(tickers)):
                picked.append(key)
        pr["themes"] = picked
        a, b = st.columns(2)
        pr["esg"] = a.selectbox("Investissement responsable (ESG)", list(FR["esg"]), index=list(FR["esg"]).index(pr["esg"]),
                                format_func=FR["esg"].get)
        pr["crypto"] = b.selectbox("Cryptoactifs", list(FR["crypto"]), index=list(FR["crypto"]).index(pr["crypto"]),
                                   format_func=FR["crypto"].get)
        pr["region"] = a.selectbox("Répartition géographique", list(FR["region"]), index=list(FR["region"]).index(pr["region"]),
                                   format_func=FR["region"].get)
        fossil = b.checkbox("Exclure les énergies fossiles", value="no_fossil_fuels" in pr.get("values", ()))
        pr["values"] = ["no_fossil_fuels"] if fossil else []
        pr["simplicity"] = a.checkbox("Je préfère peu de fonds, simples à comprendre", value=bool(pr.get("simplicity")))
        pr["excluded_sectors"] = list(pr.get("excluded_sectors", []))
        nav()

    elif ss.step == 6:
        o = draft_onboarding(d)
        p = ob.build_profile(o)
        card = pf.level_card(p.level)
        st.markdown(f"## Votre profil : {card['fr']} · {card['score_10']}/10")
        st.write(f"Pour : {LEVEL_FOR_FR[p.level]}. Actions entre **{card['stocks']}**.")
        a, b = st.columns(2)
        a.metric("Capacité de risque", f"{p.capacity:.0f}/100", help="Calculée à partir de vos chiffres")
        b.metric("Tolérance au risque", f"{p.tolerance:.0f}/100", help="D'après vos réponses")
        st.caption("Le niveau suit la plus basse des deux. Chaque objectif est ensuite plafonné par son horizon.")
        with st.expander("D'où vient votre capacité"):
            for r in p.reasons:
                if r.dimension == "capacity":
                    st.write(f"• {r.label} → {r.contribution:.1f} points")
        show_flags(p.flags)
        plan = gl.plan(p, o.goals, px_cad)
        for g in plan.goals:
            st.write(f"• **{g.goal.name}** : niveau {pf.level_card(g.level)['fr'] if g.level_name != 'Cash reserve' else 'Liquidités'}, "
                     f"compte suggéré {ACCOUNT_FR.get(g.goal.type, g.account)}")
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("← Retour"):
            ss.step -= 1
            st.rerun()
        if c2.button("Créer mon profil", type="primary"):
            accounts.save_profile(ss.user, o.to_dict())
            ss.onboarding = o.to_dict()
            st.rerun()
    st.stop()

# ----------------------------------------------------------------------------- dashboard

o = ob.Onboarding.from_dict(ss.onboarding)
base_profile = ob.build_profile(o)
ss.setdefault("chosen_level", base_profile.level)
profile = base_profile
if ss.chosen_level < base_profile.level:
    profile, _ = pf.choose_level(base_profile, ss.chosen_level)
plan = gl.plan(profile, o.goals, px_cad)
eff = gl.effective_profile(profile, plan)
weights = plan.total_weights

tabs = st.tabs(["Mon plan", "Machine à remonter le temps", "Titre", "Labo", "Avocat du diable", "Mon profil"])

with tabs[0]:
    card = pf.level_card(profile.level)
    st.markdown(f"### {card['fr']} · {card['score_10']}/10 — {money(plan.total_amount)} répartis sur {len(plan.goals)} objectif(s)")
    checks = gl.check_plan(profile, plan, universe, px_cad)
    cols = st.columns(len(plan.goals))
    for col, g in zip(cols, plan.goals):
        with col:
            st.markdown(f"#### {g.goal.name}")
            lvl = "Liquidités" if g.level_name == "Cash reserve" else pf.level_card(g.level)["fr"]
            st.caption(f"{lvl} · horizon {horizon_txt(g.goal.horizon_years)} · compte suggéré : "
                       f"{ACCOUNT_FR.get(g.goal.type, g.account)} (à titre éducatif)")
            fig = go.Figure(go.Pie(labels=list(g.weights), values=list(g.weights.values()), hole=0.55))
            fig.update_traces(textinfo="percent", textposition="inside")
            fig.update_layout(height=300, margin=dict(t=0, b=0, l=0, r=0), showlegend=True,
                              legend=dict(orientation="h", y=-0.05, font=dict(size=11)))
            st.plotly_chart(fig, key=f"pie_{g.goal.name}", **stretch(st.plotly_chart))
            ga = g.goal_analysis
            if ga.get("kind") == "cushion":
                if ga["reachable"]:
                    st.success(f"Coussin complet : {money(g.goal.current_amount)} pour une cible de {money(g.goal.target_amount)}.")
                elif ga["months_to_fill"]:
                    st.warning(f"Il manque {money(ga['gap'])} : environ {ga['months_to_fill']:.0f} mois au rythme de "
                               f"{money(g.goal.monthly_contribution)}/mois. À remplir avant d'investir davantage.")
                else:
                    st.warning(f"Il manque {money(ga['gap'])}. Prévoyez un montant mensuel pour le remplir en priorité.")
            elif ga["reachable"]:
                st.success(f"Atteignable : besoin {pct(ga['required_return'])}/an, hypothèse {pct(ga['assumed_return'])}/an")
            else:
                need = ga.get("monthly_contribution_needed")
                st.warning(f"Pas atteignable tel quel : besoin {pct(ga['required_return'])}/an, hypothèse "
                           f"{pct(ga['assumed_return'])}/an" + (f". Épargne requise : {money(need)}/mois." if need else ""))
            for v in checks[g.goal.name]:
                if v.severity == "warning":
                    st.error(v.message)
            with st.expander("Pourquoi"):
                st.write(g.why_level)
                for r in g.reasons:
                    st.write(f"• **{r['ticker']} {r['weight']:.1%}** — {r['reason']}")
                for n in g.notes:
                    st.caption(n)
                st.markdown("**Ce qui changerait cette réponse**")
                for c in whatif.goal_conditions(profile, g.goal):
                    st.caption(f"{c.condition} → {c.effect}")
    st.markdown("#### Les six risques de votre portefeuille combiné")
    rm = risks.risk_map(weights, universe, px_cad, dollar_vol, expected_nominal=profile.expected["net"])
    rcols = st.columns(len(rm))
    for c, r in zip(rcols, rm):
        c.metric(f"{DOT[r.level]} {RISK_FR[r.kind]}", LEVEL_FR[r.level])
        c.caption(risk_text(r))

with tabs[1]:
    amount = st.number_input("Montant ($)", 1000, 100_000_000, int(max(plan.total_amount, 1000)), step=5000)
    r = tm.replay(weights, px_cad, eff, float(amount), cpi_index=cpi())
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=r.path.index, y=r.path["value"], name="Valeur ($)"))
    if "value_real" in r.path:
        fig.add_trace(go.Scatter(x=r.path.index, y=r.path["value_real"], name="Après inflation", line=dict(dash="dot")))
    d_ = r.worst_drawdown
    fig.add_vrect(x0=d_["peak_date"], x1=d_["trough_date"], fillcolor="red", opacity=0.08, line_width=0)
    fig.update_layout(height=380, margin=dict(t=10, b=10), legend=dict(orientation="h"))
    st.plotly_chart(fig, **stretch(st.plotly_chart))
    c = st.columns(4)
    c[0].metric("Valeur finale", money(r.final_value))
    c[1].metric("Après inflation", money(r.final_value_real) if r.final_value_real else "—")
    c[2].metric("Pire baisse", f"{d_['drawdown']:.1%}", f"-{money(d_['dollars_lost'])}", delta_color="inverse")
    c[3].metric("Pire 12 mois", pct(r.worst_12_months["return"]), f"accepté : -{r.accepted_loss:.0%}", delta_color="off")
    st.info(f"Le {d_['trough_date']}, vos {money(amount)} auraient valu {money(d_['trough_value'])}, après un sommet de "
            f"{money(d_['peak_value'])} le {d_['peak_date']}. Les pires 12 mois ont fait {r.worst_12_months['return']:.1%}; "
            f"vous acceptiez {r.accepted_loss:.0%} dans une mauvaise année. **Auriez-vous tenu ?**")
    if st.radio("Votre réponse", ["Oui", "Non"], horizontal=True) == "Non":
        st.warning("Votre tolérance réelle semble plus basse que déclarée. Dans « Mon profil », choisissez un niveau plus prudent "
                   "ou refaites le questionnaire.")
    st.markdown("#### Scénarios hypothétiques (pas des prévisions)")
    st.dataframe(pd.DataFrame([{"Scénario": s["label"], "Effet": f"{s['portfolio_return']:.1%}", "En $": money(s["dollars"]),
                                "Base": s["basis"]} for s in (tm.shock(weights, universe, float(amount), k) for k in tm.SHOCKS)]),
                 hide_index=True, **stretch(st.dataframe))

with tabs[2]:
    c1, c2, c3 = st.columns([2, 3, 1])
    symbol = c1.text_input("Rechercher un titre (ex. NVDA, RY.TO, BTC-USD)", "NVDA").strip().upper()
    tf = c2.radio("Période", list(tk.TIMEFRAMES), index=5, horizontal=True)
    live = c3.toggle("Yahoo en direct", value=False, help="Sinon : données des organisateurs (31 actifs, sans états financiers)")
    if not live and symbol not in universe.index:
        st.warning(f"{symbol} n'est pas dans le jeu de données de départ. Activez « Yahoo en direct » pour d'autres titres.")
    else:
        try:
            source = tk.YFinanceSource() if live else tk.StarterSource()
            ov = tk.overview(symbol, source, profile=eff, portfolio=weights, universe=universe, prices_cad=px_cad)
            ch = tk.chart(source, symbol, tf)
            idn = ov["identity"]
            st.subheader(f"{idn['name'] or symbol} ({symbol}) · {idn.get('sector') or ''} · {idn.get('currency') or ''}")
            cf = go.Figure(go.Scatter(x=[q["t"] for q in ch["points"]], y=[q["close"] for q in ch["points"]], fill="tozeroy"))
            ys = [q["close"] for q in ch["points"]]
            if ys:
                cf.update_yaxes(range=[min(ys) * 0.97, max(ys) * 1.03])
            cf.update_layout(height=300, margin=dict(t=10, b=10))
            st.plotly_chart(cf, **stretch(st.plotly_chart))
            m = st.columns(6)
            for col, k in zip(m, ["1M", "YTD", "1Y", "3Y", "5Y"]):
                col.metric(k, pct(ov["returns"][k]["value"]), help=ov["returns"][k]["detail"])
            m[5].metric("Pire baisse", pct(ov["risk"]["max_drawdown"]["value"]), help=ov["risk"]["max_drawdown"]["detail"])
            g, fs = ov["growth_score"], ov["fit_score"]
            a, b = st.columns(2)
            with a:
                st.markdown(f"#### Croissance mesurée : {g['score'] if g['score'] is not None else '—'} · {g['label']}")
                for x in g["factors"]:
                    st.write(f"• {x['name']} : {'—' if x['value'] is None else round(x['value'], 3)} → "
                             f"{'—' if x['score'] is None else round(x['score'], 2)} · _{x['explanation']}_")
                for n in g["notes"]:
                    st.caption(n)
            with b:
                st.markdown(f"#### Adéquation à votre profil : {fs['score']} · {fs['label']}")
                for x in fs["factors"]:
                    st.write(f"• {x['name']} → {'—' if x['score'] is None else round(x['score'], 2)} · _{x['explanation']}_")
                for n in fs["notes"]:
                    st.caption(n)
            st.markdown("#### Nouvelles récentes : faits ou opinions ?")
            try:
                dg = news.digest(symbol, news.recent_headlines(symbol))
                n1, n2, n3, n4 = st.columns(4)
                n1.metric("Manchettes pertinentes", dg.n)
                n2.metric("Opinions / prévisions", f"{dg.share_predictive:.0%}")
                n3.metric("Sources peu fiables", f"{dg.share_low_trust:.0%}")
                n4.metric("« Hype »", f"{dg.hype_share:.0%}", help="Opinions venant de sources peu fiables")
                fa, op = st.columns(2)
                with fa:
                    st.markdown("**Faits** (sources fiables d'abord)")
                    for x in dg.top_descriptive:
                        st.write(f"• {x['title']} — _{x['publisher']}, confiance {x['trust']:.2f}_")
                with op:
                    st.markdown("**Opinions et prévisions**")
                    for x in dg.top_predictive:
                        st.write(f"• {x['title']} — _{x['publisher']}, confiance {x['trust']:.2f}_")
                for n in dg.notes:
                    st.caption(n)
            except Exception as e:
                st.caption(f"Nouvelles indisponibles : {e}")
            with st.expander("Données et provenance"):
                st.json({"fondamentaux": ov["fundamentals"], "risque": ov["risk"], "données": ov["data"]})
        except Exception as e:
            st.error(f"{symbol} : {e}")

with tabs[3]:
    c1, c2 = st.columns(2)
    names = sorted(px_local.columns)
    lsym = c1.selectbox("Titre", names, index=names.index("TSLA"))
    strat = c2.selectbox("Stratégie", [s for s in lab.STRATEGIES if s != "buy_hold"],
                         format_func=lambda s: f"{s} — {lab.STRATEGIES[s].description}")
    with st.spinner("Test en cours…"):
        res = lab.evaluate(px_local[lsym], strat, lsym, profile=profile, risk_free_annual=0.025)
    st.caption(f"Mode {'complet' if res.mode == 'full' else 'guidé'} · {res.combinations_tested} combinaisons testées · "
               f"paramètres {res.params} · optimisé avant le {res.split_date}, testé après")
    tbl = pd.DataFrame({"Stratégie (avant)": res.in_sample, "Acheter-conserver (avant)": res.buy_hold_in_sample,
                        "Stratégie (après)": res.out_of_sample, "Acheter-conserver (après)": res.buy_hold_out_of_sample}
                       ).loc[["total_return", "cagr", "volatility", "sharpe", "max_drawdown", "trades", "time_invested", "costs_paid"]]
    st.dataframe(tbl.apply(pd.to_numeric, errors="coerce").style.format("{:.3f}", na_rep="—"), **stretch(st.dataframe))
    for fnd in res.findings:
        (st.warning if fnd["severity"] == "warning" else st.info)(fnd["message"])
    st.caption("Le labo répond à « qu'est-ce qui se serait passé ? », jamais à « achetez maintenant ».")

with tabs[4]:
    st.markdown("Demandez quelque chose : l'avocat du diable vérifie la cohérence avec votre profil, chiffres à l'appui.")
    c1, c2 = st.columns(2)
    names = sorted(universe.index)
    asym = c1.selectbox("Je veux mettre…", names, index=names.index("TSLA"), key="adv_sym")
    aw = c2.slider("…cette part de mon portefeuille", 0.01, 0.60, 0.30, 0.01)
    if eff.level < profile.level:
        st.caption(f"Vérifié au niveau {pf.level_card(eff.level)['fr']}, celui de votre objectif le plus prudent qui est investi.")
    try:
        adv_digest = news.digest(asym, news.recent_headlines(asym)).to_dict()
    except Exception:
        adv_digest = None
    rv = advocate.review_trade(asym, aw, weights, eff, px_cad, universe, news_digest=adv_digest)
    st.subheader({"reconsider": "🔴 À reconsidérer", "proceed with care": "🟡 Avec prudence",
                  "no major objection": "🟢 Pas d'objection majeure"}[rv.verdict])
    if rv.before_after:
        bb, aa = rv.before_after["before"], rv.before_after["after"]
        cmp = pd.DataFrame({"Avant": bb, "Après": aa}).loc[["cagr", "volatility", "max_drawdown", "sharpe"]].astype(float)
        st.dataframe(cmp.style.format("{:.3f}"), **stretch(st.dataframe))
        st.caption(f"Historique {rv.before_after['window']}, en CAD.")
    for ch_ in rv.challenges:
        with bordered():
            st.markdown(f"**{ch_.bias}** — {ch_.claim}")
            if ch_.counterpoint:
                st.write("↔️ Contre-argument : " + ch_.counterpoint)
            st.write("❓ " + ch_.question)
    st.divider()
    st.markdown("#### Conseiller (agents Claude sur Amazon Bedrock)")
    if not (os.environ.get("WEALTHPILOT_LLM") or os.environ.get("ANTHROPIC_API_KEY")):
        st.caption("Agents non connectés dans cette démo locale : définir WEALTHPILOT_LLM=bedrock (AWS) ou "
                   "WEALTHPILOT_LLM=anthropic. Les calculs ci-dessus sont les mêmes outils qu'ils appellent.")
    else:
        q = st.chat_input("Posez votre question")
        if q:
            from wealthpilot.agents import Session, ask
            from wealthpilot.agents.llm import from_env
            sess = Session.from_starter()
            sess.profile, sess.portfolio, sess.amount = eff, weights, plan.total_amount
            with st.spinner("Les agents travaillent…"):
                ans = ask(sess, q, from_env())
            st.markdown(ans.text)
            with st.expander("Reçus (trace d'exécution)"):
                st.json([r.to_dict() for r in sess.ledger.receipts])

with tabs[5]:
    card = pf.level_card(base_profile.level)
    st.markdown(f"### Niveau recommandé : {card['fr']} · {card['score_10']}/10")
    st.write(f"Pour : {LEVEL_FOR_FR[base_profile.level]}.")
    a, b = st.columns(2)
    a.metric("Capacité de risque", f"{base_profile.capacity:.0f}/100")
    b.metric("Tolérance au risque", f"{base_profile.tolerance:.0f}/100")
    fin = o.financials
    m = st.columns(4)
    m[0].metric("Valeur nette", money(fin.net_worth))
    m[1].metric("Coussin", f"{fin.emergency_months:.1f} mois")
    m[2].metric("Taux d'épargne", f"{fin.savings_rate:.0%}")
    m[3].metric("Dette / revenu", f"{fin.debt_to_income:.0%}")
    with st.expander("D'où vient votre capacité"):
        for r in base_profile.reasons:
            if r.dimension == "capacity":
                st.write(f"• {r.label} → {r.contribution:.1f} points")
    show_flags(base_profile.flags)
    if base_profile.level > 1:
        lvl = st.select_slider("Choisir un niveau plus prudent (jamais plus risqué que recommandé)",
                               options=list(range(1, base_profile.level + 1)), value=min(ss.chosen_level, base_profile.level),
                               format_func=lambda n: f"{n} · {pf.level_card(n)['fr']}")
        if lvl != ss.chosen_level:
            ss.chosen_level = lvl
            st.rerun()
    else:
        st.caption("Vous êtes déjà au niveau le plus prudent.")
    c1, c2 = st.columns(2)
    if c1.button("Refaire le questionnaire"):
        ss.draft = dict(ss.onboarding)
        ss.onboarding = None
        ss.step = 1
        ss.chosen_level = 99
        st.rerun()
    if c2.button("Supprimer mon profil"):
        accounts.delete_profile(ss.user)
        ss.onboarding, ss.draft, ss.step = None, None, 1
        st.rerun()
