"""WealthPilot - demo interface (Streamlit).

Run:  streamlit run app/streamlit_app.py
Simulation only: fictional accounts and amounts, no real transactions, not financial advice.

Display rules
-------------
* Simple by default: one sentence per card, the two ticker scores up front.
  "Plus de détails" (sidebar) opens the deeper views.
* Streamlit renders text as Markdown, where "$...$" is a math formula
  (italic, spaces removed). Every displayed text goes through esc().
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

from wealthpilot import accounts, advocate, data, goals as gl, lab, macro_news, news, onboarding as ob  # noqa: E402
from wealthpilot import profile as pf, risks, strategist, ticker as tk, time_machine as tm, whatif  # noqa: E402

st.set_page_config(page_title="WealthPilot", page_icon="🧭", layout="wide")


# ----------------------------------------------------------------------------- display helpers

def esc(text) -> str:
    """Escape '$' so Markdown does not turn amounts into math formulas."""
    return str(text).replace("$", "\\$")


def say(text):
    st.markdown(esc(text))


def note(text):
    st.caption(esc(text))


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


def money(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ") + " $"


def pfr(x, digits: int = 1) -> str:
    """Percentage in French style: 8,2 %."""
    if x is None:
        return "—"
    return f"{x * 100:.{digits}f}".replace(".", ",") + " %"


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
    "CAPACITY_TOLERANCE_GAP": "Votre capacité et votre tolérance au risque ne concordent pas : le niveau suit la plus basse.",
    "EMERGENCY_FUND_SHORT": "Votre coussin d'urgence est plus petit que la cible : le remplir passe avant d'investir.",
    "SAVINGS_OVERCOMMITTED": "Vos objectifs demandent plus d'épargne mensuelle que ce que vous pouvez mettre de côté.",
    "HIGH_DEBT": "Vos dettes sont élevées par rapport à votre revenu : les rembourser est un rendement garanti.",
    "EXPECTATION_GAP": "Le rendement que vous espérez dépasse les hypothèses prudentes pour votre niveau.",
    "ESG_DATA_LIMIT": "Les préférences ESG passent par des exclusions et un fonds filtré; nous n'avons pas de cotes ESG.",
    "CRYPTO_NO_EXPERIENCE": "Crypto désactivée : votre profil n'indique pas d'expérience en placement.",
    "CRYPTO_NOT_ALLOWED": "Votre niveau ne permet pas de crypto : une préférence ne dépasse jamais une limite.",
    "LEVEL_LOWERED": "Vous avez choisi un niveau plus prudent que celui recommandé.",
    "HORIZON_CAP": "Votre horizon limite le niveau de risque.",
    "NO_EMERGENCY_FUND": "Vous n'avez pas de coussin d'urgence.",
    "GOAL_NOT_REACHABLE": "Un objectif n'est pas atteignable tel quel.",
}
ACCOUNT_FR = {"emergency_fund": "CELI ou compte épargne à intérêt élevé", "home_purchase": "CELIAPP",
              "project": "CELI", "retirement": "REER, puis CELI", "income": "CELI, puis non enregistré",
              "legacy": "Non enregistré ou CELI (voir un planificateur successoral)"}
LEVEL_FOR_FR = {1: "horizons courts, peu de confort avec les variations ou argent requis bientôt",
                2: "approche de la retraite ou horizons moyens, priorité à la stabilité",
                3: "horizons moyens à longs, équilibre entre croissance et stabilité",
                4: "longs horizons et confort avec des baisses temporaires importantes",
                5: "très longs horizons, capacité ET tolérance élevées"}
RISK_FR = {"market": "Marché", "credit": "Crédit", "liquidity": "Liquidité", "currency": "Devise",
           "concentration": "Concentration", "inflation": "Inflation"}
LEVEL_FR = {"low": "faible", "moderate": "modéré", "high": "élevé"}
DOT = {"low": "🟢", "moderate": "🟡", "high": "🔴"}
FIT_LABEL = {"Good fit": "Bonne adéquation", "Possible, in a small position": "Possible en petite position",
             "Poor fit": "Mauvaise adéquation", "Not suitable": "Non adapté à votre profil",
             "Insufficient data": "Données insuffisantes"}
POT_LABEL = {"Strong measured growth": "Croissance solide", "Moderate measured growth": "Croissance modérée",
             "Weak measured growth": "Croissance faible", "Insufficient data": "Données insuffisantes",
             "Not applicable": "Non applicable"}
FACTOR_FR = {"revenue_growth": "Croissance des revenus", "earnings_growth": "Croissance des bénéfices",
             "margin_trend": "Évolution de la marge", "fcf_margin": "Flux de trésorerie libre",
             "debt_to_equity": "Endettement", "analyst_eps_growth": "Prévision des analystes (opinion)",
             "volatility": "Variations du prix", "max_drawdown": "Pire chute vs perte acceptée",
             "recovery_vs_horizon": "Temps de récupération vs horizon", "preferences": "Vos préférences",
             "portfolio_impact": "Effet sur votre portefeuille"}
VERDICT_FR = {"reconsider": "🔴 À reconsidérer", "proceed with care": "🟡 Avec prudence",
              "no major objection": "🟢 Pas d'objection majeure"}
CHALLENGE_FR = {"SINGLE_SECURITY": "Trop gros pour un seul titre", "EQUITY_ABOVE_RANGE": "Trop d'actions pour votre niveau",
                "SECTOR": "Trop concentré dans un secteur", "RISK_CONCENTRATION": "Un titre porte la majorité du risque",
                "CRYPTO_ABOVE_LIMIT": "Trop de crypto pour votre niveau", "EXCLUDED_SECTOR": "Contraire à vos valeurs",
                "RISK_JUMP": "Le risque grimpe fortement", "HORIZON_MISMATCH": "Trop long à récupérer pour votre horizon",
                "RECENCY_BIAS": "Biais de récence", "HIDDEN_CONCENTRATION": "Diversification moins grande qu'il n'y paraît",
                "HOME_BIAS": "Biais domestique", "HYPE": "Beaucoup de bruit médiatique",
                "NEWS_EXPOSURE": "Dépendance à un sujet d'actualité",
                "GOLD_ABOVE_LIMIT": "Trop d'or", "EQUITY_BELOW_RANGE": "Peu d'actions pour votre niveau"}


def horizon_txt(y: float) -> str:
    return "immédiat" if y == 0 else f"{y:g} an(s)"


def level_txt(g) -> str:
    return "Liquidités" if g.level_name == "Cash reserve" else pf.level_card(g.level)["fr"]


def show_flags(flags, detailed: bool):
    for f in flags:
        msg = FLAG_FR.get(f.code, f.message)
        if detailed and f.code in FLAG_FR:
            msg += f"  \nDétail : {f.message}"
        (st.warning if f.severity == "warning" else st.info)(esc(msg))


def risk_text(r) -> str:
    v = r.value
    if r.kind == "market":
        return f"Ce mélange a varié d'environ {pfr(v, 0)} par année; les placements peuvent baisser ensemble."
    if r.kind == "credit":
        return f"{pfr(v, 0)} en fonds d'obligations, surtout gouvernementales et de bonne qualité."
    if r.kind == "liquidity":
        return f"{pfr(v, 0)} en actifs peu échangés ou en crypto."
    if r.kind == "currency":
        return f"{pfr(v, 0)} en dollars américains : la valeur en CAD bouge avec le taux de change."
    if r.kind == "concentration":
        return (f"La plus grosse position individuelle porte {pfr(v, 0)} du risque." if v > 0 else
                "Aucune entreprise seule ne domine : le risque est réparti dans des fonds larges.")
    if r.kind == "inflation":
        return f"Rendement réel supposé d'environ {pfr(v)} par an après inflation (hypothèse)."
    return r.reason


def fit_sentence(fit: dict, risk: dict) -> str:
    if fit["label"] == "Not suitable":
        return fit["notes"][0] if fit["notes"] else "Ce placement ne respecte pas vos préférences ou vos limites."
    scored = [f for f in fit["factors"] if f["score"] is not None]
    worst = min(scored, key=lambda f: f["score"]) if scored else None
    if worst is None or worst["score"] >= 0.6:
        return "Son comportement passé reste dans les limites de votre profil."
    mdd = risk["max_drawdown"]["value"]
    return {
        "volatility": "Son prix varie beaucoup plus que ce que votre profil accepte pour un seul titre.",
        "max_drawdown": f"Sa pire chute ({pfr(mdd, 0)}) dépasse largement la perte que vous acceptez dans une mauvaise année.",
        "recovery_vs_horizon": "Il a mis longtemps à se remettre de sa pire chute, par rapport à votre horizon.",
        "preferences": "Il va à l'encontre de vos préférences.",
        "portfolio_impact": "L'ajouter déséquilibrerait votre portefeuille actuel.",
    }.get(worst["name"], "Un des critères de votre profil n'est pas respecté.")


def potential_sentence(pot: dict) -> str:
    scored = [f for f in pot["factors"] if f["score"] is not None]
    if not scored:
        return ""
    best = max(scored, key=lambda f: f["score"])
    worst = min(scored, key=lambda f: f["score"])
    out = []
    if best["score"] >= 0.6:
        out.append(f"Point fort : {FACTOR_FR.get(best['name'], best['name']).lower()}.")
    if worst["score"] < 0.5:
        out.append(f"Point faible : {FACTOR_FR.get(worst['name'], worst['name']).lower()}.")
    return " ".join(out) or "Aucun facteur ne ressort nettement."


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


@st.cache_data(show_spinner=False, ttl=3600)
def news_digest(symbol: str) -> dict | None:
    try:
        return news.digest(symbol, news.recent_headlines(symbol)).to_dict()
    except Exception:
        return None


@st.cache_data(show_spinner=False, ttl=3600)
def macro_items() -> list[dict]:
    try:
        return macro_news.recent()
    except Exception:
        return []


@st.cache_data(show_spinner=False, ttl=3600)
def article_texts(symbol: str) -> dict | None:
    try:
        return news.read_texts([h for h in news.recent_headlines(symbol) if news.is_relevant(h)])
    except Exception:
        return None


MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
PUBLISHER_SHORT = {"Bank of Canada": "Banque du Canada", "Federal Reserve": "Réserve fédérale (É.-U.)",
                   "Statistics Canada": "Statistique Canada"}
VERDICT_ANALOG = {"clear": "écart net", "unclear": "pas d'effet net", "too_few": "trop peu de cas"}


def date_fr(iso: str) -> str:
    y, mth, d = iso[:10].split("-")
    return f"{int(d)} {MOIS[int(mth) - 1]} {y}"


def news_box(weights: dict, amount: float) -> None:
    """Official global news, read in full, mapped to the investor's own portfolio."""
    st.markdown("#### L'actualité et votre portefeuille")
    items = macro_items()
    if not items:
        note("Communiqués officiels indisponibles pour le moment (connexion aux sites de la Banque du Canada, "
             "de la Fed et de Statistique Canada).")
        return
    imp = macro_news.impact(weights, universe, items, px_cad, amount=amount, top=5 if detailed else 3)
    for it in imp["items"]:
        with bordered():
            note(f"{date_fr(it['published_at'])} · {PUBLISHER_SHORT.get(it['publisher'], it['publisher'])} · "
                 f"{it['factor_fr']}")
            say(f"**{it['fact']}**")
            say(it["message"])
            say(it["note"])
            if detailed:
                with st.expander("Le texte, les placements touchés et le passé"):
                    say("**Ce que dit le texte officiel**")
                    for q in it["quotes"]:
                        tag = "fait" if q["kind"] == "fact" else "prévision de la source"
                        say(f"> {q['text']}  \n> *({tag})*")
                    note(f"Statut du texte : {it['text_status_fr']}. {it['forward_share'] * 100:.0f} % des phrases sont des "
                         f"prévisions de la source. Analyse : {it['analyzer']}. [Lire le communiqué]({it['link']})")
                    lines = it["exposure"]["lines"]
                    if lines:
                        st.dataframe(pd.DataFrame([{"Placement": x["name"], "Part": pfr(x["weight"], 0),
                                                    "Lien": "direct" if x["channel"] == "direct" else "indirect",
                                                    "Pourquoi": x["reason"]} for x in lines]),
                                     hide_index=True, **stretch(st.dataframe))
                    an = it["analog"]
                    if an:
                        say(f"**Après {an['n_events']} événements semblables** ({date_fr(an['first'])} au "
                            f"{date_fr(an['last'])}), sur les {an['horizon_days']} jours ouvrables suivants :")
                        st.dataframe(pd.DataFrame([{
                            "Placement": universe.loc[r["ticker"], "name"] if r["ticker"] in universe.index else r["ticker"],
                            "Moyenne après": pfr(r["mean_after"]), "D'habitude": pfr(r["usual"]),
                            "En hausse": f"{r['hit_rate'] * 100:.0f} % des cas", "Verdict": VERDICT_ANALOG[r["verdict"]]}
                            for r in an["rows"]]), hide_index=True, **stretch(st.dataframe))
                        note(an["caveat"])
                    elif it.get("analog_note"):
                        note(it["analog_note"])
                    if it["stress"]:
                        stv = it["stress"]
                        say(f"**Test de stress lié** (hypothèse, pas une prévision) : {money(stv['dollars'])} "
                            f"({pfr(stv['portfolio_return'])}) si {STRESS_FR.get(stv['scenario'], stv['label'])}.")
    note(f"{imp['notes'][0]} Sources : {', '.join(PUBLISHER_SHORT.get(x, x) for x in imp['sources'])}. "
         "Les nouvelles expliquent ce qui fait bouger votre argent; elles ne changent pas votre répartition "
         "(réagir à l'actualité, c'est tenter de deviner le marché).")


STRESS_FR = {"rates_up_1pt": "les taux montaient d'un point de pourcentage",
             "stocks_and_bonds_down": "les actions et les obligations baissaient ensemble",
             "equity_crash": "les actions chutaient fortement"}


try:
    px_cad, px_local, universe, dollar_vol = load()
except FileNotFoundError as e:
    st.error(esc(f"Données de départ manquantes. {e}"))
    st.stop()

ss = st.session_state
ss.setdefault("user", None)
ss.setdefault("step", 1)
ss.setdefault("draft", None)

# ----------------------------------------------------------------------------- header

h1, h2 = st.columns([5, 1])
h1.title("🧭 WealthPilot")
h1.caption("Simulation éducative · comptes et montants fictifs · aucune transaction réelle · pas un conseil financier")
if ss.user:
    h2.write(f"👤 **{ss.user}**")
    if h2.button("Se déconnecter"):
        for k in ("user", "draft", "onboarding", "chosen_level"):
            ss.pop(k, None)
        ss.step = 1
        st.rerun()

# ----------------------------------------------------------------------------- authentication

if not ss.user:
    st.info("Créez un compte **fictif** pour la démo. N'utilisez pas un vrai mot de passe ni vos vraies données bancaires.")
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
                    st.error(esc(str(e)))
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
        note(message)


if not ss.get("onboarding"):
    if ss.draft is None:
        ss.draft = blank_draft()
    d = ss.draft
    f = d["financials"]
    st.subheader(f"Créer votre profil · étape {ss.step} de {len(STEPS)} : {STEPS[ss.step - 1]}")
    st.progress(ss.step / len(STEPS))

    if ss.step == 1:
        note("Pour la démo, vous pouvez partir d'un persona du cas.")
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
        note("Des montants approximatifs suffisent. Ils mesurent votre capacité à absorber une baisse.")
        a, b = st.columns(2)
        f["annual_income"] = float(a.number_input("Revenu annuel brut (en dollars)", 0, 10_000_000, int(f["annual_income"]), step=1000))
        f["monthly_expenses"] = float(b.number_input("Dépenses par mois", 0, 1_000_000, int(f["monthly_expenses"]), step=100))
        f["monthly_savings"] = float(a.number_input("Épargne possible par mois", 0, 1_000_000, int(f["monthly_savings"]), step=50))
        f["cash_savings"] = float(b.number_input("Épargne disponible (compte épargne)", 0, 100_000_000, int(f["cash_savings"]), step=1000))
        f["investments"] = float(a.number_input("Montant à investir dans la simulation", 0, 100_000_000, int(f["investments"]), step=1000))
        f["other_assets"] = float(b.number_input("Autres actifs, nets d'hypothèque (maison, etc.)", 0, 100_000_000, int(f["other_assets"]), step=1000))
        f["debts"] = float(a.number_input("Dettes hors hypothèque (prêt étudiant, auto, cartes)", 0, 100_000_000, int(f["debts"]), step=1000))
        valid = f["monthly_expenses"] > 0
        if valid:
            fin = ob.Financials(**f)
            m = st.columns(3)
            m[0].metric("Valeur nette", money(fin.net_worth))
            m[1].metric("Coussin", f"{fin.emergency_months:.1f} mois".replace(".", ","))
            m[2].metric("Taux d'épargne", pfr(fin.savings_rate, 0))
            if fin.monthly_savings > fin.annual_income / 12 - fin.monthly_expenses + 1:
                st.warning("L'épargne indiquée dépasse votre revenu moins vos dépenses. Vérifiez les montants.")
        nav(valid=valid, message="Indiquez vos dépenses par mois.")

    elif ss.step == 3:
        fin = ob.Financials(**f)
        note("Chaque objectif a son propre horizon : il aura son propre sous-portefeuille.")
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
                c = st.columns(4)
                if gtype == "emergency_fund":
                    g["horizon_years"] = 0.0
                    c[0].markdown("Horizon : **immédiat**")
                else:
                    g["horizon_years"] = float(c[0].number_input("Dans combien d'années ?", 0.5, 60.0, float(max(g["horizon_years"], 0.5)), step=0.5, key=f"gh_{gtype}"))
                g["target_amount"] = float(c[1].number_input("Montant visé", 0, 100_000_000, int(g["target_amount"]), step=1000, key=f"gt_{gtype}"))
                g["current_amount"] = float(c[2].number_input("Déjà de côté", 0, 100_000_000, int(g["current_amount"]), step=1000, key=f"gc_{gtype}"))
                g["monthly_contribution"] = float(c[3].number_input("Par mois", 0, 1_000_000, int(g["monthly_contribution"]), step=50, key=f"gm_{gtype}"))
                if gtype == "emergency_fund":
                    note(f"Cible suggérée : {money(fin.emergency_target())}, soit "
                         f"{fin.emergency_target() / fin.monthly_expenses:.0f} mois de dépenses.")
            new_goals.append(g)
        d["goals"] = new_goals
        total = sum(g["monthly_contribution"] for g in new_goals)
        say(f"Épargne planifiée : **{money(total)}** par mois, pour une capacité de **{money(fin.monthly_savings)}**.")
        nav(valid=bool(new_goals), message="Choisissez au moins un objectif.")

    elif ss.step == 4:
        t = d["tolerance"]
        amount = max(f["investments"], 1000.0)
        note("Ces questions mesurent votre tolérance : ce que vous vivriez bien, avec vos propres montants.")
        t["drop_reaction"] = st.radio(esc(f"Vos placements de {money(amount)} valent {money(amount * 0.8)} après quelques mois. "
                                          "Que faites-vous ?"), list(FR["drop_reaction"]),
                                      index=list(FR["drop_reaction"]).index(t["drop_reaction"]), format_func=FR["drop_reaction"].get)
        t["range_choice"] = st.radio("Sur un an, quel résultat accepteriez-vous ?", list(RANGES),
                                     index=list(RANGES).index(t["range_choice"]),
                                     format_func=lambda k: esc(f"Entre {money(amount * (1 + RANGES[k][1]))} et "
                                                               f"{money(amount * (1 + RANGES[k][0]))}"))
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
        say("**Thèmes qui vous intéressent** (facultatif)")
        note("Ils deviennent de petites positions, toujours à l'intérieur de vos limites.")
        chosen = set(strategist.normalize_themes(pr.get("themes", ())))
        cols = st.columns(3)
        picked = []
        for i, (key, (label, tickers)) in enumerate(strategist.THEMES.items()):
            if cols[i % 3].checkbox(label, value=key in chosen, key=f"th_{key}"):
                picked.append(key)
        pr["themes"] = picked
        with st.expander("Autres préférences (facultatif)"):
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
        say(f"Convient aux {LEVEL_FOR_FR[p.level]}.")
        a, b = st.columns(2)
        a.metric("Capacité de risque", f"{p.capacity:.0f}/100", help="Ce que votre situation financière permet")
        b.metric("Tolérance au risque", f"{p.tolerance:.0f}/100", help="Ce que vous vivriez bien")
        note("Votre niveau suit la plus basse des deux. Chaque objectif est ensuite ajusté selon son horizon.")
        show_flags([x for x in p.flags if x.severity == "warning"], detailed=False)
        plan = gl.plan(p, o.goals, px_cad)
        for g in plan.goals:
            say(f"• **{g.goal.name}** : {level_txt(g)}")
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

detailed = st.sidebar.toggle("Plus de détails", value=False,
                             help="Affiche les calculs, les facteurs et les sources derrière chaque résultat.")
st.sidebar.caption("La vue simple montre l'essentiel. Les détails restent disponibles à tout moment.")

tabs = st.tabs(["Mon plan", "Titre", "Machine à remonter le temps", "Avocat du diable", "Labo", "Mon profil"])

# ---- Mon plan
with tabs[0]:
    card = pf.level_card(profile.level)
    st.markdown(f"### Profil {card['fr']} · {card['score_10']}/10")
    say(f"{money(plan.total_amount)} répartis sur {len(plan.goals)} objectif(s), chacun selon son horizon.")
    checks = gl.check_plan(profile, plan, universe, px_cad)
    cols = st.columns(len(plan.goals))
    for col, g in zip(cols, plan.goals):
        with col, bordered():
            st.markdown(f"#### {g.goal.name}")
            note(f"{level_txt(g)} · horizon {horizon_txt(g.goal.horizon_years)}")
            labels = [universe.loc[t, "name"] if t in universe.index else t for t in g.weights]
            fig = go.Figure(go.Pie(labels=labels, values=list(g.weights.values()), hole=0.6, sort=True))
            fig.update_traces(textinfo="none", hovertemplate="%{label}<br>%{percent}<extra></extra>")
            fig.update_layout(height=200, margin=dict(t=0, b=0, l=0, r=0), showlegend=detailed,
                              legend=dict(orientation="h", font=dict(size=10)))
            st.plotly_chart(fig, key=f"pie_{g.goal.name}", **stretch(st.plotly_chart))
            ga = g.goal_analysis
            if ga.get("kind") == "cushion":
                if ga["reachable"]:
                    st.success("Coussin complet.")
                elif ga["months_to_fill"]:
                    st.warning(esc(f"Il manque {money(ga['gap'])}, environ {ga['months_to_fill']:.0f} mois au rythme actuel."))
                else:
                    st.warning(esc(f"Il manque {money(ga['gap'])}. Prévoyez un montant mensuel."))
            elif ga["reachable"]:
                st.success("En bonne voie selon nos hypothèses.")
            else:
                need = ga.get("monthly_contribution_needed")
                st.warning(esc("Pas atteignable tel quel" + (f" : il faudrait environ {money(need)} par mois." if need else ".")))
            for v in checks[g.goal.name]:
                if v.severity == "warning":
                    st.error(esc(v.message))
            note(f"Compte suggéré : {ACCOUNT_FR.get(g.goal.type, g.account)}")
            if detailed:
                with st.expander("Pourquoi cette répartition"):
                    say(g.why_level)
                    for r in g.reasons:
                        say(f"• **{r['ticker']}** {pfr(r['weight'])} : {r['reason']}")
                    if ga.get("kind") != "cushion":
                        note(f"Rendement requis {pfr(ga['required_return'])} par an; hypothèse {pfr(ga['assumed_return'])} "
                             f"par an ({pf.assumptions.SOURCE['name']}).")
                with st.expander("Ce qui changerait cette réponse"):
                    for c in whatif.goal_conditions(profile, g.goal):
                        say(f"• {c.condition} → {c.effect}")
    news_box(weights, plan.total_amount)
    rm = risks.risk_map(weights, universe, px_cad, dollar_vol, expected_nominal=profile.expected["net"])
    attention = [r for r in rm if r.level != "low"]
    st.markdown("#### Points d'attention")
    if not attention:
        say("Aucun risque élevé ou modéré ne ressort.")
    for r in attention:
        say(f"{DOT[r.level]} **{RISK_FR[r.kind]}** ({LEVEL_FR[r.level]}) : {risk_text(r)}")
    if detailed:
        with st.expander("Les six risques en détail"):
            for r in rm:
                say(f"{DOT[r.level]} **{RISK_FR[r.kind]}** : {LEVEL_FR[r.level]} · {r.metric} = {r.value:.3f}")
                note(r.reason)

# ---- Titre
with tabs[1]:
    c1, c2 = st.columns([1, 2])
    symbol = c1.text_input("Rechercher un titre", "NVDA", help="Exemples : NVDA, RY.TO, SPY, BTC-USD").strip().upper()
    tf = c2.radio("Période", list(tk.TIMEFRAMES), index=5, horizontal=True)
    source = tk.auto_source()
    live = isinstance(source, tk.YFinanceSource)
    if not live and symbol not in universe.index:
        st.warning(esc(f"{symbol} n'est pas dans les données hors ligne. Installez yfinance (pip install yfinance) "
                       "pour chercher n'importe quel titre."))
    else:
        try:
            try:
                ov = tk.overview(symbol, source, profile=eff, portfolio=weights, universe=universe, prices_cad=px_cad)
                ch = tk.chart(source, symbol, tf)
            except Exception as e:
                if not live or symbol not in universe.index:
                    raise
                note(f"Données en direct indisponibles ({type(e).__name__}); données hors ligne utilisées.")
                source, live = tk.StarterSource(), False
                ov = tk.overview(symbol, source, profile=eff, portfolio=weights, universe=universe, prices_cad=px_cad)
                ch = tk.chart(source, symbol, tf)
            idn = ov["identity"]
            st.subheader(esc(f"{idn['name'] or symbol} ({symbol})"))
            ys = [q["close"] for q in ch["points"]]
            cf = go.Figure(go.Scatter(x=[q["t"] for q in ch["points"]], y=ys, line=dict(width=2)))
            if ys:
                cf.update_yaxes(range=[min(ys) * 0.97, max(ys) * 1.03])
            cf.update_layout(height=260, margin=dict(t=10, b=10))
            st.plotly_chart(cf, **stretch(st.plotly_chart))

            fit, pot, lra = ov["fit_score"], ov["potential_score"], ov["long_run_assumption"]
            a, b = st.columns(2)
            with a, bordered():
                st.markdown("**Pour votre profil**")
                st.metric("Adéquation", f"{fit['score']:.0f}/100" if fit["score"] is not None else "—",
                          label_visibility="collapsed")
                say(f"**{FIT_LABEL.get(fit['label'], fit['label'])}**. {fit_sentence(fit, ov['risk'])}")
            with b, bordered():
                st.markdown("**Potentiel, sans biais**")
                if pot["score"] is not None:
                    st.metric("Potentiel", f"{pot['score']:.0f}/100", label_visibility="collapsed")
                    say(f"**{POT_LABEL.get(pot['label'], pot['label'])}**. {potential_sentence(pot)}")
                elif lra:
                    st.metric("Potentiel", pfr(lra["annual_return"]) + " par an", label_visibility="collapsed")
                    say("**Fonds diversifié** : son potentiel est celui de son marché. Rendement à long terme supposé, "
                        "pas une prévision.")
                elif pot["label"] == "Not applicable":
                    st.metric("Potentiel", "—", label_visibility="collapsed")
                    say("**Non évaluable** : pas d'états financiers ni d'hypothèse reconnue pour cet actif.")
                else:
                    st.metric("Potentiel", "—", label_visibility="collapsed")
                    say("**Données insuffisantes** pour mesurer la croissance de l'entreprise."
                        + ("" if live else " Installez yfinance pour obtenir les états financiers."))
                note("Basé seulement sur des données mesurées : ni opinions d'analystes, ni nouvelles, ni votre profil.")

            m = st.columns(3)
            m[0].metric("Sur 1 an", pfr(ov["returns"]["1Y"]["value"], 0))
            m[1].metric("Pire chute (5 ans)", pfr(-ov["risk"]["max_drawdown"]["value"], 0) if ov["risk"]["max_drawdown"]["value"] else "—")
            vol = ov["risk"]["volatility_full"]["value"]
            m[2].metric("Variations", "fortes" if vol and vol > 0.35 else "moyennes" if vol and vol > 0.18 else "faibles",
                        help=f"Volatilité annuelle de {pfr(vol, 0)}")

            dg = news_digest(symbol)
            st.markdown("#### Nouvelles récentes")
            if dg is None:
                note("Nouvelles indisponibles pour le moment (connexion à Yahoo Finance).")
            elif dg["n"] == 0:
                note("Aucune manchette récente ne porte vraiment sur ce titre.")
            else:
                n_op = round(dg["share_predictive"] * dg["n"])
                say(f"Sur {dg['n']} manchettes récentes : **{dg['n'] - n_op} faits** et **{n_op} opinions ou prévisions**"
                    + (f", dont beaucoup de sources peu fiables." if dg["hype_share"] >= 0.4 else "."))
                for x in dg["top_descriptive"][:2]:
                    say(f"• {x['title']} ({x['publisher']})")
                if detailed and dg["top_predictive"]:
                    say("**Opinions et prévisions**")
                    for x in dg["top_predictive"][:3]:
                        say(f"• {x['title']} ({x['publisher']}, confiance {x['trust']:.2f})".replace("confiance 0.", "confiance 0,"))

            if dg is not None and dg["n"] > 0:
                at = article_texts(symbol)
                if at is not None:
                    note(at["note"])
                    if detailed:
                        for r in [r for r in at["rows"] if r["status"] == "ok"][:3]:
                            for q in r.get("quotes", []):
                                say(f"> {q}")
            if detailed:
                with st.expander("Comment les deux scores sont calculés"):
                    for title, sc in (("Adéquation à votre profil", fit), ("Potentiel (données mesurées)", pot)):
                        say(f"**{title}**")
                        rows = [{"Facteur": FACTOR_FR.get(x["name"], x["name"]),
                                 "Valeur": "—" if x["value"] is None else f"{x['value']:.3g}",
                                 "Note (0 à 1)": "—" if x["score"] is None else round(x["score"], 2),
                                 "Poids": x["weight"], "Règle": x["explanation"]} for x in sc["factors"]]
                        if rows:
                            st.dataframe(pd.DataFrame(rows), hide_index=True, **stretch(st.dataframe))
                        for n_ in sc["notes"]:
                            note(n_)
                    op = ov["fundamentals"]["analyst_target_upside"]["value"]
                    if op is not None:
                        note(f"Pour information, les analystes visent en moyenne {pfr(op, 0)} de hausse : une opinion, "
                             "exclue du score de potentiel.")
                with st.expander("Rendements et risque"):
                    rows = [{"Période": k, "Rendement": pfr(v["value"]), "Détail": v["detail"]} for k, v in ov["returns"].items()]
                    st.dataframe(pd.DataFrame(rows), hide_index=True, **stretch(st.dataframe))
                    rows = [{"Mesure": k, "Valeur": "—" if v["value"] is None else round(v["value"], 3), "Détail": v["detail"]}
                            for k, v in ov["risk"].items()]
                    st.dataframe(pd.DataFrame(rows), hide_index=True, **stretch(st.dataframe))
                with st.expander("Données fondamentales et provenance"):
                    rows = [{"Donnée": k, "Valeur": "—" if v["value"] is None else v["value"],
                             "Type": {"computed": "calculé", "provider": "fournisseur", "opinion": "opinion"}[v["source"]],
                             "Détail": v["detail"]} for k, v in ov["fundamentals"].items()]
                    st.dataframe(pd.DataFrame(rows).astype(str), hide_index=True, **stretch(st.dataframe))
                    note(f"Source : {ov['data']['source']}. {ov['data']['price_basis']}.")
        except Exception as e:
            st.error(esc(f"{symbol} : {e}"))

# ---- Machine à remonter le temps
with tabs[2]:
    amount = float(max(plan.total_amount, 1000))
    r = tm.replay(weights, px_cad, eff, amount, cpi_index=cpi())
    d_ = r.worst_drawdown
    say(f"Votre plan, rejoué sur les cinq dernières années avec vos {money(amount)}.")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=r.path.index, y=r.path["value"], name="Valeur", line=dict(width=2)))
    if detailed and "value_real" in r.path:
        fig.add_trace(go.Scatter(x=r.path.index, y=r.path["value_real"], name="Après inflation", line=dict(dash="dot")))
    fig.add_vrect(x0=d_["peak_date"], x1=d_["trough_date"], fillcolor="red", opacity=0.08, line_width=0)
    fig.update_layout(height=320, margin=dict(t=10, b=10), legend=dict(orientation="h"), showlegend=detailed)
    st.plotly_chart(fig, **stretch(st.plotly_chart))
    with bordered():
        say(f"Au pire moment ({d_['trough_date']}), vos {money(amount)} auraient valu **{money(d_['trough_value'])}**, "
            f"soit {money(d_['dollars_lost'])} de moins qu'au sommet précédent.")
        say("**Auriez-vous gardé le cap ?**")
        if st.radio("Votre réponse", ["Oui", "Non"], horizontal=True, label_visibility="collapsed") == "Non":
            st.warning("C'est utile à savoir : votre tolérance réelle est peut-être plus basse. Dans « Mon profil », "
                       "vous pouvez choisir un niveau plus prudent.")
    if detailed:
        c = st.columns(4)
        c[0].metric("Valeur finale", money(r.final_value))
        c[1].metric("Après inflation", money(r.final_value_real) if r.final_value_real else "—")
        c[2].metric("Pire chute", pfr(d_["drawdown"]))
        c[3].metric("Pires 12 mois", pfr(r.worst_12_months["return"]))
        with st.expander("Scénarios hypothétiques (pas des prévisions)"):
            st.dataframe(pd.DataFrame([{"Scénario": s["label"], "Effet": pfr(s["portfolio_return"]),
                                        "En dollars": money(s["dollars"]), "Base": s["basis"]}
                                       for s in (tm.shock(weights, universe, amount, k) for k in tm.SHOCKS)]),
                         hide_index=True, **stretch(st.dataframe))

# ---- Avocat du diable
with tabs[3]:
    say("Dites ce que vous aimeriez faire : l'avocat du diable vérifie si c'est cohérent avec votre profil.")
    c1, c2 = st.columns(2)
    names = sorted(universe.index)
    asym = c1.selectbox("Je veux mettre…", names, index=names.index("TSLA"), key="adv_sym",
                        format_func=lambda t: f"{t} · {universe.loc[t, 'name']}")
    aw = c2.slider("…cette part de mon portefeuille (%)", 1, 60, 30, 1) / 100
    rv = advocate.review_trade(asym, aw, weights, eff, px_cad, universe, news_digest=news_digest(asym),
                               macro_items=macro_items())
    st.subheader(VERDICT_FR[rv.verdict])
    for ch_ in rv.challenges:
        with bordered():
            say(f"**{CHALLENGE_FR.get(ch_.code, ch_.bias)}** — {ch_.claim}")
            if ch_.counterpoint:
                say(f"↔️ {ch_.counterpoint}")
            say(f"❓ {ch_.question}")
    if detailed and rv.before_after:
        with st.expander("Avant et après, sur l'historique"):
            bb, aa = rv.before_after["before"], rv.before_after["after"]
            names_fr = {"cagr": "Rendement annuel", "volatility": "Volatilité", "max_drawdown": "Pire chute", "sharpe": "Sharpe"}
            st.dataframe(pd.DataFrame({"Avant": [pfr(bb[k]) if k != "sharpe" else f"{bb[k]:.2f}" for k in names_fr],
                                       "Après": [pfr(aa[k]) if k != "sharpe" else f"{aa[k]:.2f}" for k in names_fr]},
                                      index=list(names_fr.values())), **stretch(st.dataframe))
            note(f"Historique {rv.before_after['window']}, en dollars canadiens.")
    st.divider()
    st.markdown("#### Conseiller (agents Claude sur Amazon Bedrock)")
    if not (os.environ.get("WEALTHPILOT_LLM") or os.environ.get("ANTHROPIC_API_KEY")):
        note("Agents non connectés dans cette démo locale. Définir WEALTHPILOT_LLM=bedrock (AWS) ou "
             "WEALTHPILOT_LLM=anthropic pour poser des questions en texte libre.")
    else:
        q = st.chat_input("Posez votre question")
        if q:
            from wealthpilot.agents import Session, ask
            from wealthpilot.agents.llm import from_env
            sess = Session.from_starter()
            sess.profile, sess.portfolio, sess.amount = eff, weights, plan.total_amount
            with st.spinner("Les agents travaillent…"):
                ans = ask(sess, q, from_env())
            say(ans.text)
            if detailed:
                with st.expander("Reçus (trace d'exécution)"):
                    st.json([x.to_dict() for x in sess.ledger.receipts])

# ---- Labo
with tabs[4]:
    say("Testez une règle d'achat et de vente sur un titre, honnêtement : sur une période qu'elle n'a jamais vue.")
    c1, c2 = st.columns(2)
    names = sorted(px_local.columns)
    lsym = c1.selectbox("Titre", names, index=names.index("TSLA"))
    strat_fr = {"ma_crossover": "Croisement de moyennes mobiles", "rsi": "RSI (acheter les creux)",
                "bollinger": "Bandes de Bollinger", "macd": "MACD (élan)", "breakout": "Cassure de sommet"}
    strat = c2.selectbox("Règle", list(strat_fr), format_func=strat_fr.get)
    with st.spinner("Test en cours…"):
        res = lab.evaluate(px_local[lsym], strat, lsym, profile=profile, risk_free_annual=0.025)
    so, bo = res.out_of_sample, res.buy_hold_out_of_sample
    better = so["total_return"] > bo["total_return"]
    with bordered():
        say(f"Sur la période de test (après le {res.split_date}), la règle a fait **{pfr(so['total_return'])}**, contre "
            f"**{pfr(bo['total_return'])}** en gardant simplement le titre.")
        say("✅ Elle a fait mieux sur cette période, ce qui reste une seule période." if better else
            "❌ Elle a fait moins bien que de simplement garder le titre.")
    if detailed:
        tbl = pd.DataFrame({"Règle (optimisation)": res.in_sample, "Garder (optimisation)": res.buy_hold_in_sample,
                            "Règle (test)": res.out_of_sample, "Garder (test)": res.buy_hold_out_of_sample}
                           ).loc[["total_return", "cagr", "volatility", "sharpe", "max_drawdown", "trades", "costs_paid"]]
        st.dataframe(tbl.apply(pd.to_numeric, errors="coerce").style.format("{:.3f}", na_rep="—"), **stretch(st.dataframe))
        for fnd in res.findings:
            note(fnd["message"])
        note(f"{res.combinations_tested} combinaisons testées · paramètres retenus {res.params}")
    note("Le labo répond à « qu'est-ce qui se serait passé ? », jamais à « achetez maintenant ».")

# ---- Mon profil
with tabs[5]:
    card = pf.level_card(base_profile.level)
    st.markdown(f"### Niveau recommandé : {card['fr']} · {card['score_10']}/10")
    say(f"Convient aux {LEVEL_FOR_FR[base_profile.level]}.")
    a, b = st.columns(2)
    a.metric("Capacité de risque", f"{base_profile.capacity:.0f}/100")
    b.metric("Tolérance au risque", f"{base_profile.tolerance:.0f}/100")
    show_flags([x for x in base_profile.flags if detailed or x.severity == "warning"], detailed)
    if detailed:
        fin = o.financials
        m = st.columns(4)
        m[0].metric("Valeur nette", money(fin.net_worth))
        m[1].metric("Coussin", f"{fin.emergency_months:.1f} mois".replace(".", ","))
        m[2].metric("Taux d'épargne", pfr(fin.savings_rate, 0))
        m[3].metric("Dette / revenu", pfr(fin.debt_to_income, 0))
        with st.expander("D'où vient votre capacité"):
            for r in base_profile.reasons:
                if r.dimension == "capacity":
                    say(f"• {r.label} : {r.contribution:.1f} points")
    if base_profile.level > 1:
        lvl = st.select_slider("Préférer un niveau plus prudent (jamais plus risqué que recommandé)",
                               options=list(range(1, base_profile.level + 1)), value=min(ss.chosen_level, base_profile.level),
                               format_func=lambda n: f"{n} · {pf.level_card(n)['fr']}")
        if lvl != ss.chosen_level:
            ss.chosen_level = lvl
            st.rerun()
    else:
        note("Vous êtes déjà au niveau le plus prudent.")
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
